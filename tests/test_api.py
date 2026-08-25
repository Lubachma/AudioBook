"""Tests d'intégration de l'API : moteurs TTS et ffmpeg sont mockés."""

import pytest
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from app import engines, jobs, main
from app.config import settings
from app.engines import TTSError
from app.main import app

from .conftest import make_epub


@pytest.fixture()
def client(tmp_path, monkeypatch, fake_engine):
    # Données isolées dans un répertoire temporaire
    settings.data_dir = tmp_path / "data"
    settings.ensure_dirs()
    settings.chunk_max_chars = 4000
    monkeypatch.setattr(settings, "default_engine", "fake")
    monkeypatch.setattr(main, "_voices_cache", {})
    jobs.init_db()  # le thread worker persiste entre les tests et ne le fait qu'une fois

    # Traitement synchrone des jobs pour des tests déterministes
    def run_now(job_id, action):
        if action == "extract":
            jobs.run_extraction(job_id)
        elif action == "convert":
            jobs.run_conversion(job_id)

    monkeypatch.setattr(jobs, "enqueue", run_now)

    # Faux ffmpeg : concaténation binaire simple + M4B factice
    def fake_merge(chunk_dir, ext, mp3_out, m4b_out, **kw):
        data = b"".join(f.read_bytes() for f in sorted(chunk_dir.glob(f"chunk_*.{ext}")))
        mp3_out.write_bytes(data)
        m4b_out.write_bytes(b"M4B" + data)

    monkeypatch.setattr(jobs.audio, "merge_book", fake_merge)

    with TestClient(app) as c:
        yield c


def _make_pdf(path, text="Bonjour le monde. Ceci est un livre de test avec assez de texte pour passer le seuil."):
    c = canvas.Canvas(str(path), pagesize=LETTER)
    c.drawString(72, 700, text)
    c.showPage()
    c.save()
    return path


def test_config_endpoint(client):
    cfg = client.get("/api/config").json()
    assert cfg["default_engine"] == "fake"
    assert "monthly_quota_chars" in cfg
    names = [e["name"] for e in cfg["engines"]]
    assert {"qwen3", "kyutai", "elevenlabs", "fake"} <= set(names)
    fake = next(e for e in cfg["engines"] if e["name"] == "fake")
    assert fake["available"] is True
    assert fake["default_voice"] == "fv1"


def test_full_cycle_upload_convert_listen_delete(client, tmp_path):
    pdf = _make_pdf(tmp_path / "livre.pdf")

    with pdf.open("rb") as f:
        resp = client.post("/api/books", files={"file": ("livre.pdf", f, "application/pdf")}, data={"language": "fr"})
    assert resp.status_code == 201
    job_id = resp.json()["id"]

    # L'extraction (synchrone en test) a rempli le comptage de caractères
    books = client.get("/api/books").json()
    book = next(b for b in books if b["id"] == job_id)
    assert book["status"] == "extracted"
    assert book["char_count"] > 0
    assert book["source_type"] == "pdf"

    # Conversion (TTS mockée via le faux moteur)
    resp = client.post(f"/api/books/{job_id}/convert")
    assert resp.status_code == 200
    book = client.get("/api/books").json()[0]
    assert book["status"] == "done"
    assert book["total_chunks"] == book["done_chunks"] >= 1
    assert book["has_m4b"] is True

    # Streaming audio MP3 + téléchargement M4B
    audio = client.get(f"/api/books/{job_id}/audio")
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/mpeg"
    assert audio.content.startswith(b"FAKEMP3")

    m4b = client.get(f"/api/books/{job_id}/audio.m4b")
    assert m4b.status_code == 200
    assert m4b.content.startswith(b"M4B")

    # Suppression
    assert client.delete(f"/api/books/{job_id}").status_code == 204
    assert client.get(f"/api/books/{job_id}/audio").status_code == 404


def test_epub_upload_and_chapters(client, tmp_path):
    epub = make_epub(
        tmp_path / "livre.epub",
        [
            ("Chapitre premier", "Il était une fois un test qui voulait des chapitres. " * 3),
            ("Chapitre second", "La suite du livre continue ici avec encore du texte. " * 3),
        ],
    )
    with epub.open("rb") as f:
        resp = client.post(
            "/api/books", files={"file": ("livre.epub", f, "application/epub+zip")}, data={"language": "fr"}
        )
    assert resp.status_code == 201
    job_id = resp.json()["id"]

    book = next(b for b in client.get("/api/books").json() if b["id"] == job_id)
    assert book["status"] == "extracted"
    assert book["source_type"] == "epub"

    from app.chapters import load_chapters

    chapters = load_chapters(jobs.chapters_path(job_id))
    assert [c.title for c in chapters] == ["Chapitre premier", "Chapitre second"]


