"""Tests for config loading and provider config lookup."""

import pytest
import yaml

from paper_orator.config import create_default_config, get_provider_config, load_config


def _write(tmp_path, data):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    return str(path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "nope.yaml"))


def test_defaults_merged(tmp_path):
    config = load_config(_write(tmp_path, {"feed": {"title": "Mine"}}))
    assert config["feed"]["title"] == "Mine"
    assert config["feed"]["language"] == "en-us"
    assert config["providers"]["tts"] == "azure"


def test_empty_file_uses_defaults(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("")
    assert load_config(str(path))["providers"]["ocr"] == "azure"


def test_env_vars_resolved(tmp_path, monkeypatch):
    monkeypatch.setenv("PO_TEST_KEY", "secret")
    config = load_config(_write(tmp_path, {"azure": {"speech": {"key": "${PO_TEST_KEY}"}}}))
    assert config["azure"]["speech"]["key"] == "secret"


def test_missing_env_var_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("PO_TEST_MISSING", raising=False)
    with pytest.raises(OSError, match="PO_TEST_MISSING"):
        load_config(_write(tmp_path, {"azure": {"speech": {"key": "${PO_TEST_MISSING}"}}}))


def test_get_provider_config_azure_sections():
    config = {
        "providers": {"ocr": "azure", "tts": "azure"},
        "azure": {"document_intelligence": {"endpoint": "e"}, "speech": {"key": "k"}},
    }
    assert get_provider_config(config, "ocr") == {"endpoint": "e"}
    assert get_provider_config(config, "tts") == {"key": "k"}


def test_get_provider_config_custom_flat_section():
    config = {"providers": {"ocr": "custom"}, "custom": {"api_key": "abc"}}
    assert get_provider_config(config, "ocr") == {"api_key": "abc"}


def test_get_provider_config_custom_by_type():
    config = {"providers": {"ocr": "custom"}, "custom": {"ocr": {"api_key": "abc"}}}
    assert get_provider_config(config, "ocr") == {"api_key": "abc"}


def test_create_default_config_is_loadable(tmp_path, monkeypatch):
    for var in ("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "AZURE_DOCUMENT_INTELLIGENCE_KEY",
                "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_KEY", "AZURE_OPENAI_DEPLOYMENT",
                "AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION", "AZURE_STORAGE_CONNECTION_STRING",
                "AZURE_STORAGE_CONTAINER_NAME"):
        monkeypatch.setenv(var, "x")
    out = tmp_path / "paper_orator.yaml"
    create_default_config(str(out))
    config = load_config(str(out))
    assert config["providers"] == {"ocr": "azure", "llm": "azure", "tts": "azure",
                                   "storage": "azure"}
