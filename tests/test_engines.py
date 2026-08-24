"""Tests du registre de moteurs : résolution, activation exclusive, retry, atomicité."""

from pathlib import Path

import pytest

from app import engines
from app.engines import AuthError, QuotaExceededError, TTSError

from .conftest import FakeEngine, FakeLocalEngine, register_engine


def test_engine_names_order():
    names = engines.engine_names()
    assert names[:3] == ["qwen3", "kyutai", "elevenlabs"]


def test_get_engine_unknown_raises():
    with pytest.raises(TTSError):
        engines.get_engine("edge")


def test_get_engine_is_singleton():
    assert engines.get_engine("qwen3") is engines.get_engine("qwen3")


def test_activate_unloads_other_local_engines(monkeypatch, fake_local_engine):
    class OtherLocal(FakeLocalEngine):
        name = "other-local"
        label = "Autre local"

    other = register_engine(monkeypatch, OtherLocal())

    engines.activate("fake-local")
    assert fake_local_engine.loaded == 1
    assert other.unloaded == 1
    assert fake_local_engine.unloaded == 0

    engines.activate("other-local")
    assert other.loaded == 1
    assert fake_local_engine.unloaded == 1


def test_activate_keeps_cloud_engines_untouched(monkeypatch, fake_engine, fake_local_engine):
    engines.activate("fake-local")
    assert fake_engine.unloaded == 0  # moteur cloud : rien à décharger


def test_unload_all(monkeypatch, fake_local_engine):
    engines.activate("fake-local")
    engines.unload_all()
    assert fake_local_engine.unloaded >= 1


def test_describe_reports_availability(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "elevenlabs_api_key", "")
    rows = {row["name"]: row for row in engines.describe()}
    assert rows["elevenlabs"]["available"] is False
    assert "Clé API" in rows["elevenlabs"]["reason"]


# ------------------------------------------------------------ base commune

class _FailingEngine(FakeEngine):
    name = "failing"
    label = "Failing"

    def __init__(self, errors):
        super().__init__()
        self.errors = list(errors)

    def _synthesize(self, text, out_path, *, voice_id, language):
        if self.errors:
            raise self.errors.pop(0)
        super()._synthesize(text, out_path, voice_id=voice_id, language=language)


def test_retry_recovers_from_transient_error(tmp_path):
    engine = _FailingEngine([RuntimeError("réseau")])
    out = tmp_path / "c.mp3"
    engine.synthesize_with_retry("texte", out, voice_id="v", language="fr", base_delay=0)
    assert out.read_bytes().startswith(b"FAKEMP3")


def test_retry_gives_up_after_attempts(tmp_path):
    engine = _FailingEngine([RuntimeError("1"), RuntimeError("2"), RuntimeError("3")])
    with pytest.raises(RuntimeError):
        engine.synthesize_with_retry("texte", tmp_path / "c.mp3", voice_id="v", language="fr", base_delay=0)
    assert len(engine.errors) == 0  # les 3 tentatives ont été consommées


@pytest.mark.parametrize("error", [QuotaExceededError("quota"), AuthError("clé")])
def test_quota_and_auth_never_retried(tmp_path, error):
    engine = _FailingEngine([error, RuntimeError("ne doit pas être atteint")])
    with pytest.raises(type(error)):
        engine.synthesize_with_retry("texte", tmp_path / "c.mp3", voice_id="v", language="fr", base_delay=0)
    assert len(engine.errors) == 1  # une seule tentative


def test_atomic_write_no_partial_file_on_failure(tmp_path):
    """Un échec en cours de synthèse ne doit laisser AUCUN fichier : sinon la
    reprise le croirait complet et l'assemblage produirait un livre corrompu."""

    class PartialEngine(FakeEngine):
        name = "partial"
        label = "Partial"

        def _synthesize(self, text, out_path, *, voice_id, language):
            Path(out_path).write_bytes(b"PARTIEL")
            raise RuntimeError("coupure en plein stream")

    out = tmp_path / "c.mp3"
    with pytest.raises(RuntimeError):
        PartialEngine().synthesize("texte", out, voice_id="v", language="fr")
    assert not out.exists()
    assert not out.with_name(out.name + ".part").exists()


def test_empty_output_rejected(tmp_path):
    class EmptyEngine(FakeEngine):
        name = "empty"
        label = "Empty"

        def _synthesize(self, text, out_path, *, voice_id, language):
            Path(out_path).write_bytes(b"")

    with pytest.raises(TTSError):
        EmptyEngine().synthesize("texte", tmp_path / "c.mp3", voice_id="v", language="fr")
    assert not (tmp_path / "c.mp3").exists()
