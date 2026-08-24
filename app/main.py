"""API FastAPI : upload PDF/EPUB, suivi des conversions, banc d'essai des voix,
streaming audio (MP3 + M4B chapitré), UI statique."""

import shutil
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import audio, covers, engines, jobs, previews
from .config import settings
from .engines import TTSError
from .settings_store import default_engine_name, default_voice_for, get_setting, set_setting

STATIC_DIR = Path(__file__).parent / "static"
CHUNK_SIZE = 1 << 20  # 1 Mo
VOICES_CACHE_TTL = 600  # secondes
ACCEPTED_EXTENSIONS = (".pdf", ".epub")

# Cache mémoire des listes de voix des moteurs cloud (évite un appel externe par page).
_voices_cache: dict[str, tuple[float, list[dict]]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    if shutil.which("ffmpeg") is None:
        print("AVERTISSEMENT : ffmpeg introuvable — les conversions échoueront à l'assemblage.")
    jobs.start_worker()
    yield


app = FastAPI(title="PDF/EPUB → Livre audio", lifespan=lifespan)


def _resolved_default_engine() -> str:
    name = default_engine_name()
    return name if name in engines.engine_names() else engines.engine_names()[0]


@app.get("/api/config")
def get_config() -> dict:
    described = engines.describe()
    for entry in described:
        entry["default_voice"] = (
            default_voice_for(entry["name"]) or engines.get_engine(entry["name"]).default_voice()
        )
        # Vitesse mesurée lors des dernières conversions (pour les estimations de l'UI).
        entry["chars_per_min"] = int(get_setting(f"speed_cpm:{entry['name']}") or 0)
    return {
        "default_language": settings.default_language,
        "default_engine": _resolved_default_engine(),
        "engines": described,
        "monthly_quota_chars": settings.monthly_quota_chars,
    }


def _voices_for(engine_name: str) -> list[dict]:
    """Voix d'un moteur, avec cache TTL pour les moteurs cloud uniquement."""
    engine = engines.get_engine(engine_name)  # lève TTSError si inconnu
    if engine.is_local:
        return [v.as_dict() for v in engine.list_voices()]
    now = time.time()
    cached = _voices_cache.get(engine_name)
    if cached and now - cached[0] < VOICES_CACHE_TTL:
        return cached[1]
    voices = [v.as_dict() for v in engine.list_voices()]
    _voices_cache[engine_name] = (now, voices)
    return voices


@app.get("/api/voices")
def get_voices(engine: str = "") -> dict:
    engine = engine or _resolved_default_engine()
    if engine not in engines.engine_names():
        raise HTTPException(status_code=400, detail=f"Moteur inconnu : '{engine}'.")
    try:
        return {"voices": _voices_for(engine)}
    except TTSError:
        # Service cloud injoignable / clé absente : échec non mis en cache.
        return {"voices": []}


def _voice_label(engine_name: str, voice_id: str) -> str:
    if not voice_id:
        return ""
    try:
        for voice in _voices_for(engine_name):
            if voice["voice_id"] == voice_id:
                return voice["name"]
    except TTSError:
        pass
    return voice_id


@app.post("/api/books", status_code=201)
async def create_book(
    file: UploadFile = File(...),
    language: str = Form("fr"),
    voice_id: str = Form(""),
    engine: str = Form(""),
) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ACCEPTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF et EPUB sont acceptés.")
    if engine and engine not in engines.engine_names():
        raise HTTPException(status_code=400, detail=f"Moteur inconnu : '{engine}'.")

    source_type = suffix[1:]
    engine_name = engine or _resolved_default_engine()
    job_id = jobs.create_job(
        title=Path(file.filename).stem,
        language=language,
        voice_id=voice_id,
        engine=engine,
        voice_label=_voice_label(engine_name, voice_id),
        source_type=source_type,
    )
    source_path = jobs.source_path(job_id, source_type)

    max_bytes = settings.max_upload_mb * 1024 * 1024
    size = 0
    with source_path.open("wb") as f:
        while chunk := await file.read(CHUNK_SIZE):
            size += len(chunk)
            if size > max_bytes:
                source_path.unlink(missing_ok=True)
                jobs.delete_job(job_id)
                raise HTTPException(
                    status_code=413,
                    detail=f"Fichier trop volumineux (max {settings.max_upload_mb} Mo).",
                )
            f.write(chunk)

    jobs.enqueue(job_id, "extract")
    return {"id": job_id}


@app.get("/api/books")
def list_books() -> list[dict]:
    books = jobs.list_jobs()
    for book in books:
        # Sur l'existence du fichier, pas sur le statut : pendant une reconversion,
        # la version précédente reste écoutable jusqu'à son remplacement atomique.
        book["has_m4b"] = jobs.m4b_path(book["id"]).exists()
        book["has_cover"] = covers.cover_path(book["id"]).exists()
    return books


@app.post("/api/books/{job_id}/convert")
def convert_book(job_id: str) -> dict:
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Livre introuvable.")
    if job["status"] not in ("extracted", "error"):
        raise HTTPException(
            status_code=409,
            detail=f"Conversion impossible depuis le statut '{job['status']}'.",
        )
    if not jobs.text_path(job_id).exists():
        raise HTTPException(
            status_code=409,
            detail="Texte extrait absent, veuillez ré-uploader le fichier.",
        )
    engine_name = job["engine"] or _resolved_default_engine()
    if engine_name == "edge":
        raise HTTPException(
            status_code=409,
            detail="Le moteur edge-tts a été retiré : supprimez ce livre et ré-uploadez-le "
            "(l'audio déjà généré reste lisible).",
        )
    if engine_name not in engines.engine_names():
        raise HTTPException(status_code=409, detail=f"Moteur inconnu : '{engine_name}'.")
    available, reason = engines.get_engine(engine_name).availability()
    if not available:
        raise HTTPException(status_code=409, detail=f"Moteur {engine_name} indisponible : {reason}")
    # Statut posé AVANT l'enqueue : un second clic est refusé (409) pendant
    # que le job attend dans la file — sinon il serait converti deux fois.
    # "queued" tant que le worker n'a pas commencé, "converting" ensuite.
    jobs.clear_cancel(job_id)
    jobs.update_job(job_id, status="queued", error=None)
    jobs.enqueue(job_id, "convert")
    return {"id": job_id, "status": "queued"}


@app.post("/api/books/{job_id}/cancel")
def cancel_book(job_id: str) -> dict:
    """Annule une conversion en attente ou en cours. Les segments déjà générés
    sont conservés : un futur « Convertir » reprendra au même endroit."""
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Livre introuvable.")
    if job["status"] not in ("queued", "converting"):
        raise HTTPException(
            status_code=409,
            detail=f"Rien à annuler depuis le statut '{job['status']}'.",
        )
    jobs.request_cancel(job_id)
    if job["status"] == "queued":
        # Pas encore commencé : effet immédiat.
        jobs.update_job(job_id, status="extracted", error=None)
        return {"id": job_id, "status": "extracted"}
    # En cours : le worker s'arrête à la fin du segment en train d'être synthétisé.
    return {"id": job_id, "status": "cancelling"}


@app.get("/api/books/{job_id}/chunks/{index}")
def get_chunk(job_id: str, index: int) -> FileResponse:
    """Segment audio brut pendant la génération (pré-écoute en direct).

    Les segments sont écrits atomiquement : un fichier présent est complet."""
    if jobs.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Livre introuvable.")
    directory = jobs.chunk_dir(job_id)
    for ext, media in (("wav", "audio/wav"), ("mp3", "audio/mpeg")):
        path = directory / f"chunk_{index:04d}.{ext}"
        if path.exists() and path.stat().st_size > 0:
            return FileResponse(path, media_type=media)
    raise HTTPException(status_code=404, detail="Segment pas encore généré.")


class ReconvertRequest(BaseModel):
    engine: str = ""
    voice_id: str = ""


@app.post("/api/books/{job_id}/reconvert")
def reconvert_book(job_id: str, body: ReconvertRequest) -> dict:
    """Re-synthétise un livre avec un autre moteur/voix (le texte extrait est réutilisé).

    L'audio actuel reste écoutable pendant la régénération : il n'est remplacé
    qu'à la fin de l'assemblage."""
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Livre introuvable.")
    if job["status"] in ("extracting", "queued", "converting"):
        raise HTTPException(
            status_code=409,
            detail=f"Reconversion impossible depuis le statut '{job['status']}'.",
        )
    if not jobs.text_path(job_id).exists():
        raise HTTPException(status_code=409, detail="Texte extrait absent, ré-uploadez le fichier.")

    engine_name = body.engine or job["engine"] or _resolved_default_engine()
    if engine_name not in engines.engine_names():
        raise HTTPException(status_code=400, detail=f"Moteur inconnu : '{engine_name}'.")
    available, reason = engines.get_engine(engine_name).availability()
    if not available:
        raise HTTPException(status_code=409, detail=f"Moteur {engine_name} indisponible : {reason}")

    voice_id = body.voice_id  # vide = voix par défaut du moteur au moment de la synthèse
    jobs.clear_cancel(job_id)
    jobs.update_job(
        job_id,
        engine=engine_name,
        voice_id=voice_id,
        voice_label=_voice_label(engine_name, voice_id),
        status="queued",
        error=None,
        done_chunks=0,
        total_chunks=0,
    )
    jobs.enqueue(job_id, "convert")
    return {"id": job_id, "status": "queued"}


@app.get("/api/books/{job_id}/audio")
def get_audio(job_id: str) -> FileResponse:
    job = jobs.get_job(job_id)
    audio = jobs.audio_path(job_id)
    if job is None or not audio.exists():
        raise HTTPException(status_code=404, detail="Audio introuvable.")
    return FileResponse(audio, media_type="audio/mpeg")


@app.get("/api/books/{job_id}/audio.m4b")
def get_audio_m4b(job_id: str) -> FileResponse:
    job = jobs.get_job(job_id)
    m4b = jobs.m4b_path(job_id)
    if job is None or not m4b.exists():
        raise HTTPException(status_code=404, detail="M4B introuvable.")
    return FileResponse(m4b, media_type="audio/mp4", filename=f"{job['title']}.m4b")


# Cache des chapitres lus depuis le M4B, invalidé par mtime (reconversion possible).
_chapters_cache: dict[str, tuple[float, list[dict]]] = {}


@app.get("/api/books/{job_id}/chapters")
def get_chapters(job_id: str) -> dict:
    """Chapitres {title, start, end} du livre, lus depuis les métadonnées du M4B."""
    m4b = jobs.m4b_path(job_id)
    if jobs.get_job(job_id) is None or not m4b.exists():
        return {"chapters": []}
    mtime = m4b.stat().st_mtime
    cached = _chapters_cache.get(job_id)
    if cached is None or cached[0] != mtime:
        try:
            _chapters_cache[job_id] = (mtime, audio.probe_chapters(m4b))
        except audio.AudioError:
            return {"chapters": []}
    return {"chapters": _chapters_cache[job_id][1]}


@app.get("/api/books/{job_id}/cover")
def get_cover(job_id: str) -> FileResponse:
    path = covers.cover_path(job_id)
    if jobs.get_job(job_id) is None or not path.exists():
        raise HTTPException(status_code=404, detail="Pas de couverture.")
    return FileResponse(path, media_type="image/jpeg")


class PositionRequest(BaseModel):
    seconds: float


@app.put("/api/books/{job_id}/position", status_code=204)
def set_position(job_id: str, body: PositionRequest) -> None:
    """Position de lecture partagée entre appareils (source de vérité serveur)."""
    if jobs.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Livre introuvable.")
    jobs.update_job(
        job_id,
        position_seconds=max(0.0, float(body.seconds)),
        last_played_at=datetime.now(timezone.utc).isoformat(),
    )


@app.delete("/api/books/{job_id}", status_code=204)
def delete_book(job_id: str) -> None:
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Livre introuvable.")
    if job["status"] == "converting":
        raise HTTPException(
            status_code=409,
            detail="Conversion en cours : attendez la fin ou le prochain statut d'erreur.",
        )
    jobs.delete_job(job_id)
    _chapters_cache.pop(job_id, None)


# ---------------------------------------------------------- banc d'essai voix

class PreviewRequest(BaseModel):
    engine: str
    language: str = "fr"
    voice_id: str = ""
    all: bool = False


class DefaultsRequest(BaseModel):
    engine: str
    voice_id: str = ""


def _check_engine(name: str) -> None:
    if name not in engines.engine_names():
        raise HTTPException(status_code=400, detail=f"Moteur inconnu : '{name}'.")


@app.get("/api/previews")
def get_previews(engine: str, language: str = "fr") -> dict:
    _check_engine(engine)
    language = language if language in previews.SAMPLE_TEXTS else "fr"
    return {
        "voices": previews.list_previews(engine, language),
        "sample_text": previews.SAMPLE_TEXTS[language],
    }


@app.post("/api/previews", status_code=202)
def request_previews(body: PreviewRequest) -> dict:
    _check_engine(body.engine)
    language = body.language if body.language in previews.SAMPLE_TEXTS else "fr"
    available, reason = engines.get_engine(body.engine).availability()
    if not available:
        raise HTTPException(status_code=409, detail=f"Moteur {body.engine} indisponible : {reason}")
    if body.all:
        targets = [
            row["voice_id"]
            for row in previews.list_previews(body.engine, language)
            if row["status"] in ("missing", "error")
        ]
    elif body.voice_id:
        targets = [body.voice_id]
    else:
        raise HTTPException(status_code=400, detail="voice_id requis (ou all=true).")
    for voice_id in targets:
        jobs.enqueue_preview(body.engine, voice_id, language)
    return {"queued": len(targets)}


@app.get("/api/previews/audio")
def get_preview_audio(engine: str, voice_id: str, language: str = "fr") -> FileResponse:
    _check_engine(engine)
    path = previews.preview_path(engine, voice_id, language)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Extrait non généré.")
    media = "audio/wav" if path.suffix == ".wav" else "audio/mpeg"
    return FileResponse(path, media_type=media)


@app.put("/api/settings")
def put_settings(body: DefaultsRequest) -> dict:
    _check_engine(body.engine)
    set_setting("default_engine", body.engine)
    if body.voice_id:
        set_setting(f"default_voice:{body.engine}", body.voice_id)
    return get_config()


# L'UI statique est montée en dernier pour ne pas masquer les routes /api.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
