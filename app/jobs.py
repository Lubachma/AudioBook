"""Suivi des jobs de conversion (SQLite) et worker de traitement en tâche de fond.

Cycle de vie d'un job :
  extracting  -> extraction du texte du PDF/EPUB (+ chapitres)
  extracted   -> texte prêt, estimation affichée, attente du clic "Convertir"
  converting  -> synthèse TTS chunk par chunk + assemblage ffmpeg (MP3 + M4B)
  done        -> audio disponible
  error       -> message d'erreur consultable dans l'UI

La file traite aussi les extraits du banc d'essai (action "preview") : l'accès aux
modèles locaux est ainsi strictement sérialisé. Au repos prolongé, les modèles
sont déchargés pour rendre la RAM.
"""

import hashlib
import json
import queue
import shutil
import sqlite3
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import audio, engines, epub_extract, pdf_extract, previews
from .chapters import Chapter, load_chapters, save_chapters
from .chunker import chunk_by_chapters
from .config import settings
from .settings_store import default_voice_for, default_engine_name

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
    engine TEXT NOT NULL DEFAULT 'elevenlabs',
    voice_label TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT 'pdf'
)
"""

SETTINGS_SCHEMA = "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"

# Colonnes ajoutées après la première version : appliquées aux bases existantes.
MIGRATIONS = (
    "voice_id TEXT NOT NULL DEFAULT ''",
    "engine TEXT NOT NULL DEFAULT 'elevenlabs'",
    "voice_label TEXT NOT NULL DEFAULT ''",
    "source_type TEXT NOT NULL DEFAULT 'pdf'",
)

# File FIFO consommée par le thread worker ; items :
#   {"action": "extract"|"convert", "job_id": str}
#   {"action": "preview", "engine": str, "voice_id": str, "language": str}
_queue: queue.Queue[dict] = queue.Queue()
_worker_thread: threading.Thread | None = None

# Après ce délai sans travail, les modèles locaux sont déchargés (RAM rendue au Mac).
IDLE_UNLOAD_SECONDS = 300


# ---------------------------------------------------------------- base SQLite

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    settings.ensure_dirs()
    with _connect() as conn:
        conn.execute(SCHEMA)
        conn.execute(SETTINGS_SCHEMA)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        for column_def in MIGRATIONS:
            column_name = column_def.split()[0]
            if column_name not in columns:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {column_def}")


def create_job(
    title: str,
    language: str,
    voice_id: str = "",
    engine: str = "",
    voice_label: str = "",
    source_type: str = "pdf",
) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _connect() as conn:
        conn.execute(
            "INSERT INTO jobs (id, title, language, status, created_at, voice_id, engine,"
            " voice_label, source_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                title,
                language,
                "extracting",
                datetime.now(timezone.utc).isoformat(),
                voice_id,
                engine,
                voice_label,
                source_type,
            ),
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
        for path in (
            source_path(job_id, "pdf"),
            source_path(job_id, "epub"),
            text_path(job_id),
            chapters_path(job_id),
            audio_path(job_id),
            m4b_path(job_id),
        ):
            path.unlink(missing_ok=True)
        shutil.rmtree(chunk_dir(job_id), ignore_errors=True)
    return bool(deleted)


def recover_interrupted() -> None:
    """Au redémarrage : conversions interrompues relançables, extractions relancées."""
    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET status = 'extracted' WHERE status = 'converting'"
        )
        extracting = conn.execute(
            "SELECT id FROM jobs WHERE status = 'extracting'"
        ).fetchall()
    # Le fichier source est encore sur disque : on relance l'extraction plutôt que
    # de demander un re-upload (qui orphelinait l'ancien fichier).
    for row in extracting:
        enqueue(row["id"], "extract")


# ---------------------------------------------------------------- chemins

def source_path(job_id: str, source_type: str) -> Path:
    return settings.uploads_dir / f"{job_id}.{source_type}"


def pdf_path(job_id: str) -> Path:  # compat historique (anciens appels/tests)
    return source_path(job_id, "pdf")


def text_path(job_id: str) -> Path:
    return settings.text_dir / f"{job_id}.txt"


def chapters_path(job_id: str) -> Path:
    return settings.text_dir / f"{job_id}.chapters.json"


def audio_path(job_id: str) -> Path:
    return settings.audio_dir / f"{job_id}.mp3"


def m4b_path(job_id: str) -> Path:
    return settings.audio_dir / f"{job_id}.m4b"


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
    _queue.put({"action": action, "job_id": job_id})


def enqueue_preview(engine_name: str, voice_id: str, language: str) -> None:
    previews.mark_pending(engine_name, voice_id, language)
    _queue.put(
        {"action": "preview", "engine": engine_name, "voice_id": voice_id, "language": language}
    )


def _mark_error_safe(job_id: str, message: str) -> None:
    """Marque un job en erreur sans jamais tuer le thread worker."""
    try:
        update_job(job_id, status="error", error=message)
    except Exception:  # noqa: BLE001 - la boucle du worker doit survivre à tout
        traceback.print_exc()


def _worker_loop() -> None:
    while True:
        try:
            item = _queue.get(timeout=IDLE_UNLOAD_SECONDS)
        except queue.Empty:
            try:
                engines.unload_all()
            except Exception:  # noqa: BLE001 - le worker doit survivre à tout
                traceback.print_exc()
            continue
        try:
            action = item["action"]
            if action == "extract":
                run_extraction(item["job_id"])
            elif action == "convert":
                run_conversion(item["job_id"])
            elif action == "preview":
                previews.run_preview(item)
        except Exception as exc:  # noqa: BLE001 - toute erreur doit remonter dans l'UI
            if item.get("job_id"):
                _mark_error_safe(item["job_id"], str(exc))
            else:
                previews.mark_error(item, str(exc))
        finally:
            _queue.task_done()


# ---------------------------------------------------------------- pipeline

def run_extraction(job_id: str) -> None:
    """PDF/EPUB -> texte nettoyé + chapitres + comptage des caractères."""
    job = get_job(job_id)
    if job is None:
        return
    source_type = job.get("source_type") or "pdf"
    source = source_path(job_id, source_type)
    if source_type == "epub":
        text, chapters = epub_extract.extract_book(source)
    else:
        text, chapters = pdf_extract.extract_book(source)
    text_path(job_id).write_text(text, encoding="utf-8")
    save_chapters(chapters_path(job_id), chapters)
    update_job(job_id, status="extracted", char_count=len(text), error=None)


def _fingerprint(engine: engines.Engine, text: str, chapters: list[Chapter]) -> str:
    """Empreinte du plan de découpage : moteur, paramètres, texte et chapitres."""
    h = hashlib.sha1()
    h.update(f"{engine.name}|{engine.chunk_ext}|{engine.chunk_max_chars}|".encode())
    h.update(hashlib.sha1(text.encode("utf-8")).digest())
    h.update(json.dumps([[c.title, c.offset] for c in chapters]).encode())
    return h.hexdigest()


def write_chunks_meta(chunk_directory: Path, engine: engines.Engine, count: int, fingerprint: str) -> None:
    meta = {
        "engine": engine.name,
        "ext": engine.chunk_ext,
        "chunk_max_chars": engine.chunk_max_chars,
        "count": count,
        "fingerprint": fingerprint,
    }
    (chunk_directory / "chunks.meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _purge_if_stale(chunk_directory: Path, fingerprint: str) -> None:
    """Vide le dossier de chunks si le plan de découpage a changé depuis la
    tentative précédente (changement de moteur, de voix de format…) : sinon la
    reprise mélangerait des chunks incompatibles."""
    meta_path = chunk_directory / "chunks.meta.json"
    stale = True
    if meta_path.exists():
        try:
            stale = json.loads(meta_path.read_text(encoding="utf-8")).get("fingerprint") != fingerprint
        except (OSError, ValueError):
            stale = True
    if stale and any(chunk_directory.iterdir()):
        shutil.rmtree(chunk_directory)
        chunk_directory.mkdir(parents=True, exist_ok=True)


def run_conversion(job_id: str) -> None:
    """Texte -> chunks audio (moteur au choix) -> assemblage ffmpeg en MP3 + M4B."""
    job = get_job(job_id)
    if job is None or job["status"] == "done":
        # Garde anti double-traitement : un livre terminé n'est jamais re-synthétisé.
        return

    free_mb = shutil.disk_usage(settings.data_dir).free / (1024 * 1024)
    if free_mb < settings.min_free_disk_mb:
        update_job(job_id, status="error", error=f"Espace disque insuffisant ({free_mb:.0f} Mo libres).")
        return

    engine_name = job["engine"] or default_engine_name()
    if engine_name == "edge":
        update_job(
            job_id,
            status="error",
            error="Le moteur edge-tts a été retiré. Supprimez ce livre et ré-uploadez-le "
            "avec un moteur local (l'audio déjà généré reste lisible).",
        )
        return
    engine = engines.get_engine(engine_name)
    available, reason = engine.availability()
    if not available:
        update_job(job_id, status="error", error=f"Moteur {engine_name} indisponible : {reason}")
        return

    text = text_path(job_id).read_text(encoding="utf-8")
    chapters = load_chapters(chapters_path(job_id))
    if not chapters:
        chapters = [Chapter(title=job["title"], offset=0)]
    chunks = chunk_by_chapters(text, chapters, engine.chunk_max_chars)
    if not chunks:
        update_job(job_id, status="error", error="Aucun texte à convertir.")
        return

    out_dir = chunk_dir(job_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = _fingerprint(engine, text, chapters)
    _purge_if_stale(out_dir, fingerprint)
    write_chunks_meta(out_dir, engine, len(chunks), fingerprint)

    voice_id = job["voice_id"] or default_voice_for(engine_name) or engine.default_voice()
    language = job["language"] or settings.default_language
    update_job(job_id, status="converting", total_chunks=len(chunks), done_chunks=0, error=None)

    engines.activate(engine_name)
    for i, (chunk, _chapter_idx) in enumerate(chunks, start=1):
        chunk_file = out_dir / f"chunk_{i:04d}.{engine.chunk_ext}"
        # Un chunk déjà présent (tentative précédente interrompue) n'est pas
        # re-synthétisé : la reprise ne re-facture/re-calcule pas le moteur TTS.
        if not (chunk_file.exists() and chunk_file.stat().st_size > 0):
            engine.synthesize_with_retry(chunk, chunk_file, voice_id=voice_id, language=language)
        update_job(job_id, done_chunks=i)

    audio.merge_book(
        out_dir,
        engine.chunk_ext,
        audio_path(job_id),
        m4b_path(job_id),
        chapter_titles=[c.title for c in chapters],
        chunk_chapters=[chapter_idx for _, chapter_idx in chunks],
        title=job["title"],
        artist=job.get("voice_label") or voice_id,
    )
    shutil.rmtree(out_dir)
    update_job(job_id, status="done")
