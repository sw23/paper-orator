"""Tests for the Azure OpenAI text cleaner (no network calls)."""

from types import SimpleNamespace
from unittest import mock

import pytest

from paper_orator.providers.azure_llm import AzureTextCleaner, _v1_base_url

CONFIG = {"endpoint": "https://res.openai.azure.com/", "key": "k", "deployment": "dep"}


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://res.openai.azure.com",
        "https://res.openai.azure.com/",
        "https://res.openai.azure.com/openai/v1",
        "https://res.openai.azure.com/openai/v1/",
    ],
)
def test_v1_base_url(endpoint):
    assert _v1_base_url(endpoint) == "https://res.openai.azure.com/openai/v1/"


def test_client_uses_v1_api_without_api_version():
    cleaner = AzureTextCleaner(CONFIG)
    assert str(cleaner.client.base_url) == "https://res.openai.azure.com/openai/v1/"
    assert "api-version" not in (cleaner.client.default_query or {})


def _response(**overrides):
    fields = {"error": None, "status": "completed", "incomplete_details": None,
              "output_text": "cleaned"}
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_clean_sends_text_and_images():
    cleaner = AzureTextCleaner(CONFIG)
    pages = [["line one", {"type": "image", "index": 0, "data": "QUJD", "path": "f.png"}],
             ["line two"]]
    with mock.patch.object(cleaner.client.responses, "create",
                           return_value=_response()) as create:
        assert cleaner.clean(pages) == "cleaned"

    kwargs = create.call_args.kwargs
    assert kwargs["model"] == "dep"
    user_content = kwargs["input"][1]["content"]
    assert [c["type"] for c in user_content] == ["input_text", "input_image", "input_text"]
    assert user_content[1]["image_url"] == "data:image/png;base64,QUJD"


def test_clean_raises_on_truncated_output():
    cleaner = AzureTextCleaner(CONFIG)
    truncated = _response(status="incomplete",
                          incomplete_details=SimpleNamespace(reason="max_output_tokens"))
    cleaner.client.responses.create = mock.Mock(return_value=truncated)
    with pytest.raises(RuntimeError, match="max_output_tokens"):
        cleaner.clean([["text"]])
