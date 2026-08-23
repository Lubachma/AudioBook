"""Configuration de l'application, chargée depuis les variables d'environnement (.env)."""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv est optionnel
    pass


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


class Settings:
    """Instance mutable pour permettre aux tests de surcharger les valeurs."""

    def __init__(self) -> None:
        self.data_dir = Path(os.environ.get("DATA_DIR", "data")).resolve()
        self.elevenlabs_api_key = os.environ.get("ELEVENLABS_API_KEY", "")
        self.elevenlabs_voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
        self.elevenlabs_model_id = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
        self.default_language = os.environ.get("DEFAULT_LANGUAGE", "fr")
        self.default_engine = os.environ.get("DEFAULT_ENGINE", "edge")
        self.default_edge_voice = os.environ.get("DEFAULT_EDGE_VOICE", "fr-FR-DeniseNeural")
        self.chunk_max_chars = _int("CHUNK_MAX_CHARS", 4000)
        self.max_upload_mb = _int("MAX_UPLOAD_MB", 100)
        self.voice_stability = _float("VOICE_STABILITY", 0.5)
        self.voice_similarity_boost = _float("VOICE_SIMILARITY_BOOST", 0.75)
        self.monthly_quota_chars = _int("MONTHLY_QUOTA_CHARS", 100_000)
        self.min_free_disk_mb = _int("MIN_FREE_DISK_MB", 500)

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def text_dir(self) -> Path:
        return self.data_dir / "text"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jobs.db"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.uploads_dir, self.audio_dir, self.text_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
