"""Intégration réelle des moteurs locaux (téléchargement de modèles, minutes de calcul).

Exclus par défaut (pytest.ini : -m "not slow"). Lancer explicitement :
    uv run pytest -m slow -s tests/test_local_integration.py
"""

import shutil

import pytest

pytestmark = pytest.mark.slow


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg requis")
def test_qwen3_real_short_synthesis(tmp_path, data_dir):
    pytest.importorskip("mlx_audio")
    from app.engines import get_engine

    engine = get_engine("qwen3")
    out = tmp_path / "sample.wav"
    engine.synthesize(
        "Bonjour, ceci est un court test de synthèse locale.",
        out,
        voice_id="spk:Ryan",
        language="fr",
    )
    assert out.stat().st_size > 10_000

    from app.audio import wav_duration

    assert wav_duration(out) > 1.0


def test_kyutai_real_short_synthesis(tmp_path, data_dir):
    from app.config import settings
    from app.engines import get_engine

    if not settings.kyutai_python.exists():
        pytest.skip(".venv-kyutai absent")
    engine = get_engine("kyutai")
    out = tmp_path / "sample.wav"
    try:
        engine.synthesize(
            "Bonjour, ceci est un court test de synthèse locale.",
            out,
            voice_id="unmute-prod-website/developpeuse-3.wav",
            language="fr",
        )
    finally:
        engine.unload()
    assert out.stat().st_size > 10_000
