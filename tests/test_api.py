"""Tests d'intégration de l'API : ElevenLabs et ffmpeg sont mockés."""

import pytest
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from app import jobs
from app.config import settings
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Données isolées dans un répertoire temporaire
    settings.data_dir = tmp_path / "data"
    settings.ensure_dirs()
    settings.chunk_max_chars = 4000
    monkeypatch.setattr(settings, "default_engine", "elevenlabs")
    jobs.init_db()  # le thread worker persiste entre les tests et ne le fait qu'une fois

    # Traitement synchrone des jobs pour des tests déterministes
    def run_now(job_id, action):
        if action == "extract":
            jobs.run_extraction(job_id)
        elif action == "convert":
            jobs.run_conversion(job_id)

    monkeypatch.setattr(jobs, "enqueue", run_now)
    # Fausses réponses TTS : chaque chunk devient un petit fichier binaire
    monkeypatch.setattr(
        jobs,
        "synthesize_with_retry",
        lambda text, out_path, **kw: out_path.write_bytes(b"FAKEMP3" + text[:8].encode()),
    )
    # Faux ffmpeg : concaténation binaire simple
    def fake_merge(chunk_dir, out_path):
        data = b"".join(f.read_bytes() for f in sorted(chunk_dir.glob("chunk_*.mp3")))
        out_path.write_bytes(data)

    monkeypatch.setattr(jobs, "merge_chunks", fake_merge)

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
    assert cfg["model_id"] == "eleven_multilingual_v2"
    assert "monthly_quota_chars" in cfg


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

    # Conversion (TTS mockée)
    resp = client.post(f"/api/books/{job_id}/convert")
    assert resp.status_code == 200
    book = client.get("/api/books").json()[0]
    assert book["status"] == "done"
    assert book["total_chunks"] == book["done_chunks"] >= 1

    # Streaming audio
    audio = client.get(f"/api/books/{job_id}/audio")
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/mpeg"
    assert audio.content.startswith(b"FAKEMP3")

    # Suppression
    assert client.delete(f"/api/books/{job_id}").status_code == 204
    assert client.get(f"/api/books/{job_id}/audio").status_code == 404


def test_rejects_non_pdf(client, tmp_path):
    txt = tmp_path / "doc.txt"
    txt.write_text("pas un pdf")
    with txt.open("rb") as f:
        resp = client.post("/api/books", files={"file": ("doc.txt", f, "text/plain")})
    assert resp.status_code == 400


def test_convert_requires_extracted_status(client):
    resp = client.post("/api/books/inconnu/convert")
    assert resp.status_code == 404


def test_convert_allowed_from_error_status(client):
    """Un job en erreur (ex : quota ou ffmpeg) avec texte extrait peut être relancé."""
    job_id = jobs.create_job(title="livre", language="fr")
    jobs.text_path(job_id).write_text("Du texte à convertir.", encoding="utf-8")
    jobs.update_job(job_id, status="error", char_count=21, error="quota atteint")

    resp = client.post(f"/api/books/{job_id}/convert")
    assert resp.status_code == 200
    assert jobs.get_job(job_id)["status"] == "done"


def test_convert_error_without_extracted_text_rejected(client):
    """Job en erreur SANS texte extrait (ex : PDF scanné) -> 409, il faut ré-uploader."""
    job_id = jobs.create_job(title="scan", language="fr")
    jobs.update_job(job_id, status="error", error="PDF scanné")

    resp = client.post(f"/api/books/{job_id}/convert")
    assert resp.status_code == 409


def test_index_served(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Livres audio" in resp.text


def test_voices_endpoint_lists_account_voices(client, monkeypatch):
    from app import main

    monkeypatch.setattr(main, "_voices_cache", {})
    monkeypatch.setattr(settings, "elevenlabs_api_key", "cle-test")
    monkeypatch.setattr(
        main,
        "list_voices",
        lambda key: [{"voice_id": "v1", "name": "Alice", "category": "premade"}],
    )

    data = client.get("/api/voices").json()
    assert data["voices"] == [{"voice_id": "v1", "name": "Alice", "category": "premade"}]


def test_voices_endpoint_without_key_returns_empty(client, monkeypatch):
    from app import main

    monkeypatch.setattr(main, "_voices_cache", {})
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")

    data = client.get("/api/voices").json()
    assert data["voices"] == []


def test_voices_endpoint_elevenlabs_failure_returns_empty(client, monkeypatch):
    from app import main, tts

    monkeypatch.setattr(main, "_voices_cache", {})
    monkeypatch.setattr(settings, "elevenlabs_api_key", "cle-test")

    def boom(key):
        raise tts.TTSError("panne")

    monkeypatch.setattr(main, "list_voices", boom)
    data = client.get("/api/voices").json()
    assert data["voices"] == []


def test_upload_stores_chosen_voice(client, tmp_path):
    pdf = _make_pdf(tmp_path / "livre2.pdf")
    with pdf.open("rb") as f:
        resp = client.post(
            "/api/books",
            files={"file": ("livre2.pdf", f, "application/pdf")},
            data={"language": "en", "voice_id": "voix-choisie"},
        )
    assert resp.status_code == 201
    book = client.get("/api/books").json()[0]
    assert book["voice_id"] == "voix-choisie"


def test_voices_endpoint_edge_engine(client, monkeypatch):
    from app import main

    monkeypatch.setattr(main, "_voices_cache", {})
    monkeypatch.setattr(
        main,
        "list_edge_voices",
        lambda: [{"voice_id": "fr-FR-DeniseNeural", "name": "Denise (fr-FR, F)", "category": "edge"}],
    )

    data = client.get("/api/voices?engine=edge").json()
    assert data["voices"][0]["voice_id"] == "fr-FR-DeniseNeural"


def test_upload_stores_engine(client, tmp_path):
    pdf = _make_pdf(tmp_path / "livre3.pdf")
    with pdf.open("rb") as f:
        resp = client.post(
            "/api/books",
            files={"file": ("livre3.pdf", f, "application/pdf")},
            data={"language": "fr", "voice_id": "fr-FR-DeniseNeural", "engine": "edge"},
        )
    assert resp.status_code == 201
    book = client.get("/api/books").json()[0]
    assert book["engine"] == "edge"


def test_convert_sets_converting_status_before_enqueue(client, monkeypatch):
    """Le statut transitoire empêche un second clic de re-facturer le livre."""
    job_id = jobs.create_job(title="livre", language="fr", engine="elevenlabs")
    jobs.text_path(job_id).write_text("Du texte.", encoding="utf-8")
    jobs.update_job(job_id, status="extracted", char_count=9)

    queued = []
    monkeypatch.setattr(jobs, "enqueue", lambda jid, action: queued.append((jid, action)))

    resp = client.post(f"/api/books/{job_id}/convert")
    assert resp.status_code == 200
    assert jobs.get_job(job_id)["status"] == "converting"  # posé avant même l'exécution
    assert queued == [(job_id, "convert")]

    # Un second clic pendant que le job attend dans la file est refusé
    resp2 = client.post(f"/api/books/{job_id}/convert")
    assert resp2.status_code == 409


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
            data={"language": "fr", "engine": "Edge"},  # typo -> rejet, pas de facturation ElevenLabs
        )
    assert resp.status_code == 400


def test_invalid_engine_rejected_on_voices(client):
    assert client.get("/api/voices?engine=Edge").status_code == 400
