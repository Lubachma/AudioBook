"""Client minimal pour l'API ElevenLabs (text-to-speech), avec retries.

On utilise l'API HTTP directement (plutôt que le SDK) pour garder une
dépendance légère et facilement mockable en tests.
"""

import time
from pathlib import Path

import httpx

API_BASE = "https://api.elevenlabs.io/v1/text-to-speech"
VOICES_URL = "https://api.elevenlabs.io/v1/voices"
DEFAULT_TIMEOUT = 120.0


class TTSError(Exception):
    """Erreur générique de synthèse vocale."""


class QuotaExceededError(TTSError):
    """Quota mensuel ElevenLabs atteint."""


class AuthError(TTSError):
    """Clé API absente ou invalide."""


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


def list_voices(
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


def _raise_for_status(status: int, body: str) -> None:
    if status == 429 or "quota" in body.lower():
        raise QuotaExceededError(
            "Quota ElevenLabs atteint : attendez le mois prochain ou passez à un plan supérieur."
        )
    if status in (401, 403):
        raise AuthError(f"Clé API ElevenLabs refusée (HTTP {status}). Vérifiez ELEVENLABS_API_KEY.")
    raise TTSError(f"ElevenLabs HTTP {status} : {body}")


def synthesize_with_retry(
    *args,
    attempts: int = 3,
    base_delay: float = 2.0,
    **kwargs,
) -> Path:
    """Retry avec backoff exponentiel sur les erreurs réseau/serveur.

    Les erreurs de quota et d'authentification ne sont jamais retentées.
    """
    for attempt in range(attempts):
        try:
            return synthesize_chunk(*args, **kwargs)
        except (QuotaExceededError, AuthError):
            raise
        except (TTSError, httpx.HTTPError):
            if attempt == attempts - 1:
                raise
            time.sleep(base_delay * 2**attempt)
    raise TTSError("Échec de synthèse après plusieurs tentatives.")  # pragma: no cover
