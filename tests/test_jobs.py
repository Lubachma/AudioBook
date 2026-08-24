"""Tests du pipeline de jobs : dispatch moteur, reprise sans re-synthèse, migrations."""

import sqlite3

import pytest

from app import engines, jobs
from app.chapters import Chapter
from app.config import settings

from .conftest import FakeEngine


@pytest.fixture(autouse=True)
def _quiet_merge(monkeypatch):
    """L'assemblage réel (ffmpeg) est testé dans test_audio.py."""
    monkeypatch.setattr(
        jobs.audio,
        "merge_book",
        lambda chunk_dir, ext, mp3_out, m4b_out, **kw: (
            mp3_out.write_bytes(b"MERGED"),
            m4b_out.write_bytes(b"M4B"),
        ),
    )


def _make_book(engine="fake", text="Première phrase. Deuxième phrase."):
    job_id = jobs.create_job(title="test", language="fr", engine=engine)
    jobs.text_path(job_id).write_text(text, encoding="utf-8")
    jobs.update_job(job_id, status="extracted", char_count=len(text))
    return job_id


def _seed_valid_meta(job_id, engine_name="fake", voice_id="fv1"):
    """chunks.meta.json cohérent avec l'état courant (comme une vraie 1re tentative)."""
    engine = engines.get_engine(engine_name)
    text = jobs.text_path(job_id).read_text(encoding="utf-8")
    job = jobs.get_job(job_id)
    fingerprint = jobs._fingerprint(engine, text, [Chapter(title=job["title"], offset=0)], voice_id)
    directory = jobs.chunk_dir(job_id)
    directory.mkdir(parents=True, exist_ok=True)
    jobs.write_chunks_meta(directory, engine, 2, fingerprint)
    return directory


def test_run_conversion_skips_existing_chunks(data_dir, fake_engine, monkeypatch):
    """Un chunk déjà présent sur disque n'est pas re-synthétisé (reprise)."""
    monkeypatch.setattr(FakeEngine, "chunk_max_chars", 20)  # force 2 chunks
    job_id = _make_book()
    directory = _seed_valid_meta(job_id)
    (directory / "chunk_0001.mp3").write_bytes(b"DEJA LA")

    jobs.run_conversion(job_id)

    assert len(fake_engine.calls) == 1, f"chunk existant re-synthétisé : {fake_engine.calls}"
    assert jobs.get_job(job_id)["status"] == "done"


def test_voice_change_purges_chunks(data_dir, fake_engine, monkeypatch):
    """Changer de voix invalide les chunks existants (l'empreinte inclut la voix) :
    la reprise ne doit jamais mélanger deux voix dans un même livre."""
    monkeypatch.setattr(FakeEngine, "chunk_max_chars", 20)  # 2 chunks
    job_id = _make_book()
    directory = _seed_valid_meta(job_id, voice_id="fv1")  # 1re tentative avec fv1
    (directory / "chunk_0001.mp3").write_bytes(b"VOIX FV1")
    jobs.update_job(job_id, voice_id="fv2")  # reconversion demandée avec fv2

    jobs.run_conversion(job_id)

    assert len(fake_engine.calls) == 2  # tout re-synthétisé avec la nouvelle voix
    assert all(c["voice_id"] == "fv2" for c in fake_engine.calls)


def test_stale_chunks_are_purged(data_dir, fake_engine, monkeypatch):
    """Un dossier de chunks d'un AUTRE plan de découpage (moteur/params changés)
    est purgé avant reprise, sinon on mélangerait des chunks incompatibles."""
    monkeypatch.setattr(FakeEngine, "chunk_max_chars", 20)  # 2 chunks
    job_id = _make_book()
    directory = jobs.chunk_dir(job_id)
    directory.mkdir(parents=True)
    (directory / "chunk_0001.mp3").write_bytes(b"ANCIEN MOTEUR")  # pas de meta -> obsolète

    jobs.run_conversion(job_id)

    assert len(fake_engine.calls) == 2  # tout re-synthétisé
    assert jobs.get_job(job_id)["status"] == "done"


def test_zero_byte_chunk_is_resynthesized(data_dir, fake_engine, monkeypatch):
    """Un chunk vide (0 octet) n'est pas considéré comme terminé à la reprise."""
    monkeypatch.setattr(FakeEngine, "chunk_max_chars", 20)
    job_id = _make_book()
    directory = _seed_valid_meta(job_id)
    (directory / "chunk_0001.mp3").write_bytes(b"")  # résidu vide

    jobs.run_conversion(job_id)

    assert len(fake_engine.calls) == 2


