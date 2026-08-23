"""Client minimal pour l'API ElevenLabs (text-to-speech), avec retries,
et moteur alternatif edge-tts (voix neurales Microsoft, gratuit).

On utilise l'API HTTP directement pour ElevenLabs (plutôt que le SDK)
pour garder une dépendance légère et facilement mockable en tests.
"""

import asyncio
import time
from pathlib import Path

import edge_tts
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
            try:
                with out_path.open("wb") as f:
                    for data in response.iter_bytes():
                        f.write(data)
            except Exception:
                # Pas de fichier partiel : sinon la reprise le croirait complet
                # et ffmpeg assemblerait un MP3 corrompu.
                out_path.unlink(missing_ok=True)
                raise
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


# ------------------------------------------------------------------ edge-tts

def synthesize_edge_chunk(text: str, out_path: str | Path, *, voice: str) -> Path:
    """Synthétise un chunk via edge-tts (voix neurales Microsoft, gratuit)."""
    out_path = Path(out_path)

    async def _run() -> None:
        await edge_tts.Communicate(text, voice).save(str(out_path))

    try:
        asyncio.run(_run())
    except Exception:
        # Pas de fichier partiel : sinon la reprise le croirait complet.
        out_path.unlink(missing_ok=True)
        raise
    return out_path


def synthesize_edge_with_retry(
    *args,
    attempts: int = 3,
    base_delay: float = 2.0,
    **kwargs,
) -> Path:
    """Retry avec backoff exponentiel ; edge-tts lève des exceptions génériques."""
    for attempt in range(attempts):
        try:
            return synthesize_edge_chunk(*args, **kwargs)
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(base_delay * 2**attempt)
    raise TTSError("Échec edge-tts après plusieurs tentatives.")  # pragma: no cover


def _edge_display_name(voice: dict) -> str:
    """'fr-FR-DeniseNeural' -> 'Denise (fr-FR, F)'."""
    short = voice["ShortName"]
    name = short.split("-")[-1].removesuffix("Neural")
    gender = {"Female": "F", "Male": "M"}.get(voice.get("Gender", ""), "")
    return f"{name} ({voice['Locale']}, {gender})" if gender else f"{name} ({voice['Locale']})"


def list_edge_voices(locales: tuple[str, ...] = ("fr", "en")) -> list[dict]:
    """Voix edge-tts filtrées par langue (fr/en par défaut), format simplifié."""
    all_voices = asyncio.run(edge_tts.list_voices())
    return [
        {"voice_id": v["ShortName"], "name": _edge_display_name(v), "category": "edge"}
        for v in all_voices
        if v["Locale"].split("-")[0] in locales
    ]
