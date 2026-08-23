"""Tests du client ElevenLabs : liste des voix du compte."""

import httpx
import pytest

from app.tts import AuthError, TTSError, list_voices


def test_list_voices_returns_simplified_list():
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

    voices = list_voices("ma-cle", transport=httpx.MockTransport(handler))

    assert voices == [
        {"voice_id": "v1", "name": "Alice", "category": "premade"},
        {"voice_id": "v2", "name": "Ma Voix", "category": "cloned"},
    ]


def test_list_voices_without_key_raises():
    with pytest.raises(AuthError):
        list_voices("")


def test_list_voices_bad_key_raises():
    transport = httpx.MockTransport(lambda req: httpx.Response(401, json={"detail": "bad key"}))
    with pytest.raises(AuthError):
        list_voices("mauvaise-cle", transport=transport)


def test_list_voices_server_error_raises():
    transport = httpx.MockTransport(lambda req: httpx.Response(500, text="boom"))
    with pytest.raises(TTSError):
        list_voices("ma-cle", transport=transport)
