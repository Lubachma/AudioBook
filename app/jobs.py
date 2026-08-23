"""Suivi des jobs de conversion (SQLite) et worker de traitement en tâche de fond.

Cycle de vie d'un job :
  extracting  -> extraction du texte du PDF
  extracted   -> texte prêt, estimation du coût affichée, attente du clic "Convertir"
  converting  -> synthèse TTS chunk par chunk + assemblage ffmpeg
  done        -> MP3 disponible
  error       -> message d'erreur consultable dans l'UI
"""

import queue
import shutil
import sqlite3
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .chunker import chunk_text
from .config import settings
from .pdf_extract import ScannedPdfError, extract_text
from .tts import synthesize_edge_with_retry, synthesize_with_retry

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    language TEXT NOT NULL,
    status TEXT NOT NULL,
    char_count INTEGER NOT NULL DEFAULT 0,
    total_chunks INTEGER NOT NULL DEFAULT 0,
    done_chunks INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    voice_id TEXT NOT NULL DEFAULT '',
    engine TEXT NOT NULL DEFAULT 'elevenlabs'
)
"""

# Colonnes ajoutées après la première version : appliquées aux bases existantes.
MIGRATIONS = (
    "voice_id TEXT NOT NULL DEFAULT ''",
    "engine TEXT NOT NULL DEFAULT 'elevenlabs'",
)

# Queue FIFO consommée par le thread worker ; actions : "extract" | "convert".
_queue: queue.Queue[tuple[str, str]] = queue.Queue()
_worker_thread: threading.Thread | None = None


# ---------------------------------------------------------------- base SQLite

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    settings.ensure_dirs()
    with _connect() as conn:
        conn.execute(SCHEMA)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        for column_def in MIGRATIONS:
            column_name = column_def.split()[0]
            if column_name not in columns:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {column_def}")


def create_job(title: str, language: str, voice_id: str = "", engine: str = "") -> str:
    job_id = uuid.uuid4().hex[:12]
    with _connect() as conn:
        conn.execute(
            "INSERT INTO jobs (id, title, language, status, created_at, voice_id, engine)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (job_id, title, language, "extracting", datetime.now(timezone.utc).isoformat(), voice_id, engine),
        )
    return job_id


def get_job(job_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_jobs() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


def update_job(job_id: str, **fields) -> None:
    assignments = ", ".join(f"{key} = ?" for key in fields)
    with _connect() as conn:
        conn.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", (*fields.values(), job_id))


def delete_job(job_id: str) -> bool:
    with _connect() as conn:
        deleted = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,)).rowcount
    if deleted:
        for path in (pdf_path(job_id), text_path(job_id), audio_path(job_id)):
            path.unlink(missing_ok=True)
        shutil.rmtree(chunk_dir(job_id), ignore_errors=True)
    return bool(deleted)


def recover_interrupted() -> None:
    """Au redémarrage : les conversions interrompues redeviennent relançables."""
    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET status = 'extracted' WHERE status = 'converting'"
        )
        conn.execute(
            "UPDATE jobs SET status = 'error', error = ? WHERE status = 'extracting'",
            ("Serveur redémarré pendant l'extraction, veuillez ré-uploader le PDF.",),
        )


# ---------------------------------------------------------------- chemins

def pdf_path(job_id: str) -> Path:
    return settings.uploads_dir / f"{job_id}.pdf"


def text_path(job_id: str) -> Path:
    return settings.text_dir / f"{job_id}.txt"


def audio_path(job_id: str) -> Path:
    return settings.audio_dir / f"{job_id}.mp3"


def chunk_dir(job_id: str) -> Path:
    return settings.audio_dir / f"{job_id}_chunks"


# ---------------------------------------------------------------- worker

def start_worker() -> None:
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    init_db()
    recover_interrupted()
    _worker_thread = threading.Thread(target=_worker_loop, daemon=True)
    _worker_thread.start()


def enqueue(job_id: str, action: str) -> None:
    _queue.put((job_id, action))


def _worker_loop() -> None:
    while True:
        job_id, action = _queue.get()
        try:
            if action == "extract":
                run_extraction(job_id)
            elif action == "convert":
                run_conversion(job_id)
        except ScannedPdfError as exc:
            update_job(job_id, status="error", error=str(exc))
        except Exception as exc:  # noqa: BLE001 - toute erreur doit remonter dans l'UI
            update_job(job_id, status="error", error=str(exc))
        finally:
            _queue.task_done()


# ---------------------------------------------------------------- pipeline

def run_extraction(job_id: str) -> None:
    """PDF -> fichier texte nettoyé + comptage des caractères."""
    text = extract_text(pdf_path(job_id))
    text_path(job_id).write_text(text, encoding="utf-8")
    update_job(job_id, status="extracted", char_count=len(text), error=None)


def run_conversion(job_id: str) -> None:
    """Texte -> chunks MP3 (ElevenLabs ou edge-tts) -> assemblage ffmpeg en un MP3."""
    job = get_job(job_id)
    if job is None:
        return

    free_mb = shutil.disk_usage(settings.data_dir).free / (1024 * 1024)
    if free_mb < settings.min_free_disk_mb:
        update_job(job_id, status="error", error=f"Espace disque insuffisant ({free_mb:.0f} Mo libres).")
        return

    text = text_path(job_id).read_text(encoding="utf-8")
    chunks = chunk_text(text, settings.chunk_max_chars)
    if not chunks:
        update_job(job_id, status="error", error="Aucun texte à convertir.")
        return

    engine = job["engine"] or settings.default_engine

    out_dir = chunk_dir(job_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    update_job(job_id, status="converting", total_chunks=len(chunks), done_chunks=0, error=None)

    for i, chunk in enumerate(chunks, start=1):
        chunk_file = out_dir / f"chunk_{i:04d}.mp3"
        # Un chunk déjà présent (tentative précédente interrompue) n'est pas
        # re-synthétisé : la reprise ne re-facture pas le moteur TTS.
        if not (chunk_file.exists() and chunk_file.stat().st_size > 0):
            if engine == "edge":
                synthesize_edge_with_retry(
                    chunk,
                    chunk_file,
                    voice=job["voice_id"] or settings.default_edge_voice,
                )
            else:
                synthesize_with_retry(
                    chunk,
                    chunk_file,
                    api_key=settings.elevenlabs_api_key,
                    voice_id=job["voice_id"] or settings.elevenlabs_voice_id,
                    model_id=settings.elevenlabs_model_id,
                    language_code=job["language"] or None,
                    stability=settings.voice_stability,
                    similarity_boost=settings.voice_similarity_boost,
                )
        update_job(job_id, done_chunks=i)

    merge_chunks(out_dir, audio_path(job_id))
    shutil.rmtree(out_dir)
    update_job(job_id, status="done")


def merge_chunks(chunk_directory: Path, out_path: Path) -> None:
    """Assemble les chunks MP3 sans ré-encodage via le demuxer concat de ffmpeg.

    Les chemins de la liste sont en absolu : ffmpeg les résout par rapport au
    dossier du fichier liste, pas au répertoire courant du processus.
    """
    files = sorted(chunk_directory.glob("chunk_*.mp3"))
    list_file = chunk_directory / "concat.txt"
    list_file.write_text("".join(f"file '{f.resolve()}'\n" for f in files), encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(out_path)],
        check=True,
        capture_output=True,
    )
