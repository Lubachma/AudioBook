"""API FastAPI : upload de PDF, suivi des conversions, streaming audio, UI statique."""

import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import jobs
from .config import settings
from .tts import TTSError, list_edge_voices, list_voices

STATIC_DIR = Path(__file__).parent / "static"
CHUNK_SIZE = 1 << 20  # 1 Mo
VOICES_CACHE_TTL = 600  # secondes

# Cache en mémoire des listes de voix par moteur (évite un appel externe par chargement de page)
_voices_cache: dict[str, tuple[float, list[dict]]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    jobs.start_worker()
    yield


app = FastAPI(title="PDF → Livre audio", lifespan=lifespan)


@app.get("/api/config")
def get_config() -> dict:
    return {
        "voice_id": settings.elevenlabs_voice_id,
        "model_id": settings.elevenlabs_model_id,
        "default_language": settings.default_language,
        "monthly_quota_chars": settings.monthly_quota_chars,
        "api_key_configured": bool(settings.elevenlabs_api_key),
        "default_engine": settings.default_engine,
        "default_edge_voice": settings.default_edge_voice,
    }


@app.get("/api/voices")
def get_voices(engine: str = "elevenlabs") -> dict:
    """Voix du moteur demandé, avec cache par moteur.

    engine=edge        -> voix neurales Microsoft (gratuit), liste filtrée fr/en
    engine=elevenlabs  -> voix du compte ElevenLabs ; liste vide si clé absente ou API en échec
    """
    now = time.time()
    cached = _voices_cache.get(engine)
    if cached and now - cached[0] < VOICES_CACHE_TTL:
        return {"voices": cached[1]}

    if engine == "edge":
        try:
            voices = list_edge_voices()
        except Exception:  # noqa: BLE001 - service externe non critique
            voices = []
    else:
        if not settings.elevenlabs_api_key:
            return {"voices": []}
        try:
            voices = list_voices(settings.elevenlabs_api_key)
        except TTSError:
            return {"voices": []}

    _voices_cache[engine] = (now, voices)
    return {"voices": voices}


@app.post("/api/books", status_code=201)
async def create_book(
    file: UploadFile = File(...),
    language: str = Form("fr"),
    voice_id: str = Form(""),
    engine: str = Form(""),
) -> dict:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptés.")

    job_id = jobs.create_job(
        title=Path(file.filename).stem, language=language, voice_id=voice_id, engine=engine
    )
    pdf_path = jobs.pdf_path(job_id)

    max_bytes = settings.max_upload_mb * 1024 * 1024
    size = 0
    with pdf_path.open("wb") as f:
        while chunk := await file.read(CHUNK_SIZE):
            size += len(chunk)
            if size > max_bytes:
                pdf_path.unlink(missing_ok=True)
                jobs.delete_job(job_id)
                raise HTTPException(
                    status_code=413,
                    detail=f"PDF trop volumineux (max {settings.max_upload_mb} Mo).",
                )
            f.write(chunk)

    jobs.enqueue(job_id, "extract")
    return {"id": job_id}


@app.get("/api/books")
def list_books() -> list[dict]:
    return jobs.list_jobs()


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
            detail="Texte extrait absent, veuillez ré-uploader le PDF.",
        )
    jobs.enqueue(job_id, "convert")
    return {"id": job_id, "status": "converting"}


@app.get("/api/books/{job_id}/audio")
def get_audio(job_id: str) -> FileResponse:
    job = jobs.get_job(job_id)
    audio = jobs.audio_path(job_id)
    if job is None or job["status"] != "done" or not audio.exists():
        raise HTTPException(status_code=404, detail="Audio introuvable.")
    return FileResponse(audio, media_type="audio/mpeg")


@app.delete("/api/books/{job_id}", status_code=204)
def delete_book(job_id: str) -> None:
    if not jobs.delete_job(job_id):
        raise HTTPException(status_code=404, detail="Livre introuvable.")


# L'UI statique est montée en dernier pour ne pas masquer les routes /api.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
