"""Contrôle qualité des chunks TTS locaux : transcription (mlx-whisper) vs texte source.

Les TTS autorégressifs déraillent parfois sur un segment (phrase avalée, répétition).
Après chaque chunk local, on transcrit l'audio et on compare aux mots attendus :
un score trop bas déclenche une seconde prise (voir jobs._synthesize_with_qc).
Le modèle whisper est mis en cache par mlx-whisper entre les appels.
"""

from __future__ import annotations

import difflib
import importlib.util
import re
from pathlib import Path

from .config import settings

_WORD_RE = re.compile(r"[\w']+", re.UNICODE)


def available() -> bool:
    return importlib.util.find_spec("mlx_whisper") is not None


def _normalize(text: str) -> list[str]:
    """Liste de mots comparables : minuscules, sans ponctuation ni chiffres isolés.

    Les chiffres sont écartés des deux côtés : whisper écrit « 37 » là où le texte
    source dit « trente-sept » (et inversement), ce qui créerait de faux écarts.
    """
    words = _WORD_RE.findall(text.lower())
    return [w for w in words if not w.isdigit()]


def words_ratio(expected: str, transcript: str) -> float:
    """Similarité 0..1 entre les mots attendus et les mots transcrits."""
    a, b = _normalize(expected), _normalize(transcript)
    if not a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def match_ratio(audio_path: str | Path, expected_text: str, *, language: str = "fr") -> float:
    """Transcrit le chunk et retourne sa similarité avec le texte attendu."""
    import mlx_whisper

    result = mlx_whisper.transcribe(
        str(audio_path),
        path_or_hf_repo=settings.qc_whisper_model,
        language=language if language in ("fr", "en") else None,
        condition_on_previous_text=False,
    )
    return words_ratio(expected_text, result.get("text", ""))


def unload() -> None:
    """Libère le modèle whisper (appelé quand la file de jobs est au repos)."""
    try:  # pragma: no cover - dépend de la présence de mlx_whisper
        from mlx_whisper.transcribe import ModelHolder

        ModelHolder.model = None
        ModelHolder.model_path = None
        import mlx.core as mx

        mx.clear_cache()
    except Exception:  # noqa: BLE001
        pass
