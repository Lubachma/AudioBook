"""Tests de l'assemblage audio : durées, FFMETADATA, commandes ffmpeg (mockées)."""

import wave

import numpy as np
import pytest

from app import audio
from app.audio import AudioError, build_ffmetadata, merge_book, wav_duration, write_wav_int16
from app.config import settings


def _write_silence(path, seconds, rate=24000):
    write_wav_int16(path, np.zeros(int(seconds * rate), dtype=np.float32), rate)


def test_write_wav_roundtrip(tmp_path):
    path = tmp_path / "t.wav"
    write_wav_int16(path, np.full(2400, 0.25, dtype=np.float32), 24000)
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getframerate() == 24000
        assert w.getnframes() == 2400
    assert wav_duration(path) == pytest.approx(0.1)


def test_write_wav_flattens_channel_dim(tmp_path):
    path = tmp_path / "t.wav"
    write_wav_int16(path, np.zeros((1, 4800), dtype=np.float32), 24000)
    assert wav_duration(path) == pytest.approx(0.2)


def test_build_ffmetadata_chapters_and_escaping():
    meta = build_ffmetadata("Titre = spécial; #1", "Voix", [("Chapitre 1", 0, 1500), ("Fin", 1500, 3000)])
    assert meta.startswith(";FFMETADATA1\n")
    assert "title=Titre \\= spécial\\; \\#1" in meta
    assert meta.count("[CHAPTER]") == 2
    assert "TIMEBASE=1/1000" in meta
    assert "START=1500" in meta and "END=3000" in meta


@pytest.fixture()
def fake_ffmpeg(monkeypatch):
    """Capture les commandes ffmpeg et crée le fichier de sortie (dernier argument)."""
    commands = []

    def run(cmd):
        commands.append(cmd)
        from pathlib import Path

        Path(cmd[-1]).write_bytes(b"OUT")

    monkeypatch.setattr(audio, "_run_ffmpeg", run)
    return commands


def test_merge_book_wav_encodes_and_chapters(tmp_path, fake_ffmpeg, data_dir):
    chunk_dir = tmp_path / "chunks"
    chunk_dir.mkdir()
    _write_silence(chunk_dir / "chunk_0001.wav", 0.5)
    _write_silence(chunk_dir / "chunk_0002.wav", 0.5)
    _write_silence(chunk_dir / "chunk_0003.wav", 1.0)

    mp3_out = tmp_path / "livre.mp3"
    m4b_out = tmp_path / "livre.m4b"
    merge_book(
        chunk_dir,
        "wav",
        mp3_out,
        m4b_out,
        chapter_titles=["Un", "Deux"],
        chunk_chapters=[0, 0, 1],
        title="Mon livre",
        artist="Claire",
    )

    assert mp3_out.read_bytes() == b"OUT"
    assert m4b_out.read_bytes() == b"OUT"
    assert not list(tmp_path.glob("*.tmp.*"))  # sorties atomiques renommées

    mp3_cmd, m4b_cmd = fake_ffmpeg
    assert "libmp3lame" in mp3_cmd
    assert settings.mp3_bitrate in mp3_cmd
    assert "aac" in m4b_cmd and "ipod" in m4b_cmd

    # Chemins absolus dans la liste concat (bug historique du Pi)
    for line in (chunk_dir / "concat.txt").read_text().splitlines():
        path = line.removeprefix("file '").removesuffix("'")
        assert path.startswith("/"), f"chemin relatif dans la liste ffmpeg : {path}"

    # Chapitres : 0-1s puis 1-2s
    meta = (chunk_dir / "chapters.ffmeta").read_text()
    assert "title=Un" in meta and "title=Deux" in meta
    assert "START=0" in meta and "START=1000" in meta and "END=2000" in meta


def test_merge_book_mp3_copies_without_reencoding(tmp_path, fake_ffmpeg, monkeypatch, data_dir):
    monkeypatch.setattr(audio, "mp3_duration", lambda p: 1.0)
    chunk_dir = tmp_path / "chunks"
    chunk_dir.mkdir()
    (chunk_dir / "chunk_0001.mp3").write_bytes(b"A")
    (chunk_dir / "chunk_0002.mp3").write_bytes(b"B")

    merge_book(
        chunk_dir,
        "mp3",
        tmp_path / "l.mp3",
        tmp_path / "l.m4b",
        chapter_titles=["Livre"],
        chunk_chapters=[0, 0],
        title="Livre",
    )

    mp3_cmd = fake_ffmpeg[0]
    assert "copy" in mp3_cmd
    assert "libmp3lame" not in mp3_cmd


def test_merge_book_mismatch_raises(tmp_path, data_dir):
    chunk_dir = tmp_path / "chunks"
    chunk_dir.mkdir()
    _write_silence(chunk_dir / "chunk_0001.wav", 0.1)

    with pytest.raises(AudioError, match="Incohérence"):
        merge_book(
            chunk_dir, "wav", tmp_path / "l.mp3", tmp_path / "l.m4b",
            chapter_titles=["Un"], chunk_chapters=[0, 0], title="L",
        )


def test_merge_book_empty_dir_raises(tmp_path, data_dir):
    chunk_dir = tmp_path / "chunks"
    chunk_dir.mkdir()
    with pytest.raises(AudioError, match="Aucun chunk"):
        merge_book(
            chunk_dir, "wav", tmp_path / "l.mp3", tmp_path / "l.m4b",
            chapter_titles=[], chunk_chapters=[], title="L",
        )
