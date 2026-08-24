"""Moteur ElevenLabs (cloud, payant) — API HTTP directe via httpx.

On évite le SDK pour garder une dépendance légère et facilement mockable :
les fonctions bas-niveau acceptent un `transport` httpx injectable en tests.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from ..config import settings
from .base import AuthError, Engine, QuotaExceededError, TTSError, Voice

API_BASE = "https://api.elevenlabs.io/v1/text-to-speech"
VOICES_URL = "https://api.elevenlabs.io/v1/voices"
DEFAULT_TIMEOUT = 120.0


def _raise_for_status(status: int, body: str) -> None:
    if status == 429 or "quota" in body.lower():
        raise QuotaExceededError(
            "Quota ElevenLabs atteint : attendez le mois prochain ou passez à un plan supérieur."
        )
    if status in (401, 403):
        raise AuthError(f"Clé API ElevenLabs refusée (HTTP {status}). Vérifiez ELEVENLABS_API_KEY.")
    raise TTSError(f"ElevenLabs HTTP {status} : {body}")


def synthesize_chunk(
    text: str,
    out_path: str | Path,
    *,
    api_key: str,
    voice_id: str,
    model_id: str,
    language_code: str | None = None,
    stability: float = 0.5,
    similarity_boost: float = 0.75,
    timeout: float = DEFAULT_TIMEOUT,
    transport: httpx.BaseTransport | None = None,
) -> Path:
    """Synthétise un chunk de texte en MP3. Lève QuotaExceededError/AuthError/TTSError."""
    if not api_key:
        raise AuthError("ELEVENLABS_API_KEY n'est pas configurée.")

    payload: dict = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
        },
    }
    if language_code:
        payload["language_code"] = language_code

    with httpx.Client(timeout=timeout, transport=transport) as client:
        with client.stream(
            "POST",
            f"{API_BASE}/{voice_id}",
            params={"output_format": "mp3_44100_128"},
            json=payload,
            headers={"xi-api-key": api_key},
        ) as response:
            if response.status_code != 200:
                body = response.read().decode("utf-8", "replace")[:500]
                _raise_for_status(response.status_code, body)
            out_path = Path(out_path)
            with out_path.open("wb") as f:
                for data in response.iter_bytes():
                    f.write(data)
    return out_path


def fetch_account_voices(
    api_key: str,
    timeout: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> list[dict]:
    """Liste les voix du compte ElevenLabs (prédéfinies + clonées), format simplifié."""
    if not api_key:
        raise AuthError("ELEVENLABS_API_KEY n'est pas configurée.")
    with httpx.Client(timeout=timeout, transport=transport) as client:
        response = client.get(VOICES_URL, headers={"xi-api-key": api_key})
    if response.status_code != 200:
        _raise_for_status(response.status_code, response.text[:500])
    return [
        {
            "voice_id": v["voice_id"],
            "name": v["name"],
            "category": v.get("category", ""),
        }
        for v in response.json().get("voices", [])
    ]


class ElevenLabsEngine(Engine):
    name = "elevenlabs"
    label = "ElevenLabs (cloud, quota payant)"
    chunk_ext = "mp3"
    is_local = False

    # Transport httpx injectable pour les tests (classe entière, mono-utilisateur).
    transport: httpx.BaseTransport | None = None

    @property
    def chunk_max_chars(self) -> int:  # type: ignore[override]
        return settings.chunk_max_chars

    def availability(self) -> tuple[bool, str]:
        if not settings.elevenlabs_api_key:
            return False, "Clé API ElevenLabs non configurée (.env)."
        return True, ""

    def list_voices(self) -> list[Voice]:
        rows = fetch_account_voices(settings.elevenlabs_api_key, transport=self.transport)
        return [Voice(r["voice_id"], r["name"], r.get("category", "")) for r in rows]

    def default_voice(self) -> str:
        return settings.elevenlabs_voice_id

    def _synthesize(self, text: str, out_path: Path, *, voice_id: str, language: str) -> None:
        synthesize_chunk(
            text,
            out_path,
            api_key=settings.elevenlabs_api_key,
            voice_id=voice_id or settings.elevenlabs_voice_id,
            model_id=settings.elevenlabs_model_id,
            language_code=language or None,
            stability=settings.voice_stability,
            similarity_boost=settings.voice_similarity_boost,
            transport=self.transport,
        )
