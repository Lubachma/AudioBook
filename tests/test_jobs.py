"""Tests du pipeline de jobs : assemblage ffmpeg et reprise sans re-facturation."""

import sqlite3
import subprocess
from pathlib import Path

import pytest

from app import jobs
from app.config import settings


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    settings.data_dir = tmp_path / "data"
    settings.ensure_dirs()
    jobs.init_db()
    return settings.data_dir


def _make_book():
    job_id = jobs.create_job(title="test", language="fr", engine="elevenlabs")
    jobs.text_path(job_id).write_text("Première phrase. Deuxième phrase.", encoding="utf-8")
    return job_id


def test_merge_chunks_writes_absolute_paths(data_dir, monkeypatch, tmp_path):
    """Le concat demuxer de ffmpeg résout les chemins relatifs par rapport au
    dossier du fichier liste, pas au CWD : la liste doit être en absolu.
    Reproduit le bug de production (data_dir relatif -> exit 254)."""
    monkeypatch.chdir(tmp_path)  # simule le WorkingDirectory du service
    chunk_directory = Path("data/audio/job_chunks")  # relatif, comme en prod
    chunk_directory.mkdir(parents=True)
    (chunk_directory / "chunk_0001.mp3").write_bytes(b"FAKE1")
    (chunk_directory / "chunk_0002.mp3").write_bytes(b"FAKE2")

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["list_content"] = (chunk_directory / "concat.txt").read_text()

    monkeypatch.setattr(subprocess, "run", fake_run)
    jobs.merge_chunks(chunk_directory, Path("data/audio/out.mp3"))

    for line in captured["list_content"].splitlines():
        path = line.removeprefix("file '").removesuffix("'")
        assert path.startswith("/"), f"chemin relatif dans la liste ffmpeg : {path}"


def test_run_conversion_skips_existing_chunks(data_dir, monkeypatch):
    """Un chunk déjà présent sur disque ne doit pas être re-facturé à ElevenLabs."""
    monkeypatch.setattr(settings, "chunk_max_chars", 20)  # force 2 chunks
    job_id = _make_book()
    jobs.update_job(job_id, status="extracted", char_count=38)

    # chunk 1 déjà généré lors d'une tentative précédente
    chunk_directory = jobs.chunk_dir(job_id)
    chunk_directory.mkdir(parents=True)
    (chunk_directory / "chunk_0001.mp3").write_bytes(b"DEJA LA")

    calls = []

    def fake_tts(text, out_path, **kw):
        calls.append(text)
        out_path.write_bytes(b"NOUVEAU")

    monkeypatch.setattr(jobs, "synthesize_with_retry", fake_tts)
    monkeypatch.setattr(jobs, "merge_chunks", lambda d, o: o.write_bytes(b"MERGED"))

    jobs.run_conversion(job_id)

    assert len(calls) == 1, f"chunk existant re-facturé : {calls}"
    assert jobs.get_job(job_id)["status"] == "done"


def test_init_db_migrates_old_schema(tmp_path, monkeypatch):
    """Une base créée avant l'ajout de la colonne voice_id est migrée sans perte."""
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


def test_create_job_stores_voice_id(data_dir):
    job_id = jobs.create_job(title="t", language="fr", voice_id="voix42")
    assert jobs.get_job(job_id)["voice_id"] == "voix42"


def test_run_conversion_uses_job_voice(data_dir, monkeypatch):
    job_id = jobs.create_job(title="t", language="fr", voice_id="voix-du-job", engine="elevenlabs")
    jobs.text_path(job_id).write_text("Une phrase.", encoding="utf-8")
    jobs.update_job(job_id, status="extracted", char_count=11)

    captured = {}

    def fake_tts(text, out_path, **kw):
        captured.update(kw)
        out_path.write_bytes(b"X")

    monkeypatch.setattr(jobs, "synthesize_with_retry", fake_tts)
    monkeypatch.setattr(jobs, "merge_chunks", lambda d, o: o.write_bytes(b"M"))

    jobs.run_conversion(job_id)

    assert captured["voice_id"] == "voix-du-job"


def test_run_conversion_falls_back_to_default_voice(data_dir, monkeypatch):
    job_id = jobs.create_job(title="t", language="fr", engine="elevenlabs")  # pas de voix choisie
    jobs.text_path(job_id).write_text("Une phrase.", encoding="utf-8")
    jobs.update_job(job_id, status="extracted", char_count=11)

    captured = {}

    def fake_tts(text, out_path, **kw):
        captured.update(kw)
        out_path.write_bytes(b"X")

    monkeypatch.setattr(jobs, "synthesize_with_retry", fake_tts)
    monkeypatch.setattr(jobs, "merge_chunks", lambda d, o: o.write_bytes(b"M"))

    jobs.run_conversion(job_id)

    assert captured["voice_id"] == settings.elevenlabs_voice_id


def test_init_db_migrates_adds_engine(tmp_path, monkeypatch):
    """La colonne engine est ajoutée aux bases existantes (défaut elevenlabs)."""
    settings.data_dir = tmp_path / "data"
    settings.ensure_dirs()
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute(
            "CREATE TABLE jobs (id TEXT PRIMARY KEY, title TEXT NOT NULL, language TEXT NOT NULL,"
            " status TEXT NOT NULL, char_count INTEGER NOT NULL DEFAULT 0,"
            " total_chunks INTEGER NOT NULL DEFAULT 0, done_chunks INTEGER NOT NULL DEFAULT 0,"
            " error TEXT, created_at TEXT NOT NULL, voice_id TEXT NOT NULL DEFAULT '')"
        )
        conn.execute(
            "INSERT INTO jobs (id, title, language, status, created_at) VALUES ('abc', 't', 'fr', 'extracted', '2024-01-01')"
        )

    jobs.init_db()

    assert jobs.get_job("abc")["engine"] == "elevenlabs"


def test_run_conversion_dispatches_to_edge(data_dir, monkeypatch):
    job_id = jobs.create_job(title="t", language="fr", voice_id="fr-FR-HenriNeural", engine="edge")
    jobs.text_path(job_id).write_text("Une phrase.", encoding="utf-8")
    jobs.update_job(job_id, status="extracted", char_count=11)

    captured = {}

    def fake_edge(text, out_path, **kw):
        captured.update(kw)
        out_path.write_bytes(b"E")

    monkeypatch.setattr(jobs, "synthesize_edge_with_retry", fake_edge)
    monkeypatch.setattr(
        jobs, "synthesize_with_retry", lambda *a, **kw: pytest.fail("ElevenLabs ne doit pas être appelé")
    )
    monkeypatch.setattr(jobs, "merge_chunks", lambda d, o: o.write_bytes(b"M"))

    jobs.run_conversion(job_id)

    assert captured["voice"] == "fr-FR-HenriNeural"
    assert jobs.get_job(job_id)["status"] == "done"


def test_run_conversion_default_engine_fallback(data_dir, monkeypatch):
    """Job sans moteur explicite -> moteur par défaut de la config."""
    monkeypatch.setattr(settings, "default_engine", "edge")
    job_id = jobs.create_job(title="t", language="fr")
    jobs.text_path(job_id).write_text("Une phrase.", encoding="utf-8")
    jobs.update_job(job_id, status="extracted", char_count=11)

    used = []

    monkeypatch.setattr(
        jobs, "synthesize_edge_with_retry", lambda t, o, **kw: (used.append("edge"), o.write_bytes(b"E"))
    )
    monkeypatch.setattr(jobs, "merge_chunks", lambda d, o: o.write_bytes(b"M"))

    jobs.run_conversion(job_id)

    assert used == ["edge"]
