"""Fixtures partagées : données isolées, faux moteurs TTS, constructeurs PDF/EPUB."""

import zipfile
from pathlib import Path

import pytest

from app import engines, jobs
from app.config import settings
from app.engines.base import Engine, Voice


@pytest.fixture()
def data_dir(tmp_path):
    settings.data_dir = tmp_path / "data"
    settings.ensure_dirs()
    jobs.init_db()
    return settings.data_dir


@pytest.fixture(autouse=True)
def _clean_previews_state(monkeypatch):
    """L'état mémoire du banc d'essai ne doit pas fuiter d'un test à l'autre."""
    from app import previews

    monkeypatch.setattr(previews, "_state", {})


class FakeEngine(Engine):
    """Moteur cloud factice : trace les appels, écrit des chunks binaires."""

    name = "fake"
    label = "Fake (test)"
    chunk_max_chars = 4000
    chunk_ext = "mp3"
    is_local = False

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.loaded = 0
        self.unloaded = 0

    def list_voices(self) -> list[Voice]:
        return [Voice("fv1", "Fausse voix", "test", "fr"), Voice("fv2", "Fake voice", "test", "en")]

    def default_voice(self) -> str:
        return "fv1"

    def load(self) -> None:
        self.loaded += 1

    def unload(self) -> None:
        self.unloaded += 1

    def _synthesize(self, text: str, out_path: Path, *, voice_id: str, language: str) -> None:
        self.calls.append({"text": text, "voice_id": voice_id, "language": language})
        Path(out_path).write_bytes(b"FAKEMP3" + text[:8].encode())


class FakeLocalEngine(FakeEngine):
    name = "fake-local"
    label = "Fake local (test)"
    chunk_ext = "wav"
    is_local = True


def register_engine(monkeypatch, engine: Engine) -> Engine:
    monkeypatch.setitem(engines._CLASSES, engine.name, type(engine))
    monkeypatch.setitem(engines._instances, engine.name, engine)
    return engine


@pytest.fixture()
def fake_engine(monkeypatch):
    return register_engine(monkeypatch, FakeEngine())


@pytest.fixture()
def fake_local_engine(monkeypatch):
    return register_engine(monkeypatch, FakeLocalEngine())


def make_epub(
    path: Path,
    chapters: list[tuple[str, str]],
    with_ncx: bool = True,
    cover_jpeg: bytes | None = None,
) -> Path:
    """EPUB 2 minimal : mimetype, container, OPF (spine) et un XHTML par chapitre."""
    manifest_items = []
    spine_items = []
    nav_points = []
    docs = []
    for i, (title, body) in enumerate(chapters, start=1):
        manifest_items.append(
            f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>'
        )
        spine_items.append(f'<itemref idref="c{i}"/>')
        nav_points.append(
            f'<navPoint id="n{i}" playOrder="{i}"><navLabel><text>{title}</text></navLabel>'
            f'<content src="c{i}.xhtml"/></navPoint>'
        )
        docs.append(
            (
                f"OEBPS/c{i}.xhtml",
                f"<html><head><title>x</title></head><body><h1>{title}</h1><p>{body}</p></body></html>",
            )
        )

    ncx_manifest = (
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>' if with_ncx else ""
    )
    cover_manifest = ""
    cover_meta = ""
    if cover_jpeg is not None:
        cover_manifest = '<item id="cover-img" href="cover.jpg" media-type="image/jpeg"/>'
        cover_meta = '<meta name="cover" content="cover-img"/>'
    opf = f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid">
  <metadata>{cover_meta}</metadata>
  <manifest>{ncx_manifest}{cover_manifest}{''.join(manifest_items)}</manifest>
  <spine toc="ncx">{''.join(spine_items)}</spine>
</package>"""
    ncx = f"""<?xml version="1.0"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <navMap>{''.join(nav_points)}</navMap>
</ncx>"""
    container = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/content.opf", opf)
        if with_ncx:
            z.writestr("OEBPS/toc.ncx", ncx)
        if cover_jpeg is not None:
            z.writestr("OEBPS/cover.jpg", cover_jpeg)
        for name, content in docs:
            z.writestr(name, content)
    return path