def test_run_conversion_uses_job_voice(data_dir, fake_engine):
    job_id = jobs.create_job(title="t", language="fr", voice_id="voix-du-job", engine="fake")
    jobs.text_path(job_id).write_text("Une phrase.", encoding="utf-8")
    jobs.update_job(job_id, status="extracted", char_count=11)

    jobs.run_conversion(job_id)

    assert fake_engine.calls[0]["voice_id"] == "voix-du-job"


def test_run_conversion_falls_back_to_engine_default_voice(data_dir, fake_engine):
    job_id = jobs.create_job(title="t", language="fr", engine="fake")  # pas de voix choisie
    jobs.text_path(job_id).write_text("Une phrase.", encoding="utf-8")
    jobs.update_job(job_id, status="extracted", char_count=11)

    jobs.run_conversion(job_id)

    assert fake_engine.calls[0]["voice_id"] == "fv1"


def test_run_conversion_uses_bench_default_voice(data_dir, fake_engine):
    """La voix choisie au banc d'essai (table settings) prime sur le défaut du moteur."""
    from app.settings_store import set_setting

    set_setting("default_voice:fake", "fv2")
    job_id = jobs.create_job(title="t", language="fr", engine="fake")
    jobs.text_path(job_id).write_text("Une phrase.", encoding="utf-8")
    jobs.update_job(job_id, status="extracted", char_count=11)

    jobs.run_conversion(job_id)

    assert fake_engine.calls[0]["voice_id"] == "fv2"


def test_run_conversion_default_engine_fallback(data_dir, fake_engine, monkeypatch):
    """Job sans moteur explicite -> moteur par défaut de la config."""
    monkeypatch.setattr(settings, "default_engine", "fake")
    job_id = jobs.create_job(title="t", language="fr")
    jobs.text_path(job_id).write_text("Une phrase.", encoding="utf-8")
    jobs.update_job(job_id, status="extracted", char_count=11)

    jobs.run_conversion(job_id)

    assert len(fake_engine.calls) == 1
    assert jobs.get_job(job_id)["status"] == "done"


def test_run_conversion_edge_engine_rejected(data_dir, fake_engine):
    """Les livres historiques edge-tts ne sont plus convertibles (message clair)."""
    job_id = _make_book(engine="edge")

    jobs.run_conversion(job_id)

    job = jobs.get_job(job_id)
    assert job["status"] == "error"
    assert "edge-tts" in job["error"]


