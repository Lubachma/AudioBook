"""Interface commune des moteurs TTS.

Chaque moteur déclare sa taille de chunk optimale et son format de sortie ;
la classe de base fournit l'écriture atomique (un chunk présent sur disque est
garanti complet — c'est le socle de la reprise sans re-synthèse) et le retry.
"""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar


class TTSError(Exception):
    """Erreur générique de synthèse vocale."""


class QuotaExceededError(TTSError):
    """Quota mensuel du service cloud atteint — jamais retenté."""


class AuthError(TTSError):
    """Clé API absente ou invalide — jamais retenté."""


@dataclass(frozen=True)
class Voice:
    voice_id: str
    name: str
    category: str = ""
    language: str = ""  # "fr", "en" ou "" (voix multilingue)

    def as_dict(self) -> dict:
        return {
            "voice_id": self.voice_id,
            "name": self.name,
            "category": self.category,
            "language": self.language,
        }


class Engine(ABC):
    """Un moteur de synthèse. Les instances sont des singletons gérés par le registre."""

    name: ClassVar[str]
    label: ClassVar[str]
    chunk_max_chars: int = 1500
    chunk_ext: ClassVar[str] = "wav"  # "wav" (local) | "mp3" (cloud)
    is_local: ClassVar[bool] = False

    def availability(self) -> tuple[bool, str]:
        """(disponible, raison si indisponible) — ne doit JAMAIS charger de modèle."""
        return True, ""

    @abstractmethod
    def list_voices(self) -> list[Voice]:
        """Voix proposées — ne doit jamais charger de modèle."""

    def default_voice(self) -> str:
        voices = self.list_voices()
        return voices[0].voice_id if voices else ""

    def load(self) -> None:  # noqa: B027 - hook optionnel
        """Charge le modèle en mémoire (no-op pour les moteurs cloud)."""

    def unload(self) -> None:  # noqa: B027 - hook optionnel
        """Libère le modèle (RAM) — appelé quand un autre moteur local prend la main."""

    @abstractmethod
    def _synthesize(self, text: str, out_path: Path, *, voice_id: str, language: str) -> None:
        """Écrit l'audio du texte dans out_path (extension = chunk_ext)."""

    def synthesize(self, text: str, out_path: str | Path, *, voice_id: str, language: str) -> Path:
        """Synthèse avec écriture atomique : le fichier final n'apparaît que complet."""
        out_path = Path(out_path)
        tmp = out_path.with_name(out_path.name + ".part")
        try:
            self._synthesize(text, tmp, voice_id=voice_id, language=language)
            if not tmp.exists() or tmp.stat().st_size == 0:
                raise TTSError(f"Moteur {self.name} : aucun audio produit.")
            os.replace(tmp, out_path)
        finally:
            tmp.unlink(missing_ok=True)
        return out_path

    def synthesize_with_retry(
        self,
        text: str,
        out_path: str | Path,
        *,
        voice_id: str,
        language: str,
        attempts: int = 3,
        base_delay: float = 2.0,
    ) -> Path:
        """Retry avec backoff exponentiel ; quota et authentification ne sont jamais retentés."""
        for attempt in range(attempts):
            try:
                return self.synthesize(text, out_path, voice_id=voice_id, language=language)
            except (QuotaExceededError, AuthError):
                raise
            except Exception:  # noqa: BLE001 - transitoire possible (réseau, GPU)
                if attempt == attempts - 1:
                    raise
                time.sleep(base_delay * 2**attempt)
        raise TTSError("Échec de synthèse après plusieurs tentatives.")  # pragma: no cover
