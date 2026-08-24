"""Banc d'essai des voix : un même extrait témoin synthétisé par chaque voix candidate.

Les extraits sont générés par la même file que les conversions (accès sérialisé aux
modèles) et mis en cache dans data/previews/. L'état « pending/error » est en mémoire
(mono-utilisateur) ; un fichier présent = extrait prêt.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import engines
from .config import settings

# ~350 caractères : narration + dialogue + question + nombre, pour juger la
# prosodie, les liaisons et la lecture des chiffres.
SAMPLE_TEXTS = {
    "fr": (
        "Le soir tombait sur la vieille ville, et les lampadaires s'allumaient un à un "
        "le long du quai. « Tu es en retard », murmura Claire sans se retourner. "
        "Il posa les deux tasses sur la table, sourit, et répondit qu'il avait compté "
        "trente-sept marches pour monter jusqu'ici. Était-ce vraiment une excuse ? "
        "Dehors, la pluie commençait à tambouriner contre les vitres."
    ),
    "en": (
        "Evening settled over the old town as the streetlamps flickered on, one by one, "
        "along the quay. “You're late,” Claire murmured without turning around. "
        "He set the two cups on the table, smiled, and said he had counted thirty-seven "
        "steps on his way up. Was that really an excuse? Outside, the rain began to drum "
        "against the windows."
    ),
}

# clé -> "pending" | "error:<message>"
_state: dict[str, str] = {}


def _sanitize(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def preview_key(engine_name: str, voice_id: str, language: str) -> str:
    return f"{_sanitize(engine_name)}__{_sanitize(voice_id)}__{_sanitize(language)}"


def preview_path(engine_name: str, voice_id: str, language: str) -> Path:
    ext = engines.get_engine(engine_name).chunk_ext
    return settings.previews_dir / f"{preview_key(engine_name, voice_id, language)}.{ext}"


def list_previews(engine_name: str, language: str) -> list[dict]:
    """État du banc d'essai pour un moteur et une langue donnés."""
    engine = engines.get_engine(engine_name)
    default_voice = None
    rows = []
    for voice in engine.list_voices():
        if voice.language and voice.language != language:
            continue
        key = preview_key(engine_name, voice.voice_id, language)
        path = preview_path(engine_name, voice.voice_id, language)
        state = _state.get(key, "")
        if path.exists() and path.stat().st_size > 0:
            status = "ready"
        elif state == "pending":
            status = "pending"
        elif state.startswith("error:"):
            status = "error"
        else:
            status = "missing"
        rows.append(
            {
                "voice_id": voice.voice_id,
                "name": voice.name,
                "category": voice.category,
                "language": voice.language,
                "status": status,
                "error": state[len("error:"):] if status == "error" else "",
            }
        )
        default_voice = default_voice or voice.voice_id
    return rows


def mark_pending(engine_name: str, voice_id: str, language: str) -> None:
    _state[preview_key(engine_name, voice_id, language)] = "pending"


def mark_error(item: dict, message: str) -> None:
    key = preview_key(item["engine"], item["voice_id"], item["language"])
    _state[key] = f"error:{message[:300]}"


def run_preview(item: dict) -> None:
    """Exécuté par le worker de jobs (accès exclusif aux modèles)."""
    engine_name, voice_id, language = item["engine"], item["voice_id"], item["language"]
    key = preview_key(engine_name, voice_id, language)
    path = preview_path(engine_name, voice_id, language)
    if path.exists() and path.stat().st_size > 0:
        _state.pop(key, None)
        return
    text = SAMPLE_TEXTS.get(language, SAMPLE_TEXTS["fr"])
    engine = engines.activate(engine_name)
    settings.previews_dir.mkdir(parents=True, exist_ok=True)
    engine.synthesize(text, path, voice_id=voice_id, language=language)
    _state.pop(key, None)