def test_run_conversion_unavailable_engine_reports_reason(data_dir, monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")
    job_id = _make_book(engine="elevenlabs")

    jobs.run_conversion(job_id)

    job = jobs.get_job(job_id)
    assert job["status"] == "error"
    assert "indisponible" in job["error"]


def test_run_conversion_noop_on_done_job(data_dir, fake_engine):
    """Garde anti double-traitement : un livre terminé n'est jamais re-synthétisé."""
    job_id = _make_book()
    jobs.update_job(job_id, status="done")

    jobs.run_conversion(job_id)  # ne doit rien faire, ni lever d'erreur

    assert fake_engine.calls == []


def test_conversion_writes_chapter_mapping_to_merge(data_dir, fake_engine, monkeypatch):
    """Les chunks sont assignés à leur chapitre et transmis à l'assemblage."""
    from app.chapters import save_chapters

    monkeypatch.setattr(FakeEngine, "chunk_max_chars", 30)
    job_id = jobs.create_job(title="t", language="fr", engine="fake")
    text = "Chapitre un. Du texte ici. Chapitre deux. Encore du texte."
    jobs.text_path(job_id).write_text(text, encoding="utf-8")
    save_chapters(
        jobs.chapters_path(job_id),
        [Chapter("Chapitre un", 0), Chapter("Chapitre deux", text.index("Chapitre deux"))],
    )
    jobs.update_job(job_id, status="extracted", char_count=len(text))

    captured = {}

    def fake_merge(chunk_dir, ext, mp3_out, m4b_out, **kw):
        captured.update(kw)
        mp3_out.write_bytes(b"M")
        m4b_out.write_bytes(b"M4B")

    monkeypatch.setattr(jobs.audio, "merge_book", fake_merge)

    jobs.run_conversion(job_id)

    assert captured["chapter_titles"] == ["Chapitre un", "Chapitre deux"]
    assert sorted(set(captured["chunk_chapters"])) == [0, 1]


def test_create_job_stores_voice_id(data_dir):
    job_id = jobs.create_job(title="t", language="fr", voice_id="voix42")
    assert jobs.get_job(job_id)["voice_id"] == "voix42"


def test_init_db_migrates_old_schema(tmp_path):
    """Une base d'avant la refonte (sans voice_label/source_type) est migrée sans perte."""
    settings.data_dir = tmp_path / "data"
    settings.ensure_dirs()
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute(
            "CREATE TABLE jobs (id TEXT PRIMARY KEY, title TEXT NOT NULL, language TEXT NOT NULL,"
            " status TEXT NOT NULL, char_count INTEGER NOT NULL DEFAULT 0,"
            " total_chunks INTEGER NOT NULL DEFAULT 0, done_chunks INTEGER NOT NULL DEFAULT 0,"
            " error TEXT, created_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO jobs (id, title, language, status, created_at) VALUES ('abc', 't', 'fr', 'extracted', '2024-01-01')"
        )

    jobs.init_db()

    job = jobs.get_job("abc")
    assert job is not None
    assert job["voice_id"] == ""
    assert job["engine"] == "elevenlabs"
    assert job["voice_label"] == ""
    assert job["source_type"] == "pdf"
    assert job["position_seconds"] == 0


def test_recover_interrupted_reenqueues_extractions(data_dir, monkeypatch):
    """Un redémarrage pendant l'extraction la relance (le fichier source est encore là)."""
    job_id = jobs.create_job(title="t", language="fr")
    assert jobs.get_job(job_id)["status"] == "extracting"

    enqueued = []
    monkeypatch.setattr(jobs, "enqueue", lambda jid, action: enqueued.append((jid, action)))

    jobs.recover_interrupted()

    assert jobs.get_job(job_id)["status"] == "extracting"  # pas d'erreur "ré-uploadez"
    assert (job_id, "extract") in enqueued


def test_recover_interrupted_resumes_conversions_automatically(data_dir, monkeypatch):
    """Un redémarrage en pleine conversion (ou en file) relance sans clic :
    les chunks déjà synthétisés seront réutilisés par la reprise."""
    converting = _make_book()
    jobs.update_job(converting, status="converting")
    queued = _make_book()
    jobs.update_job(queued, status="queued")

    enqueued = []
    monkeypatch.setattr(jobs, "enqueue", lambda jid, action: enqueued.append((jid, action)))

    jobs.recover_interrupted()

    assert jobs.get_job(converting)["status"] == "queued"
    assert (converting, "convert") in enqueued
    assert (queued, "convert") in enqueued


def test_record_speed_ignores_insignificant_measures(data_dir):
    from app.settings_store import get_setting

    jobs._record_speed("fake", chars=500, seconds=100)     # trop peu de texte
    jobs._record_speed("fake", chars=50_000, seconds=5)    # reprise quasi instantanée
    assert get_setting("speed_cpm:fake") is None

    jobs._record_speed("fake", chars=60_000, seconds=1800)  # 2000 car./min
    assert get_setting("speed_cpm:fake") == "2000"


def test_enqueue_routes_extractions_to_fast_queue(data_dir):
    """Les extractions (secondes) ne doivent pas attendre derrière une conversion (heures)."""
    jobs.enqueue("a", "extract")
    jobs.enqueue("b", "convert")
    assert jobs._extract_queue.get_nowait()["job_id"] == "a"
    assert jobs._queue.get_nowait()["job_id"] == "b"


# --------------------------------------------------------------- annulation

def test_cancel_before_start_keeps_job_convertible(data_dir, fake_engine):
    job_id = _make_book()
    jobs.request_cancel(job_id)

    jobs.run_conversion(job_id)

    assert fake_engine.calls == []  # rien synthétisé
    assert jobs.get_job(job_id)["status"] == "extracted"


def test_cancel_mid_conversion_keeps_chunks_for_resume(data_dir, fake_engine, monkeypatch):
    """L'annulation s'applique entre deux segments ; les segments faits restent
    sur disque et une relance reprend exactement là."""
    monkeypatch.setattr(FakeEngine, "chunk_max_chars", 20)  # 2 chunks

    original = fake_engine._synthesize.__func__

    def synth_then_cancel(self, text, out_path, *, voice_id, language):
        original(self, text, out_path, voice_id=voice_id, language=language)
        jobs.request_cancel(job_id)  # demandé pendant le 1er segment

    monkeypatch.setattr(FakeEngine, "_synthesize", synth_then_cancel)
    job_id = _make_book()

    jobs.run_conversion(job_id)

    assert len(fake_engine.calls) == 1  # arrêt avant le segment 2
    job = jobs.get_job(job_id)
    assert job["status"] == "extracted"
    chunk1 = jobs.chunk_dir(job_id) / "chunk_0001.mp3"
    assert chunk1.exists()  # conservé pour la reprise

    # Relance : le segment 1 est réutilisé, seul le 2 est synthétisé
    monkeypatch.setattr(FakeEngine, "_synthesize", original)
    jobs.run_conversion(job_id)
    assert len(fake_engine.calls) == 2
    assert jobs.get_job(job_id)["status"] == "done"


def test_clear_cancel_lets_conversion_proceed(data_dir, fake_engine):
    job_id = _make_book()
    jobs.request_cancel(job_id)
    jobs.clear_cancel(job_id)

    jobs.run_conversion(job_id)

    assert jobs.get_job(job_id)["status"] == "done"


# --------------------------------------------------------- contrôle qualité

def _qc_book(fake_local_engine):
    job_id = jobs.create_job(title="t", language="fr", engine="fake-local")
    jobs.text_path(job_id).write_text("Une phrase à contrôler.", encoding="utf-8")
    jobs.update_job(job_id, status="extracted", char_count=23)
    return job_id


def test_qc_retries_bad_chunk_and_keeps_best(data_dir, fake_local_engine, monkeypatch):
    """Un chunk suspect (transcription trop éloignée) déclenche une seconde prise."""
    monkeypatch.setattr(settings, "qc_enabled", True)
    monkeypatch.setattr(settings, "qc_min_ratio", 0.7)
    monkeypatch.setattr(jobs.qc, "available", lambda: True)
    ratios = iter([0.3, 0.95])  # 1re prise mauvaise, 2e bonne
    checked = []

    def fake_ratio(path, text, *, language):
        checked.append(str(path))
        return next(ratios)

    monkeypatch.setattr(jobs.qc, "match_ratio", fake_ratio)

    job_id = _qc_book(fake_local_engine)
    jobs.run_conversion(job_id)

    assert len(fake_local_engine.calls) == 2  # synthèse + seconde prise
    assert len(checked) == 2
    assert jobs.get_job(job_id)["status"] == "done"


def test_qc_keeps_first_take_when_second_is_worse(data_dir, fake_local_engine, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "qc_enabled", True)
    monkeypatch.setattr(settings, "qc_min_ratio", 0.9)
    monkeypatch.setattr(jobs.qc, "available", lambda: True)
    ratios = iter([0.6, 0.4])
    monkeypatch.setattr(jobs.qc, "match_ratio", lambda p, t, *, language: next(ratios))

    take = []

    def synth(text, out_path, *, voice_id, language):
        take.append(1)
        from pathlib import Path

        Path(out_path).write_bytes(f"PRISE{len(take)}".encode())

    monkeypatch.setattr(fake_local_engine, "_synthesize", synth)

    chunk = tmp_path / "chunk_0001.wav"
    jobs._synthesize_checked(
        fake_local_engine, "texte", chunk, voice_id="fv1", language="fr", use_qc=True
    )

    assert chunk.read_bytes() == b"PRISE1"  # la meilleure des deux prises est conservée
    assert not chunk.with_name(chunk.name + ".take1").exists()


def test_qc_disabled_never_transcribes(data_dir, fake_local_engine, monkeypatch):
    monkeypatch.setattr(settings, "qc_enabled", False)
    called = []
    monkeypatch.setattr(jobs.qc, "match_ratio", lambda *a, **k: called.append(1) or 1.0)

    job_id = _qc_book(fake_local_engine)
    jobs.run_conversion(job_id)

    assert called == []
    assert len(fake_local_engine.calls) == 1


def test_qc_failure_never_blocks_book(data_dir, fake_local_engine, monkeypatch):
    """whisper qui explose ne doit pas faire échouer la conversion."""
    monkeypatch.setattr(settings, "qc_enabled", True)
    monkeypatch.setattr(jobs.qc, "available", lambda: True)

    def boom(*a, **k):
        raise RuntimeError("whisper cassé")

    monkeypatch.setattr(jobs.qc, "match_ratio", boom)

    job_id = _qc_book(fake_local_engine)
    jobs.run_conversion(job_id)

    assert jobs.get_job(job_id)["status"] == "done"


def test_delete_job_removes_all_artifacts(data_dir, fake_engine):
    job_id = _make_book()
    jobs.run_conversion(job_id)
    assert jobs.audio_path(job_id).exists()
    assert jobs.m4b_path(job_id).exists()

    jobs.delete_job(job_id)

    assert not jobs.audio_path(job_id).exists()
    assert not jobs.m4b_path(job_id).exists()
    assert not jobs.text_path(job_id).exists()
    assert jobs.get_job(job_id) is None
