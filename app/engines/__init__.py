"""Registre des moteurs TTS.

Garantit qu'un seul modèle local est chargé en mémoire à la fois (32 Go partagés) :
`activate(name)` décharge les autres moteurs locaux avant de charger le demandé.
Le worker de jobs étant strictement séquentiel, aucun verrou n'est nécessaire.
"""

from __future__ import annotations

from .base import AuthError, Engine, QuotaExceededError, TTSError, Voice
from .elevenlabs import ElevenLabsEngine
from .kyutai import KyutaiEngine
from .qwen3 import Qwen3Engine

__all__ = [
    "AuthError",
    "Engine",
    "QuotaExceededError",
    "TTSError",
    "Voice",
    "activate",
    "describe",
    "engine_names",
    "get_engine",
    "unload_all",
]

# Ordre = ordre d'affichage dans l'UI.
_CLASSES: dict[str, type[Engine]] = {
    cls.name: cls for cls in (Qwen3Engine, KyutaiEngine, ElevenLabsEngine)
}
_instances: dict[str, Engine] = {}


def engine_names() -> list[str]:
    return list(_CLASSES)


def get_engine(name: str) -> Engine:
    if name not in _CLASSES:
        raise TTSError(f"Moteur inconnu : '{name}'.")
    if name not in _instances:
        _instances[name] = _CLASSES[name]()
    return _instances[name]


def activate(name: str) -> Engine:
    """Prépare `name` à synthétiser : décharge les autres moteurs locaux puis charge celui-ci."""
    engine = get_engine(name)
    for other_name, other in _instances.items():
        if other.is_local and other_name != name:
            other.unload()
    engine.load()
    return engine


def unload_all() -> None:
    """Libère toute la RAM des modèles (appelé quand la file de jobs est au repos)."""
    for engine in _instances.values():
        engine.unload()


def describe() -> list[dict]:
    """Métadonnées des moteurs pour /api/config."""
    result = []
    for name in _CLASSES:
        engine = get_engine(name)
        available, reason = engine.availability()
        result.append(
            {
                "name": name,
                "label": engine.label,
                "available": available,
                "reason": reason,
                "is_local": engine.is_local,
            }
        )
    return result
