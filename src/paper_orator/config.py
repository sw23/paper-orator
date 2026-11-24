# Copyright (c) 2025 Spencer Williams
# Licensed under the MIT License. See LICENSE file in the project root.

"""Configuration loader for Paper Orator.

Loads a YAML config file and resolves ${ENV_VAR} references to environment
variable values.
"""

import logging
import os
import re
import shutil

import yaml

logger = logging.getLogger(__name__)

_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")

# Defaults applied when keys are missing from the config file
_DEFAULTS = {
    "feed": {
        "title": "Research Audio Feed",
        "description": "Audio versions of research papers and articles",
        "link": "",
        "base_url": "",
        "language": "en-us",
    },
    "tts": {
        "voice": "en-US-JennyNeural",
        "use_batch": True,
    },
    "providers": {
        "ocr": "azure",
        "llm": "azure",
        "tts": "azure",
        "storage": "azure",
    },
}


def _resolve_env_vars(value):
    """Recursively resolve ${ENV_VAR} references in config values."""
    if isinstance(value, str):
        def _replace(match):
            var_name = match.group(1)
            env_val = os.environ.get(var_name)
            if env_val is None:
                raise OSError(
                    f"Environment variable '{var_name}' is referenced in config but not set"
                )
            return env_val
        return _ENV_VAR_PATTERN.sub(_replace, value)
    elif isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


def _deep_merge(defaults: dict, overrides: dict) -> dict:
    """Merge overrides into defaults, recursing into nested dicts."""
    result = defaults.copy()
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: str) -> dict:
    """Load and validate a Paper Orator YAML configuration file.

    Environment variable references (${VAR_NAME}) in string values are
    resolved at load time.

    Args:
        config_path: Path to the YAML config file.

    Returns:
        A dict of resolved configuration values.

    Raises:
        FileNotFoundError: If the config file does not exist.
        OSError: If a referenced environment variable is not set.
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            f"Run 'paper-orator init' to create one from the example template."
        )

    with open(config_path) as f:
        raw_config = yaml.safe_load(f) or {}

    # Merge with defaults
    config = _deep_merge(_DEFAULTS, raw_config)

    # Resolve environment variables
    config = _resolve_env_vars(config)

    return config


def get_provider_config(config: dict, provider_type: str) -> dict:
    """Extract the config dict for a specific provider.

    Looks up which backend is selected for the given provider type
    (e.g. "azure" for "ocr") and returns the corresponding config section.
    Within the backend section, the provider's sub-section is looked up by its
    Azure-style name (e.g. "document_intelligence"), then by the provider type
    (e.g. "ocr"). If neither exists, the whole backend section is returned, so
    a custom provider can use a flat ``custom:`` section.

    Args:
        config: The full resolved config dict.
        provider_type: One of "ocr", "llm", "tts", "storage".

    Returns:
        The provider-specific config dict.
    """
    provider_name = config["providers"][provider_type]

    # Map provider types to their config section keys within the backend config
    section_map = {
        "ocr": "document_intelligence",
        "llm": "openai",
        "tts": "speech",
        "storage": "storage",
    }

    backend_config = config.get(provider_name) or {}
    for section_key in (section_map.get(provider_type), provider_type):
        if section_key in backend_config:
            return backend_config[section_key] or {}
    return backend_config


def create_default_config(output_path: str) -> None:
    """Copy the example config template to the specified path.

    Args:
        output_path: Where to write the config file.
    """
    # Find the example config shipped with the package
    example_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "paper_orator.example.yaml",
    )

    # Fallback: try from the installed package's parent
    if not os.path.exists(example_path):
        # When installed via pip, the example file is at the repo root
        # Use a bundled copy instead
        example_path = None

    if example_path and os.path.exists(example_path):
        shutil.copy2(example_path, output_path)
    else:
        # Write a minimal config inline
        _write_default_config(output_path)

    logger.info(f"Config file created: {output_path}")


def _write_default_config(output_path: str) -> None:
    """Write a default config file from the built-in template."""
    template = """\
# paper-orator configuration
# Environment variables can be referenced with ${ENV_VAR} syntax.

# RSS feed settings
feed:
  title: "My Research Audio Feed"
  description: "Audio versions of research papers and articles"
  link: "https://example.com/feed/feed.xml"
  base_url: "https://example.com/feed/"
  language: "en-us"

# Text-to-speech settings
tts:
  voice: "en-US-JennyNeural"
  use_batch: true

# Provider selection (currently supported: "azure")
providers:
  ocr: azure
  llm: azure
  tts: azure
  storage: azure

# Azure provider configuration
# Set these environment variables before running:
#   AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT, AZURE_DOCUMENT_INTELLIGENCE_KEY
#   AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY, AZURE_OPENAI_DEPLOYMENT
#   AZURE_SPEECH_KEY, AZURE_SPEECH_REGION
#   AZURE_STORAGE_CONNECTION_STRING, AZURE_STORAGE_CONTAINER_NAME
azure:
  document_intelligence:
    endpoint: "${AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT}"
    key: "${AZURE_DOCUMENT_INTELLIGENCE_KEY}"
  openai:
    endpoint: "${AZURE_OPENAI_ENDPOINT}"
    key: "${AZURE_OPENAI_KEY}"
    deployment: "${AZURE_OPENAI_DEPLOYMENT}"
  speech:
    key: "${AZURE_SPEECH_KEY}"
    region: "${AZURE_SPEECH_REGION}"
  storage:
    connection_string: "${AZURE_STORAGE_CONNECTION_STRING}"
    container_name: "${AZURE_STORAGE_CONTAINER_NAME}"
"""
    with open(output_path, "w") as f:
        f.write(template)
