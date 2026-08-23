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


# ------------------------------------------------------------------ edge-tts

import asyncio

from app import tts


class _FakeCommunicate:
    """Simule edge_tts.Communicate : écrit un fichier à .save()."""

    calls = []

    def __init__(self, text, voice):
        self.text = text
        self.voice = voice
        _FakeCommunicate.calls.append((text, voice))

    async def save(self, path):
        with open(path, "wb") as f:
            f.write(b"EDGE" + self.text[:8].encode())


def test_synthesize_edge_chunk_writes_file(tmp_path, monkeypatch):
    import edge_tts

    monkeypatch.setattr(edge_tts, "Communicate", _FakeCommunicate)
    out = tmp_path / "chunk.mp3"

    tts.synthesize_edge_chunk("Bonjour le monde", out, voice="fr-FR-DeniseNeural")

    assert out.read_bytes().startswith(b"EDGE")
    assert _FakeCommunicate.calls[-1] == ("Bonjour le monde", "fr-FR-DeniseNeural")


def test_edge_retry_then_success(tmp_path, monkeypatch):
    import edge_tts

    attempts = []

    class FlakyCommunicate(_FakeCommunicate):
        def __init__(self, text, voice):
            super().__init__(text, voice)
            attempts.append(1)

        async def save(self, path):
            if len(attempts) < 2:
                raise RuntimeError("réseau capricieux")
            await super().save(path)

    monkeypatch.setattr(edge_tts, "Communicate", FlakyCommunicate)
    out = tmp_path / "chunk.mp3"

    tts.synthesize_edge_with_retry("texte", out, voice="fr-FR-DeniseNeural", base_delay=0)

    assert out.exists()
    assert len(attempts) == 2


def test_list_edge_voices_filters_and_formats(monkeypatch):
    import edge_tts

    async def fake_list():
        return [
            {"ShortName": "fr-FR-DeniseNeural", "Locale": "fr-FR", "Gender": "Female"},
            {"ShortName": "fr-FR-HenriNeural", "Locale": "fr-FR", "Gender": "Male"},
            {"ShortName": "en-US-JennyNeural", "Locale": "en-US", "Gender": "Female"},
            {"ShortName": "de-DE-KatjaNeural", "Locale": "de-DE", "Gender": "Female"},
        ]

    monkeypatch.setattr(edge_tts, "list_voices", fake_list)

    voices = tts.list_edge_voices()

    assert [v["voice_id"] for v in voices] == [
        "fr-FR-DeniseNeural",
        "fr-FR-HenriNeural",
        "en-US-JennyNeural",
    ]
    assert voices[0]["name"] == "Denise (fr-FR, F)"
    assert voices[1]["name"] == "Henri (fr-FR, M)"
