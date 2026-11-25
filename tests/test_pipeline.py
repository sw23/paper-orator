"""Tests for pipeline orchestration (providers are faked; no network calls)."""

import base64

import pytest

from paper_orator import pipeline
from paper_orator.providers import get_provider, register_provider
from paper_orator.providers.base import StorageUploader


def test_raw_text_round_trip(tmp_path):
    figure = tmp_path / "figure_0.png"
    figure.write_bytes(b"PNGDATA")
    raw_text = tmp_path / "raw_text.txt"
    raw_text.write_text(
        "--- Page ---\nHello\n"
        f"--- Figure --- : 0 : {figure}\n"
        "--- Page ---\nWorld\n"
    )

    pages = pipeline._load_raw_text(str(raw_text))
    assert len(pages) == 2
    assert pages[0][0] == "Hello"
    image = pages[0][1]
    assert image["type"] == "image"
    assert base64.b64decode(image["data"]) == b"PNGDATA"
    assert pages[1][0] == "World"


def test_raw_text_missing_figure_skipped(tmp_path):
    raw_text = tmp_path / "raw_text.txt"
    raw_text.write_text(f"--- Page ---\nText\n--- Figure --- : 0 : {tmp_path / 'gone.png'}\n")
    pages = pipeline._load_raw_text(str(raw_text))
    assert all(isinstance(line, str) for line in pages[0])


def test_should_run_stage(tmp_path):
    existing = tmp_path / "out.txt"
    existing.write_text("x")
    assert pipeline._should_run_stage(str(tmp_path / "missing"), "s", False, False)
    assert not pipeline._should_run_stage(str(existing), "s", False, False)
    assert pipeline._should_run_stage(str(existing), "s", True, False)


class _FakeUploader(StorageUploader):
    def __init__(self, config):
        self.fail = config.get("fail", False)
        self.uploaded = []

    def upload(self, file_path, blob_name):
        if self.fail:
            return None
        self.uploaded.append(blob_name)
        return f"https://blob/{blob_name}"


def _upload_config(fail):
    register_provider("storage", "fake", _FakeUploader)
    return {"providers": {"storage": "fake"}, "fake": {"fail": fail}}


def test_upload_success(tmp_path):
    mp3 = tmp_path / "p.mp3"
    mp3.write_bytes(b"x")
    feed = tmp_path / "feed.xml"
    feed.write_text("<rss/>")
    pipeline._run_upload(str(mp3), str(feed), "p", _upload_config(fail=False))


def test_upload_failure_raises(tmp_path):
    mp3 = tmp_path / "p.mp3"
    mp3.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="Upload failed"):
        pipeline._run_upload(str(mp3), None, "p", _upload_config(fail=True))


def test_register_provider_rejects_wrong_base():
    with pytest.raises(TypeError):
        register_provider("ocr", "bad", _FakeUploader)


def test_get_provider_unknown_name():
    with pytest.raises(ValueError, match="Unknown tts provider"):
        get_provider("tts", "does-not-exist", {})
