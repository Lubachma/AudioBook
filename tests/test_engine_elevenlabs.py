"""Tests du moteur ElevenLabs (httpx mocké via MockTransport)."""

import httpx
import pytest

from app.config import settings
from app.engines import AuthError, QuotaExceededError, TTSError
from app.engines.elevenlabs import ElevenLabsEngine, fetch_account_voices, synthesize_chunk


def _kwargs(transport):
    return dict(
        api_key="cle",
        voice_id="v1",
        model_id="eleven_multilingual_v2",
        transport=transport,
    )


def test_fetch_account_voices_returns_simplified_list():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["xi-api-key"] == "ma-cle"
        return httpx.Response(
            200,
            json={
                "voices": [
                    {"voice_id": "v1", "name": "Alice", "category": "premade", "labels": {"accent": "fr"}},
                    {"voice_id": "v2", "name": "Ma Voix", "category": "cloned"},
                ]
            },
        )

    voices = fetch_account_voices("ma-cle", transport=httpx.MockTransport(handler))

    assert voices == [
        {"voice_id": "v1", "name": "Alice", "category": "premade"},
        {"voice_id": "v2", "name": "Ma Voix", "category": "cloned"},
    ]


def test_fetch_account_voices_without_key_raises():
    with pytest.raises(AuthError):
        fetch_account_voices("")


def test_fetch_account_voices_bad_key_raises():
    transport = httpx.MockTransport(lambda req: httpx.Response(401, json={"detail": "bad key"}))
    with pytest.raises(AuthError):
        fetch_account_voices("mauvaise-cle", transport=transport)


def test_fetch_account_voices_server_error_raises():
    transport = httpx.MockTransport(lambda req: httpx.Response(500, text="boom"))
    with pytest.raises(TTSError):
        fetch_account_voices("ma-cle", transport=transport)


def test_synthesize_chunk_streams_to_file(tmp_path):
    def handler(request):
        assert request.url.path == "/v1/text-to-speech/v1"
        return httpx.Response(200, content=b"ID3AUDIODATA")

    out = tmp_path / "c.mp3"
    synthesize_chunk("bonjour", out, **_kwargs(httpx.MockTransport(handler)))
    assert out.read_bytes() == b"ID3AUDIODATA"


# ------------------------------------------------------ via l'interface Engine

@pytest.fixture()
def engine(monkeypatch):
    eng = ElevenLabsEngine()
    monkeypatch.setattr(settings, "elevenlabs_api_key", "cle")
    return eng


def test_engine_quota_error_not_retried(tmp_path, engine):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, json={"detail": {"status": "quota_exceeded"}})

    engine.transport = httpx.MockTransport(handler)
    with pytest.raises(QuotaExceededError):
        engine.synthesize_with_retry("texte", tmp_path / "c.mp3", voice_id="v1", language="fr", base_delay=0)
    assert len(calls) == 1  # jamais de retry sur un dépassement de quota


def test_engine_auth_error_not_retried(tmp_path, engine):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, json={"detail": "invalid key"})

    engine.transport = httpx.MockTransport(handler)
    with pytest.raises(AuthError):
        engine.synthesize_with_retry("texte", tmp_path / "c.mp3", voice_id="v1", language="fr", base_delay=0)
    assert len(calls) == 1


def test_engine_server_error_retried_then_raises(tmp_path, engine):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500, text="boom")

    engine.transport = httpx.MockTransport(handler)
    with pytest.raises(TTSError):
        engine.synthesize_with_retry("texte", tmp_path / "c.mp3", voice_id="v1", language="fr", base_delay=0)
    assert len(calls) == 3


def test_engine_server_error_then_success(tmp_path, engine):
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 2:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, content=b"AUDIO")

    engine.transport = httpx.MockTransport(handler)
    out = tmp_path / "c.mp3"
    engine.synthesize_with_retry("texte", out, voice_id="v1", language="fr", base_delay=0)
    assert out.read_bytes() == b"AUDIO"
    assert len(calls) == 2


def test_engine_partial_stream_leaves_no_file(tmp_path, engine):
    """Une coupure réseau en plein stream ne doit laisser AUCUN fichier partiel :
    sinon la reprise le croirait complet et ffmpeg assemblerait un MP3 corrompu."""

    def handler(request):
        # Réponse 200 dont le corps lève en cours de lecture
        return httpx.Response(200, content=iter([b"PART", RuntimeError("connexion coupée")]))

    engine.transport = httpx.MockTransport(handler)
    out = tmp_path / "c.mp3"
    with pytest.raises(Exception):
        engine.synthesize("texte", out, voice_id="v1", language="fr")
    assert not out.exists()


def test_engine_language_forwarded(tmp_path, engine):
    seen = {}

    def handler(request):
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(200, content=b"AUDIO")

    engine.transport = httpx.MockTransport(handler)
    engine.synthesize("texte", tmp_path / "c.mp3", voice_id="v1", language="fr")
    assert seen["language_code"] == "fr"


def test_engine_availability_depends_on_key(monkeypatch):
    engine = ElevenLabsEngine()
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")
    assert engine.availability()[0] is False
    monkeypatch.setattr(settings, "elevenlabs_api_key", "cle")
    assert engine.availability() == (True, "")
