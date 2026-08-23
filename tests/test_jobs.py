"""Tests du pipeline de jobs : assemblage ffmpeg et reprise sans re-facturation."""

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
    job_id = jobs.create_job(title="test", language="fr")
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
