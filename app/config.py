"""Configuration de l'application, chargée depuis les variables d'environnement (.env).

Les préférences modifiables depuis l'UI (moteur/voix par défaut) vivent en base :
voir settings_store.py — elles priment sur les valeurs ci-dessous.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv est optionnel
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


class Settings:
    """Instance mutable pour permettre aux tests de surcharger les valeurs."""

    def __init__(self) -> None:
        self.repo_root = REPO_ROOT
        # Chemin absolu par défaut (indépendant du CWD : indispensable sous launchd).
        self.data_dir = Path(os.environ.get("DATA_DIR") or REPO_ROOT / "data").resolve()

        # Général
        self.default_language = os.environ.get("DEFAULT_LANGUAGE", "fr")
        self.default_engine = os.environ.get("DEFAULT_ENGINE", "qwen3")
        self.max_upload_mb = _int("MAX_UPLOAD_MB", 100)
        self.min_free_disk_mb = _int("MIN_FREE_DISK_MB", 500)

        # Sortie audio
        self.mp3_bitrate = os.environ.get("MP3_BITRATE", "96k")
        self.m4b_bitrate = os.environ.get("M4B_BITRATE", "64k")
        # Normalisation du volume à l'assemblage (filtre ffmpeg loudnorm) ; vide = désactivée.
        self.loudnorm = os.environ.get("LOUDNORM", "I=-18:TP=-2:LRA=11")
        # Pause insérée entre deux chapitres (moteurs locaux), en millisecondes.
        self.chapter_pause_ms = _int("CHAPTER_PAUSE_MS", 700)

        # Contrôle qualité des chunks locaux : transcription whisper vs texte source.
        self.qc_enabled = os.environ.get("QC_ENABLED", "1").lower() not in ("0", "false", "")
        self.qc_min_ratio = _float("QC_MIN_RATIO", 0.70)
        self.qc_whisper_model = os.environ.get("QC_WHISPER_MODEL", "mlx-community/whisper-small-mlx")

        # Moteur local qwen3 (mlx-audio)
        self.qwen3_base_model = os.environ.get(
            "QWEN3_BASE_MODEL", "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16"
        )
        self.qwen3_custom_model = os.environ.get(
            "QWEN3_CUSTOM_MODEL", "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-bf16"
        )
        self.qwen3_voice_design_model = os.environ.get(
            "QWEN3_VOICE_DESIGN_MODEL", "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16"
        )
        self.qwen3_temperature = _float("QWEN3_TEMPERATURE", 0.7)

        # Moteur local kyutai (moshi-mlx, dans son venv isolé — voir engines/kyutai.py)
        self.kyutai_repo = os.environ.get("KYUTAI_REPO", "kyutai/tts-1.6b-en_fr")
        self.kyutai_voice_repo = os.environ.get("KYUTAI_VOICE_REPO", "kyutai/tts-voices")
        self.kyutai_python = Path(
            os.environ.get("KYUTAI_PYTHON") or REPO_ROOT / ".venv-kyutai" / "bin" / "python"
        )
        self.kyutai_worker_script = REPO_ROOT / "scripts" / "kyutai_worker.py"
        self.kyutai_temp = _float("KYUTAI_TEMP", 0.6)
        self.kyutai_cfg_coef = _float("KYUTAI_CFG_COEF", 2.0)
        self.kyutai_load_timeout = _float("KYUTAI_LOAD_TIMEOUT", 1800.0)  # 1er run : téléchargement
        self.kyutai_synth_timeout = _float("KYUTAI_SYNTH_TIMEOUT", 900.0)

        # ElevenLabs (optionnel)
        self.elevenlabs_api_key = os.environ.get("ELEVENLABS_API_KEY", "")
        self.elevenlabs_voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
        self.elevenlabs_model_id = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
        self.chunk_max_chars = _int("CHUNK_MAX_CHARS", 4000)  # limite API ElevenLabs uniquement
        self.voice_stability = _float("VOICE_STABILITY", 0.5)
        self.voice_similarity_boost = _float("VOICE_SIMILARITY_BOOST", 0.75)
        self.monthly_quota_chars = _int("MONTHLY_QUOTA_CHARS", 100_000)

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
    def voices_dir(self) -> Path:
        return self.data_dir / "voices"

    @property
    def previews_dir(self) -> Path:
        return self.data_dir / "previews"

    @property
    def covers_dir(self) -> Path:
        return self.data_dir / "covers"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jobs.db"

    def ensure_dirs(self) -> None:
        for d in (
            self.data_dir,
            self.uploads_dir,
            self.audio_dir,
            self.text_dir,
            self.voices_dir,
            self.previews_dir,
            self.covers_dir,
            self.logs_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
