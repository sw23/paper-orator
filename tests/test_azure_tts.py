"""Tests for the Azure Speech synthesizer (HTTP is mocked; no network calls)."""

from types import SimpleNamespace
from unittest import mock

import pytest

from paper_orator.providers import azure_tts
from paper_orator.providers.azure_tts import (
    AzureSpeechSynthesizer,
    build_ssml,
    is_batch_compatible_voice,
    split_text,
    voice_locale,
)

CONFIG = {"key": "k", "region": "eastus"}


def _resp(status=200, content=b"MP3", headers=None, text=""):
    return SimpleNamespace(status_code=status, content=content, headers=headers or {}, text=text)


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, headers, data, timeout):
        self.calls.append({"url": url, "headers": headers, "data": data})
        return self.responses.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(azure_tts.time, "sleep", lambda _s: None)


def _patch_session(monkeypatch, responses):
    session = _FakeSession(responses)
    monkeypatch.setattr(azure_tts.requests, "Session", lambda: session)
    return session


# --- helpers -------------------------------------------------------------


def test_batch_compatibility():
    assert is_batch_compatible_voice("en-US-JennyNeural")
    assert not is_batch_compatible_voice("en-US-Harper:MAI-Voice-2.1")
    assert not is_batch_compatible_voice("en-US-Ava:DragonHDLatestNeural")


def test_voice_locale():
    assert voice_locale("en-US-Harper:MAI-Voice-2.1") == "en-US"
    assert voice_locale("de-DE-Conrad:DragonHDOmniLatestNeural") == "de-DE"
    assert voice_locale("weird") == "en-US"


def test_build_ssml_escapes_text():
    ssml = build_ssml("a < b & c", "en-US-Harper:MAI-Voice-2.1")
    assert 'xml:lang="en-US"' in ssml
    assert '<voice name="en-US-Harper:MAI-Voice-2.1">' in ssml
    assert "a &lt; b &amp; c" in ssml


def test_split_text_respects_limit_and_keeps_all_words():
    text = "\n\n".join(
        " ".join(f"Sentence {p}-{i} has several words in it." for i in range(40))
        for p in range(5)
    )
    chunks = split_text(text, max_chars=500)
    assert len(chunks) > 1
    assert all(len(c) <= 500 for c in chunks)
    assert " ".join(" ".join(chunks).split()) == " ".join(text.split())


def test_split_text_handles_unbroken_text():
    chunks = split_text("x" * 1200, max_chars=500)
    assert [len(c) for c in chunks] == [500, 500, 200]


def test_split_text_packs_short_paragraphs():
    assert split_text("One.\n\nTwo.\n\n\nThree.", max_chars=100) == ["One.\n\nTwo.\n\nThree."]
    assert split_text("  \n\n ") == []


# --- chunked real-time synthesis ------------------------------------------


def test_mai_voice_forces_realtime():
    synth = AzureSpeechSynthesizer(CONFIG, voice="en-US-Harper:MAI-Voice-2.1", use_batch=True)
    assert synth.use_batch is False
    synth = AzureSpeechSynthesizer(CONFIG, voice="en-US-JennyNeural", use_batch=True)
    assert synth.use_batch is True


def test_chunked_synthesis_concatenates_segments(tmp_path, monkeypatch):
    session = _patch_session(monkeypatch, [_resp(content=b"AAA"), _resp(content=b"BBB")])
    out = tmp_path / "paper.mp3"
    synth = AzureSpeechSynthesizer(CONFIG)
    synth.max_chunk_chars = 20

    synth.synthesize("First paragraph.\n\nSecond paragraph.", str(out))

    assert out.read_bytes() == b"AAABBB"
    assert len(session.calls) == 2
    call = session.calls[0]
    assert call["url"] == "https://eastus.tts.speech.microsoft.com/cognitiveservices/v1"
    assert call["headers"]["X-Microsoft-OutputFormat"] == "audio-24khz-48kbitrate-mono-mp3"
    assert b"en-US-Harper:MAI-Voice-2.1" in call["data"]
    assert not (tmp_path / "paper.mp3.part").exists()


def test_chunked_synthesis_retries_transient_errors(tmp_path, monkeypatch):
    session = _patch_session(
        monkeypatch,
        [_resp(status=429, headers={"Retry-After": "1"}), _resp(status=503), _resp(content=b"OK")],
    )
    out = tmp_path / "paper.mp3"
    AzureSpeechSynthesizer(CONFIG).synthesize("Hello.", str(out))
    assert out.read_bytes() == b"OK"
    assert len(session.calls) == 3


def test_chunked_synthesis_failure_leaves_no_partial_file(tmp_path, monkeypatch):
    _patch_session(monkeypatch, [_resp(content=b"AAA"), _resp(status=400, text="bad voice")])
    out = tmp_path / "paper.mp3"
    synth = AzureSpeechSynthesizer(CONFIG)
    synth.max_chunk_chars = 20

    with pytest.raises(RuntimeError, match="400 - bad voice"):
        synth.synthesize("First paragraph.\n\nSecond paragraph.", str(out))

    assert not out.exists()
    assert not (tmp_path / "paper.mp3.part").exists()


def test_chunked_synthesis_gives_up_after_max_attempts(tmp_path, monkeypatch):
    session = _patch_session(monkeypatch, [_resp(status=500)] * azure_tts.MAX_ATTEMPTS)
    with pytest.raises(RuntimeError, match="500"):
        AzureSpeechSynthesizer(CONFIG).synthesize("Hello.", str(tmp_path / "p.mp3"))
    assert len(session.calls) == azure_tts.MAX_ATTEMPTS


# --- batch synthesis --------------------------------------------------------


def test_batch_failure_reports_details_and_deletes_job(tmp_path, monkeypatch):
    put = mock.Mock(return_value=_resp(status=201))
    get = mock.Mock(return_value=SimpleNamespace(
        status_code=200,
        json=lambda: {"status": "Failed", "properties": {"error": {"message": "quota"}}},
    ))
    delete = mock.Mock()
    monkeypatch.setattr(azure_tts.requests, "put", put)
    monkeypatch.setattr(azure_tts.requests, "get", get)
    monkeypatch.setattr(azure_tts.requests, "delete", delete)

    synth = AzureSpeechSynthesizer(CONFIG, voice="en-US-JennyNeural", use_batch=True)
    with pytest.raises(RuntimeError, match="quota"):
        synth.synthesize("Hello.", str(tmp_path / "p.mp3"))

    assert "api-version=2024-04-01" in put.call_args.args[0]
    delete.assert_called_once()
