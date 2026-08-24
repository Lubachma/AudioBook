"""Tests du module banc d'essai (état, filtrage par langue, erreurs)."""

from app import previews


def test_list_previews_filters_by_language(data_dir, fake_engine):
    fr = previews.list_previews("fake", "fr")
    en = previews.list_previews("fake", "en")
    assert [v["voice_id"] for v in fr] == ["fv1"]
    assert [v["voice_id"] for v in en] == ["fv2"]
    assert fr[0]["status"] == "missing"


def test_run_preview_writes_cache_and_is_idempotent(data_dir, fake_engine):
    item = {"engine": "fake", "voice_id": "fv1", "language": "fr"}
    previews.run_preview(item)

    path = previews.preview_path("fake", "fv1", "fr")
    assert path.exists()
    assert previews.list_previews("fake", "fr")[0]["status"] == "ready"

    # Second appel : le cache est conservé, pas de re-synthèse
    calls_before = len(fake_engine.calls)
    previews.run_preview(item)
    assert len(fake_engine.calls) == calls_before


def test_mark_error_surfaces_in_listing(data_dir, fake_engine):
    previews.mark_pending("fake", "fv1", "fr")
    assert previews.list_previews("fake", "fr")[0]["status"] == "pending"

    previews.mark_error({"engine": "fake", "voice_id": "fv1", "language": "fr"}, "explosion")
    row = previews.list_previews("fake", "fr")[0]
    assert row["status"] == "error"
    assert "explosion" in row["error"]
