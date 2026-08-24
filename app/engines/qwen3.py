"""Moteur local Qwen3-TTS-12Hz-1.7B via mlx-audio (MLX, Apple Silicon).

Deux modes selon le préfixe du voice_id :
  ref:<nom>     clonage zéro-shot (modèle Base) depuis data/voices/<nom>.wav
                accompagné de son transcript exact data/voices/<nom>.txt —
                c'est la voie des « narratrices françaises » créées par
                scripts/design_voices.py (les speakers préréglés n'ont pas de fr natif) ;
  spk:<Nom>     speaker préréglé du modèle CustomVoice (anglophones : Ryan, Aiden).

Les imports mlx sont paresseux : l'app démarre et se teste sans l'extra `local`.
Un seul checkpoint (Base OU CustomVoice) est gardé en mémoire à la fois.
"""

from __future__ import annotations

import gc
import importlib.util
from pathlib import Path

import numpy as np

from ..audio import write_wav_int16
from ..config import settings
from .base import Engine, TTSError, Voice

_LANG_CODES = {"fr": "french", "en": "english"}


class Qwen3Engine(Engine):
    name = "qwen3"
    label = "Qwen3-TTS (local, gratuit)"
    chunk_max_chars = 1500
    chunk_ext = "wav"
    is_local = True

    # Les 9 speakers CustomVoice sont zh/en/ja/ko : seuls les anglophones sont proposés.
    PRESET_SPEAKERS = (
        ("spk:Ryan", "Ryan (en, M)"),
        ("spk:Aiden", "Aiden (en, M)"),
    )

    def __init__(self) -> None:
        self._model = None
        self._model_kind: str | None = None  # "base" | "custom"
        # Loader injectable en tests ; None => mlx_audio.tts.utils.load_model
        self._load_model = None

    # ------------------------------------------------------------- découverte

    def availability(self) -> tuple[bool, str]:
        if importlib.util.find_spec("mlx_audio") is None:
            return False, "mlx-audio non installé — lancez : uv sync --extra local"
        return True, ""

    def list_voices(self) -> list[Voice]:
        voices: list[Voice] = []
        if settings.voices_dir.is_dir():
            for wav in sorted(settings.voices_dir.glob("*.wav")):
                if wav.with_suffix(".txt").exists():
                    label = wav.stem.replace("_", " ").replace("-", " ").capitalize()
                    voices.append(Voice(f"ref:{wav.stem}", f"{label} (voix designée)", "designed", "fr"))
        voices.extend(Voice(vid, name, "preset", "en") for vid, name in self.PRESET_SPEAKERS)
        return voices

    def default_voice(self) -> str:
        voices = self.list_voices()
        return voices[0].voice_id if voices else "spk:Ryan"

    # ------------------------------------------------------------- modèle MLX

    def unload(self) -> None:
        if self._model is None:
            return
        self._model = None
        self._model_kind = None
        gc.collect()
        try:  # pragma: no cover - dépend de la présence de mlx
            import mlx.core as mx

            mx.clear_cache()
        except Exception:  # noqa: BLE001
            pass

    def _ensure_model(self, kind: str):
        if self._model is not None and self._model_kind == kind:
            return self._model
        self.unload()
        loader = self._load_model
        if loader is None:  # pragma: no cover - exercé par le smoke test réel
            from mlx_audio.tts.utils import load_model as loader
        repo = settings.qwen3_base_model if kind == "base" else settings.qwen3_custom_model
        self._model = loader(repo)
        self._model_kind = kind
        return self._model

    # ---------------------------------------------------------------- synthèse

    def _synthesize(self, text: str, out_path: Path, *, voice_id: str, language: str) -> None:
        lang = _LANG_CODES.get(language, "auto")
        if voice_id.startswith("ref:"):
            stem = voice_id[len("ref:"):]
            ref_wav = settings.voices_dir / f"{stem}.wav"
            ref_txt = ref_wav.with_suffix(".txt")
            if not (ref_wav.exists() and ref_txt.exists()):
                raise TTSError(
                    f"Voix de référence '{stem}' introuvable dans {settings.voices_dir} "
                    "(il faut le .wav ET son transcript .txt — voir scripts/design_voices.py)."
                )
            model = self._ensure_model("base")
            results = model.generate(
                text=text,
                ref_audio=str(ref_wav),
                ref_text=ref_txt.read_text(encoding="utf-8").strip(),
                lang_code=lang,
                temperature=settings.qwen3_temperature,
            )
        elif voice_id.startswith("spk:"):
            model = self._ensure_model("custom")
            results = model.generate_custom_voice(
                text=text,
                speaker=voice_id[len("spk:"):],
                language=lang,
                temperature=settings.qwen3_temperature,
            )
        else:
            raise TTSError(f"Voix qwen3 invalide : '{voice_id}' (attendu 'ref:…' ou 'spk:…').")

        sample_rate = 24_000
        parts: list[np.ndarray] = []
        for result in results:
            parts.append(np.asarray(result.audio, dtype=np.float32).reshape(-1))
            sample_rate = getattr(result, "sample_rate", sample_rate)
        if not parts:
            raise TTSError("qwen3 : aucun audio généré.")
        write_wav_int16(out_path, np.concatenate(parts), sample_rate)
