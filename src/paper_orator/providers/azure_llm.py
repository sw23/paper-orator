# Copyright (c) 2025 Spencer Williams
# Licensed under the MIT License. See LICENSE file in the project root.

"""Azure OpenAI provider for cleaning extracted text."""

import logging

from openai import OpenAI

from paper_orator.providers.base import PageContent, TextCleaner

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Your job is to clean and prepare a technical paper PDF to be read aloud by text-to-speech software. "
    "Fix any OCR or layout issues, remove line breaks within sentences, and eliminate irrelevant artifacts "
    "like headers, footers, and page numbers. "
    "CRITICAL: Preserve ALL content from the original document except for figures and tables - do not "
    "summarize, abbreviate, or omit any substantial content. "
    "The goal is to have your response match the original document's full length and detail as closely as "
    "possible, while improving readability for speech delivery. "
    "When you encounter a table or figure, replace it with a detailed description suitable for audio "
    "consumption that fully explains what the visual content shows. "
    "DO NOT include any visual content itself, only the description. "
    "Include ALL sections of the paper except for the references section, if provided in the input. "
    "Your output should be approximately the same length as the input or slightly less since the "
    "references have been removed. "
    "Omit markdown headings (##, ###, etc.). "
)

# Maximum number of images to include in a single API request
IMAGE_LIMIT = 10


def _v1_base_url(endpoint: str) -> str:
    """Build the Azure OpenAI v1 GA API base URL from a resource endpoint.

    Accepts either a bare resource endpoint (``https://<name>.openai.azure.com/``)
    or one that already ends in ``/openai/v1``.
    """
    endpoint = endpoint.rstrip("/")
    if endpoint.endswith("/openai/v1"):
        return endpoint + "/"
    return endpoint + "/openai/v1/"


class AzureTextCleaner(TextCleaner):
    """Cleans extracted document text using Azure OpenAI with vision capabilities."""

    def __init__(self, config: dict):
        """Initialize with Azure OpenAI credentials.

        Args:
            config: Dict with keys 'endpoint', 'key', and 'deployment'.
        """
        # Use the Azure OpenAI v1 GA API. Unlike the dated preview API versions
        # (e.g. "2025-03-01-preview"), it has no api-version to pin or retire.
        self.client = OpenAI(
            base_url=_v1_base_url(config["endpoint"]),
            api_key=config["key"],
        )
        self.deployment = config["deployment"]

    def clean(self, page_lines: PageContent) -> str:
        user_content: list[dict] = []
        text_parts: list[str] = []
        image_count = 0

        # Flatten all pages into a single sequence
        all_lines: list = []
        for page in page_lines:
            all_lines.extend(page)

        for line in all_lines:
            if isinstance(line, dict) and line.get("type") == "image":
                if image_count < IMAGE_LIMIT:
                    if text_parts:
                        user_content.append({
                            "type": "input_text",
                            "text": "\n".join(text_parts),
                        })
                        text_parts = []
                    user_content.append({
                        "type": "input_image",
                        "image_url": f"data:image/png;base64,{line['data']}",
                    })
                    image_count += 1
                else:
                    logger.warning(
                        f"Skipping image (index={line.get('index')}) due to {IMAGE_LIMIT}-image API limit"
                    )
            else:
                text_parts.append(line)

        if text_parts:
            user_content.append({
                "type": "input_text",
                "text": "\n".join(text_parts),
            })

        logger.info("Processing entire document in one batch...")
        response = self.client.responses.create(
            model=self.deployment,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )

        if response.error:
            raise RuntimeError(f"OpenAI API error: {response.error.message}")

        if response.status == "incomplete":
            reason = getattr(response.incomplete_details, "reason", None) or "unknown"
            raise RuntimeError(
                f"LLM response was truncated (reason: {reason}). The cleaned text would be "
                "missing part of the paper; try a deployment with a larger output limit."
            )

        return response.output_text
