"""Tests du moteur qwen3 (mlx-audio mocké : loader injecté, faux modèles)."""

import wave

import numpy as np
import pytest

from app.config import settings
from app.engines import TTSError
from app.engines.qwen3 import Qwen3Engine


class _Result:
    def __init__(self, n=2400, rate=24000):
        self.audio = np.full(n, 0.5, dtype=np.float32)
        self.sample_rate = rate


class _FakeModel:
    def __init__(self, repo):
        self.repo = repo
        self.last_kwargs = None

    def generate(self, **kwargs):
        self.last_kwargs = kwargs
        yield _Result()

    def generate_custom_voice(self, **kwargs):
        self.last_kwargs = kwargs
        yield _Result()


@pytest.fixture()
def engine(data_dir):
    eng = Qwen3Engine()
    eng._load_model = _FakeModel
    return eng


def _add_designed_voice(name="claire", transcript="Bonjour, ceci est ma voix."):
    wav = settings.voices_dir / f"{name}.wav"
    wav.write_bytes(b"RIFFfake")
    wav.with_suffix(".txt").write_text(transcript, encoding="utf-8")
    return wav


def test_list_voices_scans_designed_refs_then_presets(engine):
    _add_designed_voice("claire")
    (settings.voices_dir / "orpheline.wav").write_bytes(b"RIFF")  # sans transcript : ignorée

    voices = engine.list_voices()

    assert voices[0].voice_id == "ref:claire"
    assert voices[0].language == "fr"
    assert [v.voice_id for v in voices[-2:]] == ["spk:Ryan", "spk:Aiden"]
    assert not any(v.voice_id == "ref:orpheline" for v in voices)


def test_default_voice_prefers_designed_ref(engine):
    assert engine.default_voice() == "spk:Ryan"  # aucune voix designée
    _add_designed_voice("claire")
    assert engine.default_voice() == "ref:claire"


def test_synthesize_with_reference_voice(engine, tmp_path):
    _add_designed_voice("claire", transcript="Le transcript exact.")
    out = tmp_path / "chunk.wav"

    engine.synthesize("Bonjour le monde.", out, voice_id="ref:claire", language="fr")

    with wave.open(str(out), "rb") as w:
        assert w.getframerate() == 24000
        assert w.getnframes() == 2400
    kwargs = engine._model.last_kwargs
    assert kwargs["ref_text"] == "Le transcript exact."
    assert kwargs["lang_code"] == "french"
    assert engine._model.repo == settings.qwen3_base_model


def test_synthesize_with_preset_speaker(engine, tmp_path):
    out = tmp_path / "chunk.wav"

    engine.synthesize("Hello world.", out, voice_id="spk:Ryan", language="en")

    assert out.exists()
    kwargs = engine._model.last_kwargs
    assert kwargs["speaker"] == "Ryan"
    assert kwargs["language"] == "english"
    assert engine._model.repo == settings.qwen3_custom_model


def test_switching_voice_kind_swaps_model(engine, tmp_path):
    _add_designed_voice("claire")
    engine.synthesize("a", tmp_path / "1.wav", voice_id="ref:claire", language="fr")
    base_model = engine._model
    engine.synthesize("b", tmp_path / "2.wav", voice_id="spk:Ryan", language="en")
    assert engine._model is not base_model
    assert engine._model_kind == "custom"
    # Retour au clonage : rechargement du modèle Base
    engine.synthesize("c", tmp_path / "3.wav", voice_id="ref:claire", language="fr")
    assert engine._model_kind == "base"


def test_missing_reference_raises_clear_error(engine, tmp_path):
    with pytest.raises(TTSError, match="introuvable"):
        engine.synthesize("texte", tmp_path / "c.wav", voice_id="ref:inconnue", language="fr")


def test_invalid_voice_id_raises(engine, tmp_path):
    with pytest.raises(TTSError, match="invalide"):
        engine.synthesize("texte", tmp_path / "c.wav", voice_id="fr-FR-DeniseNeural", language="fr")


def test_unload_clears_model(engine, tmp_path):
    engine.synthesize("a", tmp_path / "1.wav", voice_id="spk:Ryan", language="en")
    assert engine._model is not None
    engine.unload()
    assert engine._model is None
    assert engine._model_kind is None
