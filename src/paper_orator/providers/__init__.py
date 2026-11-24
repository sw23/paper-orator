# Copyright (c) 2025 Spencer Williams
# Licensed under the MIT License. See LICENSE file in the project root.

"""Provider registry — maps provider names to concrete implementations."""

from __future__ import annotations

from paper_orator.providers.base import (
    DocumentExtractor,
    SpeechSynthesizer,
    StorageUploader,
    TextCleaner,
)

# Registry mapping (provider_type, provider_name) → class
_PROVIDERS: dict[str, dict[str, type]] = {
    "ocr": {},
    "llm": {},
    "tts": {},
    "storage": {},
}


def _register_defaults() -> None:
    """Register built-in Azure providers."""
    from paper_orator.providers.azure_llm import AzureTextCleaner
    from paper_orator.providers.azure_ocr import AzureDocumentExtractor
    from paper_orator.providers.azure_storage import AzureBlobUploader
    from paper_orator.providers.azure_tts import AzureSpeechSynthesizer

    _PROVIDERS["ocr"]["azure"] = AzureDocumentExtractor
    _PROVIDERS["llm"]["azure"] = AzureTextCleaner
    _PROVIDERS["tts"]["azure"] = AzureSpeechSynthesizer
    _PROVIDERS["storage"]["azure"] = AzureBlobUploader


_defaults_registered = False


def _ensure_defaults() -> None:
    global _defaults_registered
    if not _defaults_registered:
        _register_defaults()
        _defaults_registered = True


def get_provider(provider_type: str, provider_name: str, config: dict, **kwargs):
    """Instantiate a provider by type and name.

    Args:
        provider_type: One of "ocr", "llm", "tts", "storage".
        provider_name: The backend name, e.g. "azure".
        config: Provider-specific configuration dict.
        **kwargs: Additional keyword arguments passed to the provider constructor.

    Returns:
        An instance of the requested provider.

    Raises:
        ValueError: If the provider type or name is not registered.
    """
    _ensure_defaults()

    if provider_type not in _PROVIDERS:
        raise ValueError(
            f"Unknown provider type '{provider_type}'. "
            f"Available types: {list(_PROVIDERS.keys())}"
        )

    providers = _PROVIDERS[provider_type]
    if provider_name not in providers:
        raise ValueError(
            f"Unknown {provider_type} provider '{provider_name}'. "
            f"Available providers: {list(providers.keys())}"
        )

    cls = providers[provider_name]
    return cls(config, **kwargs)


def register_provider(provider_type: str, provider_name: str, cls: type) -> None:
    """Register a custom provider implementation.

    Args:
        provider_type: One of "ocr", "llm", "tts", "storage".
        provider_name: A unique name for this provider backend.
        cls: The provider class (must subclass the appropriate base class).
    """
    _ensure_defaults()

    if provider_type not in _PROVIDERS:
        raise ValueError(f"Unknown provider type '{provider_type}'")

    expected_base = {
        "ocr": DocumentExtractor,
        "llm": TextCleaner,
        "tts": SpeechSynthesizer,
        "storage": StorageUploader,
    }[provider_type]

    if not issubclass(cls, expected_base):
        raise TypeError(
            f"Provider class {cls.__name__} must be a subclass of {expected_base.__name__}"
        )

    _PROVIDERS[provider_type][provider_name] = cls
