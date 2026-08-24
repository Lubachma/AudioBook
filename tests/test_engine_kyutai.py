"""Tests du moteur kyutai : protocole du worker subprocess (stub Python)."""

import sys
import textwrap
from pathlib import Path

import pytest

from app.config import settings
from app.engines import TTSError
from app.engines.kyutai import KyutaiEngine

STUB_WORKER = textwrap.dedent(
    """
    import json, sys
    # argparse minimal : on ignore les options (--hf-repo, etc.)
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        if "boom" in req["text"]:
            print(json.dumps({"ok": False, "error": "explosion simulée"}), flush=True)
            continue
        if "crash" in req["text"]:
            sys.exit(3)
        with open(req["out"], "wb") as f:
            f.write(b"RIFF" + req["voice"].encode())
        print(json.dumps({"ok": True, "seconds": 1.0}), flush=True)
    """
)


@pytest.fixture()
def engine(data_dir, tmp_path, monkeypatch):
    stub = tmp_path / "stub_worker.py"
    stub.write_text(STUB_WORKER, encoding="utf-8")
    monkeypatch.setattr(settings, "kyutai_python", Path(sys.executable))
    monkeypatch.setattr(settings, "kyutai_worker_script", stub)
    monkeypatch.setattr(settings, "kyutai_load_timeout", 30.0)
    monkeypatch.setattr(settings, "kyutai_synth_timeout", 30.0)
    eng = KyutaiEngine()
    yield eng
    eng.unload()


def test_availability_requires_venv(monkeypatch, data_dir):
    monkeypatch.setattr(settings, "kyutai_python", Path("/nulle/part/python"))
    ok, reason = KyutaiEngine().availability()
    assert ok is False
    assert "install" in reason


def test_synthesize_via_worker(engine, tmp_path):
    out = tmp_path / "chunk.wav"
    engine.synthesize("Bonjour le monde.", out, voice_id="voix-fr.wav", language="fr")
    assert out.read_bytes() == b"RIFFvoix-fr.wav"


def test_worker_survives_between_requests(engine, tmp_path):
    engine.synthesize("Un.", tmp_path / "1.wav", voice_id="v.wav", language="fr")
    proc = engine._proc
    engine.synthesize("Deux.", tmp_path / "2.wav", voice_id="v.wav", language="fr")
    assert engine._proc is proc  # même daemon, pas de rechargement


def test_worker_error_reported(engine, tmp_path):
    with pytest.raises(TTSError, match="explosion"):
        engine.synthesize("boom", tmp_path / "c.wav", voice_id="v.wav", language="fr")


def test_worker_death_detected_and_recovers(engine, tmp_path):
    with pytest.raises(TTSError):
        engine.synthesize("crash", tmp_path / "c.wav", voice_id="v.wav", language="fr")
    # Le prochain appel relance un worker propre
    out = tmp_path / "apres.wav"
    engine.synthesize("Ça repart.", out, voice_id="v.wav", language="fr")
    assert out.exists()


def test_unload_terminates_worker(engine, tmp_path):
    engine.synthesize("Un.", tmp_path / "1.wav", voice_id="v.wav", language="fr")
    proc = engine._proc
    engine.unload()
    assert engine._proc is None
    assert proc.poll() is not None  # process terminé


def test_default_voice_is_french_female(engine):
    assert engine.default_voice() == "unmute-prod-website/developpeuse-3.wav"
    assert engine.list_voices()[0].language == "fr"
