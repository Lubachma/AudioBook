"""Extraction texte + chapitres d'un EPUB — stdlib uniquement (zipfile, ElementTree, html.parser).

Un EPUB est un zip : META-INF/container.xml pointe vers l'OPF, dont le <spine>
donne l'ordre de lecture des documents XHTML. Chaque document du spine devient
un chapitre ; son titre vient de la table des matières (NCX ou nav EPUB3), à
défaut du premier <h1>/<h2>/<h3>, à défaut « Chapitre N ».
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

from .chapters import Chapter

_NS = {
    "cnt": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
}
_XHTML_TYPES = {"application/xhtml+xml", "text/html"}
# Un document du spine plus court que ça (page de garde, page blanche) est ignoré.
MIN_DOC_CHARS = 20


class EpubError(Exception):
    """EPUB illisible ou sans texte exploitable."""


_BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "td", "th", "section", "article", "aside",
    "blockquote", "figcaption", "h1", "h2", "h3", "h4", "h5", "h6", "hr",
}
_SKIP_TAGS = {"script", "style", "head", "title"}
_HEADING_TAGS = ("h1", "h2", "h3")


class _TextExtractor(HTMLParser):
    """Texte brut d'un document XHTML + premier titre h1/h2/h3 rencontré."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.first_heading = ""
        self._skip_depth = 0
        self._heading_tag: str | None = None
        self._heading_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag in _HEADING_TAGS and not self.first_heading and self._heading_tag is None:
            self._heading_tag = tag
            self._heading_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == self._heading_tag:
            heading = _normalize_spaces("".join(self._heading_parts))
            if heading:
                self.first_heading = heading
            self._heading_tag = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self.parts.append(data)
        if self._heading_tag is not None:
            self._heading_parts.append(data)


class _AnchorCollector(HTMLParser):
    """Paires (href, texte) des <a> d'un document de navigation EPUB3."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            label = _normalize_spaces("".join(self._text))
            if label:
                self.anchors.append((self._href, label))
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _doc_text(html: str) -> tuple[str, str]:
    parser = _TextExtractor()
    parser.feed(html)
    return _normalize_spaces("".join(parser.parts)), parser.first_heading


def _resolve(base_dir: str, href: str) -> str:
    """href relatif (potentiellement encodé, avec fragment) -> chemin dans le zip."""
    path = unquote(urlparse(href).path)
    return posixpath.normpath(posixpath.join(base_dir, path))


def _toc_titles(z: zipfile.ZipFile, manifest: dict[str, ET.Element], opf_dir: str) -> dict[str, str]:
    """Chemin de document -> titre, depuis le nav EPUB3 ou le NCX EPUB2."""
    titles: dict[str, str] = {}
    nav_item = next(
        (item for item in manifest.values() if "nav" in (item.get("properties") or "").split()),
        None,
    )
    ncx_item = next(
        (item for item in manifest.values() if item.get("media-type") == "application/x-dtbncx+xml"),
        None,
    )
    try:
        if nav_item is not None:
            nav_path = _resolve(opf_dir, nav_item.get("href", ""))
            collector = _AnchorCollector()
            collector.feed(z.read(nav_path).decode("utf-8", "replace"))
            nav_dir = posixpath.dirname(nav_path)
            for href, label in collector.anchors:
                titles.setdefault(_resolve(nav_dir, href), label)
        elif ncx_item is not None:
            ncx_path = _resolve(opf_dir, ncx_item.get("href", ""))
            ncx = ET.fromstring(z.read(ncx_path))
            ncx_dir = posixpath.dirname(ncx_path)
            for nav_point in ncx.iter(f"{{{_NS['ncx']}}}navPoint"):
                label = nav_point.find("ncx:navLabel/ncx:text", _NS)
                content = nav_point.find("ncx:content", _NS)
                if label is not None and content is not None and label.text:
                    titles.setdefault(
                        _resolve(ncx_dir, content.get("src", "")),
                        _normalize_spaces(label.text),
                    )
    except (KeyError, OSError, ET.ParseError):  # table des matières cassée : non bloquant
        return titles
    return titles


def extract_book(epub_path: str | Path) -> tuple[str, list[Chapter]]:
    """(texte aplati, chapitres avec offsets). Chapitres = [] si un seul document utile."""
    try:
        z = zipfile.ZipFile(str(epub_path))
    except (OSError, zipfile.BadZipFile) as exc:
        raise EpubError(f"EPUB illisible : {exc}") from exc

    with z:
        try:
            container = ET.fromstring(z.read("META-INF/container.xml"))
            rootfile = container.find(".//cnt:rootfile", _NS)
            opf_path = rootfile.get("full-path")  # type: ignore[union-attr]
            opf = ET.fromstring(z.read(opf_path))
        except (KeyError, AttributeError, ET.ParseError) as exc:
            raise EpubError(f"Structure EPUB invalide : {exc}") from exc

        opf_dir = posixpath.dirname(opf_path)
        manifest = {
            item.get("id"): item
            for item in opf.findall(".//opf:manifest/opf:item", _NS)
            if item.get("id")
        }
        spine_ids = [ref.get("idref") for ref in opf.findall(".//opf:spine/opf:itemref", _NS)]
        toc = _toc_titles(z, manifest, opf_dir)

        chapters: list[Chapter] = []
        parts: list[str] = []
        offset = 0
        for idref in spine_ids:
            item = manifest.get(idref or "")
            if item is None or item.get("media-type") not in _XHTML_TYPES:
                continue
            doc_path = _resolve(opf_dir, item.get("href", ""))
            try:
                html = z.read(doc_path).decode("utf-8", "replace")
            except KeyError:
                continue
            text, heading = _doc_text(html)
            if len(text) < MIN_DOC_CHARS:
                continue
            title = toc.get(doc_path) or heading or f"Chapitre {len(chapters) + 1}"
            chapters.append(Chapter(title=title[:80], offset=offset))
            parts.append(text)
            offset += len(text) + 1  # +1 : espace de jointure

    if not parts:
        raise EpubError("EPUB sans texte exploitable.")
    text = " ".join(parts)
    if len(chapters) < 2:
        return text, []
    return text, chapters