def test_rejects_unsupported_extension(client, tmp_path):
    txt = tmp_path / "doc.txt"
    txt.write_text("pas un livre")
    with txt.open("rb") as f:
        resp = client.post("/api/books", files={"file": ("doc.txt", f, "text/plain")})
    assert resp.status_code == 400


def test_convert_requires_extracted_status(client):
    resp = client.post("/api/books/inconnu/convert")
    assert resp.status_code == 404


def test_convert_allowed_from_error_status(client):
    """Un job en erreur (ex : ffmpeg) avec texte extrait peut être relancé."""
    job_id = jobs.create_job(title="livre", language="fr", engine="fake")
    jobs.text_path(job_id).write_text("Du texte à convertir.", encoding="utf-8")
    jobs.update_job(job_id, status="error", char_count=21, error="panne")

    resp = client.post(f"/api/books/{job_id}/convert")
    assert resp.status_code == 200
    assert jobs.get_job(job_id)["status"] == "done"


def test_convert_error_without_extracted_text_rejected(client):
    """Job en erreur SANS texte extrait (ex : PDF scanné) -> 409, il faut ré-uploader."""
    job_id = jobs.create_job(title="scan", language="fr")
    jobs.update_job(job_id, status="error", error="PDF scanné")

    resp = client.post(f"/api/books/{job_id}/convert")
    assert resp.status_code == 409


def test_convert_legacy_edge_book_rejected_with_message(client):
    """Les livres historiques edge-tts restent lisibles mais pas re-convertibles."""
    job_id = jobs.create_job(title="ancien", language="fr", engine="edge")
    jobs.text_path(job_id).write_text("Du texte.", encoding="utf-8")
    jobs.update_job(job_id, status="extracted", char_count=9)

    resp = client.post(f"/api/books/{job_id}/convert")
    assert resp.status_code == 409
    assert "edge-tts" in resp.json()["detail"]


def test_convert_unavailable_engine_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")
    job_id = jobs.create_job(title="livre", language="fr", engine="elevenlabs")
    jobs.text_path(job_id).write_text("Du texte.", encoding="utf-8")
    jobs.update_job(job_id, status="extracted", char_count=9)

    resp = client.post(f"/api/books/{job_id}/convert")
    assert resp.status_code == 409
    assert "indisponible" in resp.json()["detail"]


