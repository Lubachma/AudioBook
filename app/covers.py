"""Couverture des livres : jaquette EPUB ou rendu de la 1re page du PDF.

Best-effort : un échec d'extraction ne bloque jamais le livre. La couverture est
normalisée en JPEG ≤ 600×900 dans data/covers/<id>.jpg — utilisée par l'UI, par
l'écran verrouillé (Media Session) et incrustée dans le M4B (pochette).
"""

from __future__ import annotations

import io
import posixpath
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

from .config import settings

COVER_MAX = (600, 900)
_OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}


def cover_path(job_id: str) -> Path:
    return settings.covers_dir / f"{job_id}.jpg"


def extract_cover(job_id: str, source: Path, source_type: str) -> Path | None:
    try:
        image = _epub_cover(source) if source_type == "epub" else _pdf_cover(source)
        if image is None:
            return None
        image = image.convert("RGB")
        image.thumbnail(COVER_MAX)
        out = cover_path(job_id)
        out.parent.mkdir(parents=True, exist_ok=True)
        image.save(out, "JPEG", quality=82)
        return out
    except Exception as exc:  # noqa: BLE001 - la couverture est un bonus, jamais bloquante
        print(f"Couverture ignorée pour {job_id} : {exc}")
        return None


def _pdf_cover(path: Path):
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    try:
        if len(doc) == 0:
            return None
        page = doc[0]
        scale = max(1.0, COVER_MAX[0] / max(1.0, page.get_width()))
        return page.render(scale=scale).to_pil()
    finally:
        doc.close()


def _resolve(base_dir: str, href: str) -> str:
    return posixpath.normpath(posixpath.join(base_dir, unquote(urlparse(href).path)))


def _epub_cover(path: Path):
    from PIL import Image

    with zipfile.ZipFile(path) as z:
        container = ET.fromstring(z.read("META-INF/container.xml"))
        rootfile = container.find(
            ".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile"
        )
        if rootfile is None:
            return None
        opf_path = rootfile.get("full-path", "")
        opf = ET.fromstring(z.read(opf_path))
        opf_dir = posixpath.dirname(opf_path)
        items = opf.findall(".//opf:manifest/opf:item", _OPF_NS)

        candidate = None
        # EPUB 3 : <item properties="cover-image">
        for item in items:
            if "cover-image" in (item.get("properties") or "").split():
                candidate = item
                break
        # EPUB 2 : <meta name="cover" content="id-de-l-item">
        if candidate is None:
            meta = next(
                (m for m in opf.iter() if m.tag.endswith("meta") and m.get("name") == "cover"),
                None,
            )
            if meta is not None:
                wanted = meta.get("content", "")
                candidate = next((i for i in items if i.get("id") == wanted), None)
        # Repli : premier item image dont l'id/href évoque une couverture
        if candidate is None:
            candidate = next(
                (
                    i
                    for i in items
                    if (i.get("media-type") or "").startswith("image/")
                    and "cover" in ((i.get("id") or "") + (i.get("href") or "")).lower()
                ),
                None,
            )
        if candidate is None:
            return None
        data = z.read(_resolve(opf_dir, candidate.get("href", "")))
        return Image.open(io.BytesIO(data))
