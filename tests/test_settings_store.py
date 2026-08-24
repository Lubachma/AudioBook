"""Tests des préférences persistantes (table settings)."""

from app.config import settings
from app.settings_store import default_engine_name, default_voice_for, get_setting, set_setting


def test_roundtrip_and_update(data_dir):
    assert get_setting("default_engine") is None
    set_setting("default_engine", "kyutai")
    assert get_setting("default_engine") == "kyutai"
    set_setting("default_engine", "qwen3")
    assert get_setting("default_engine") == "qwen3"


def test_get_setting_without_db_returns_default(tmp_path):
    settings.data_dir = tmp_path / "vierge"  # aucune base créée
    assert get_setting("default_engine", "fallback") == "fallback"


def test_default_engine_falls_back_to_env_config(data_dir, monkeypatch):
    monkeypatch.setattr(settings, "default_engine", "qwen3")
    assert default_engine_name() == "qwen3"
    set_setting("default_engine", "kyutai")
    assert default_engine_name() == "kyutai"


def test_default_voice_per_engine(data_dir):
    assert default_voice_for("qwen3") == ""
    set_setting("default_voice:qwen3", "ref:claire")
    assert default_voice_for("qwen3") == "ref:claire"
    assert default_voice_for("kyutai") == ""