def test_index_served(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Audiobooks" in resp.text


def test_voices_endpoint_lists_engine_voices(client):
    data = client.get("/api/voices?engine=fake").json()
    assert data["voices"][0] == {
        "voice_id": "fv1",
        "name": "Fausse voix",
        "category": "test",
        "language": "fr",
    }


def test_voices_endpoint_elevenlabs_without_key_returns_empty(client, monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")
    data = client.get("/api/voices?engine=elevenlabs").json()
    assert data["voices"] == []


def test_voices_endpoint_cloud_failure_returns_empty(client, monkeypatch):
    def boom():
        raise TTSError("panne")

    monkeypatch.setattr(engines.get_engine("elevenlabs"), "list_voices", boom)
    monkeypatch.setattr(settings, "elevenlabs_api_key", "cle-test")
    data = client.get("/api/voices?engine=elevenlabs").json()
    assert data["voices"] == []


def test_upload_stores_chosen_voice_and_label(client, tmp_path):
    pdf = _make_pdf(tmp_path / "livre2.pdf")
    with pdf.open("rb") as f:
        resp = client.post(
            "/api/books",
            files={"file": ("livre2.pdf", f, "application/pdf")},
            data={"language": "en", "voice_id": "fv2", "engine": "fake"},
        )
    assert resp.status_code == 201
    book = client.get("/api/books").json()[0]
    assert book["voice_id"] == "fv2"
    assert book["voice_label"] == "Fake voice"
    assert book["engine"] == "fake"


def test_upload_with_removed_edge_engine_rejected(client, tmp_path):
    pdf = _make_pdf(tmp_path / "livre3.pdf")
    with pdf.open("rb") as f:
        resp = client.post(
            "/api/books",
            files={"file": ("livre3.pdf", f, "application/pdf")},
            data={"language": "fr", "engine": "edge"},
        )
    assert resp.status_code == 400


def test_convert_sets_queued_status_before_enqueue(client, monkeypatch):
    """Le statut transitoire « queued » empêche un second clic de doubler le livre."""
    job_id = jobs.create_job(title="livre", language="fr", engine="fake")
    jobs.text_path(job_id).write_text("Du texte.", encoding="utf-8")
    jobs.update_job(job_id, status="extracted", char_count=9)

    queued = []
    monkeypatch.setattr(jobs, "enqueue", lambda jid, action: queued.append((jid, action)))

    resp = client.post(f"/api/books/{job_id}/convert")
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    assert jobs.get_job(job_id)["status"] == "queued"  # posé avant même l'exécution
    assert queued == [(job_id, "convert")]

    # Un second clic pendant que le job attend dans la file est refusé
    resp2 = client.post(f"/api/books/{job_id}/convert")
    assert resp2.status_code == 409


def test_reconvert_with_new_voice(client, tmp_path, monkeypatch):
    """Un livre terminé peut être re-synthétisé avec un autre moteur/voix,
    sans ré-upload : le texte extrait est réutilisé."""
    pdf = _make_pdf(tmp_path / "livre9.pdf")
    with pdf.open("rb") as f:
        job_id = client.post(
            "/api/books", files={"file": ("livre9.pdf", f, "application/pdf")},
            data={"language": "fr", "engine": "fake", "voice_id": "fv1"},
        ).json()["id"]
    client.post(f"/api/books/{job_id}/convert")
    assert jobs.get_job(job_id)["status"] == "done"

    resp = client.post(f"/api/books/{job_id}/reconvert", json={"engine": "fake", "voice_id": "fv2"})
    assert resp.status_code == 200
    job = jobs.get_job(job_id)
    assert job["status"] == "done"  # enqueue synchrone en test : reconverti dans la foulée
    assert job["voice_id"] == "fv2"
    assert job["voice_label"] == "Fake voice"


def test_reconvert_rejected_while_converting(client):
    job_id = jobs.create_job(title="livre", language="fr", engine="fake")
    jobs.text_path(job_id).write_text("Du texte.", encoding="utf-8")
    jobs.update_job(job_id, status="converting")
    resp = client.post(f"/api/books/{job_id}/reconvert", json={"engine": "fake"})
    assert resp.status_code == 409


def test_reconvert_unknown_engine_rejected(client, tmp_path):
    job_id = jobs.create_job(title="livre", language="fr", engine="fake")
    jobs.text_path(job_id).write_text("Du texte.", encoding="utf-8")
    jobs.update_job(job_id, status="done")
    resp = client.post(f"/api/books/{job_id}/reconvert", json={"engine": "edge"})
    assert resp.status_code == 400


def test_second_convert_after_done_rejected(client, tmp_path):
    pdf = _make_pdf(tmp_path / "livre4.pdf")
    with pdf.open("rb") as f:
        job_id = client.post(
            "/api/books", files={"file": ("livre4.pdf", f, "application/pdf")}, data={"language": "fr"}
        ).json()["id"]
    assert client.post(f"/api/books/{job_id}/convert").status_code == 200
    assert jobs.get_job(job_id)["status"] == "done"
    assert client.post(f"/api/books/{job_id}/convert").status_code == 409


def test_delete_during_conversion_rejected(client):
    job_id = jobs.create_job(title="livre", language="fr")
    jobs.update_job(job_id, status="converting")
    assert client.delete(f"/api/books/{job_id}").status_code == 409
    assert jobs.get_job(job_id) is not None  # toujours là


def test_invalid_engine_rejected_on_upload(client, tmp_path):
    pdf = _make_pdf(tmp_path / "livre5.pdf")
    with pdf.open("rb") as f:
        resp = client.post(
            "/api/books",
            files={"file": ("livre5.pdf", f, "application/pdf")},
            data={"language": "fr", "engine": "Fake"},  # casse différente -> rejet
        )
    assert resp.status_code == 400


def test_invalid_engine_rejected_on_voices(client):
    assert client.get("/api/voices?engine=Edge").status_code == 400


# ------------------------------------------------ annulation et pré-écoute

def test_cancel_queued_book_is_immediate(client, monkeypatch):
    job_id = jobs.create_job(title="livre", language="fr", engine="fake")
    jobs.text_path(job_id).write_text("Du texte.", encoding="utf-8")
    jobs.update_job(job_id, status="queued")

    resp = client.post(f"/api/books/{job_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "extracted"
    assert jobs.get_job(job_id)["status"] == "extracted"

    # L'item de file périmé arrive plus tard : il ne doit rien convertir
    jobs.run_conversion(job_id)
    assert jobs.get_job(job_id)["status"] == "extracted"


def test_cancel_converting_book_flags_worker(client):
    job_id = jobs.create_job(title="livre", language="fr", engine="fake")
    jobs.update_job(job_id, status="converting")

    resp = client.post(f"/api/books/{job_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelling"


def test_cancel_rejected_when_nothing_running(client):
    job_id = jobs.create_job(title="livre", language="fr")
    jobs.update_job(job_id, status="done")
    assert client.post(f"/api/books/{job_id}/cancel").status_code == 409
    assert client.post("/api/books/inconnu/cancel").status_code == 404


def test_live_chunk_streaming_during_conversion(client):
    job_id = jobs.create_job(title="livre", language="fr", engine="fake")
    jobs.update_job(job_id, status="converting")
    directory = jobs.chunk_dir(job_id)
    directory.mkdir(parents=True)
    (directory / "chunk_0001.wav").write_bytes(b"RIFFsegment1")

    ok = client.get(f"/api/books/{job_id}/chunks/1")
    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("audio/wav")
    assert ok.content == b"RIFFsegment1"

    assert client.get(f"/api/books/{job_id}/chunks/2").status_code == 404
    assert client.get("/api/books/inconnu/chunks/1").status_code == 404


# --------------------------------------- position, chapitres et couverture

def test_position_roundtrip_across_devices(client, tmp_path):
    pdf = _make_pdf(tmp_path / "livre6.pdf")
    with pdf.open("rb") as f:
        job_id = client.post(
            "/api/books", files={"file": ("livre6.pdf", f, "application/pdf")}, data={"language": "fr"}
        ).json()["id"]

    assert client.put(f"/api/books/{job_id}/position", json={"seconds": 123.4}).status_code == 204
    book = next(b for b in client.get("/api/books").json() if b["id"] == job_id)
    assert book["position_seconds"] == pytest.approx(123.4)

    # Valeur négative ramenée à zéro, livre inconnu -> 404
    client.put(f"/api/books/{job_id}/position", json={"seconds": -5})
    book = next(b for b in client.get("/api/books").json() if b["id"] == job_id)
    assert book["position_seconds"] == 0
    assert client.put("/api/books/inconnu/position", json={"seconds": 1}).status_code == 404


def test_chapters_endpoint_empty_without_m4b(client):
    job_id = jobs.create_job(title="livre", language="fr")
    assert client.get(f"/api/books/{job_id}/chapters").json() == {"chapters": []}
    assert client.get("/api/books/inconnu/chapters").json() == {"chapters": []}


def test_chapters_endpoint_reads_m4b(client, tmp_path, monkeypatch):
    pdf = _make_pdf(tmp_path / "livre7.pdf")
    with pdf.open("rb") as f:
        job_id = client.post(
            "/api/books", files={"file": ("livre7.pdf", f, "application/pdf")}, data={"language": "fr"}
        ).json()["id"]
    client.post(f"/api/books/{job_id}/convert")

    fake_chapters = [{"title": "Un", "start": 0.0, "end": 10.0}]
    monkeypatch.setattr(main.audio, "probe_chapters", lambda path: fake_chapters)
    monkeypatch.setattr(main, "_chapters_cache", {})

    assert client.get(f"/api/books/{job_id}/chapters").json() == {"chapters": fake_chapters}


def test_cover_endpoint(client, tmp_path):
    pdf = _make_pdf(tmp_path / "livre8.pdf")
    with pdf.open("rb") as f:
        job_id = client.post(
            "/api/books", files={"file": ("livre8.pdf", f, "application/pdf")}, data={"language": "fr"}
        ).json()["id"]

    # L'extraction (synchrone en test) a rendu la 1re page du PDF en couverture
    book = next(b for b in client.get("/api/books").json() if b["id"] == job_id)
    assert book["has_cover"] is True
    resp = client.get(f"/api/books/{job_id}/cover")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"

    assert client.get("/api/books/inconnu/cover").status_code == 404


# --------------------------------------------------------- banc d'essai voix

def test_previews_flow_and_default_voice(client, monkeypatch, fake_engine):
    # Génération synchrone : on court-circuite la file comme pour les jobs
    from app import previews

    monkeypatch.setattr(
        jobs, "enqueue_preview", lambda e, v, lang: previews.run_preview(
            {"engine": e, "voice_id": v, "language": lang}
        )
    )

    listing = client.get("/api/previews?engine=fake&language=fr").json()
    assert [v["voice_id"] for v in listing["voices"]] == ["fv1"]  # fv2 est en anglais
    assert listing["voices"][0]["status"] == "missing"

    resp = client.post("/api/previews", json={"engine": "fake", "language": "fr", "all": True})
    assert resp.status_code == 202
    assert resp.json()["queued"] == 1

    listing = client.get("/api/previews?engine=fake&language=fr").json()
    assert listing["voices"][0]["status"] == "ready"

    audio = client.get("/api/previews/audio?engine=fake&voice_id=fv1&language=fr")
    assert audio.status_code == 200
    assert audio.content.startswith(b"FAKEMP3")

    # Choix de la voix par défaut -> persisté et visible dans /api/config
    resp = client.put("/api/settings", json={"engine": "fake", "voice_id": "fv1"})
    assert resp.status_code == 200
    cfg = resp.json()
    assert cfg["default_engine"] == "fake"
    fake_cfg = next(e for e in cfg["engines"] if e["name"] == "fake")
    assert fake_cfg["default_voice"] == "fv1"


def test_previews_unavailable_engine_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")
    resp = client.post("/api/previews", json={"engine": "elevenlabs", "language": "fr", "all": True})
    assert resp.status_code == 409
