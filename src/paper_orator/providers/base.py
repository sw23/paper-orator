# Copyright (c) 2025 Spencer Williams
# Licensed under the MIT License. See LICENSE file in the project root.

"""Abstract base classes for Paper Orator providers.

Each stage of the pipeline is backed by a provider interface, allowing
different backends (Azure, AWS, local, etc.) to be swapped in.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Union


# Type alias for the page content structure returned by document extractors.
# Each page is a list of items which are either plain text strings or dicts
# representing figures (with keys: type, index, data, path).
PageContent = list[list[Union[str, dict]]]


class DocumentExtractor(ABC):
    """Extracts structured text, tables, and figures from a PDF document."""

    @abstractmethod
    def extract(self, pdf_path: str, output_dir: str) -> PageContent:
        """Extract content from a PDF file.

        Args:
            pdf_path: Path to the input PDF file.
            output_dir: Directory to save extracted figures and tables.

        Returns:
            A list of pages, where each page is a list of content items.
            Items are either plain text strings or dicts for figures:
                {"type": "image", "index": int, "data": str, "path": str}
        """


class TextCleaner(ABC):
    """Cleans and prepares extracted text for text-to-speech."""

    @abstractmethod
    def clean(self, page_lines: PageContent) -> str:
        """Clean extracted page content into TTS-ready text.

        Args:
            page_lines: Page content as returned by DocumentExtractor.extract().

        Returns:
            A single cleaned text string ready for speech synthesis.
        """


class SpeechSynthesizer(ABC):
    """Converts text to spoken audio."""

    @abstractmethod
    def synthesize(self, text: str, output_path: str) -> None:
        """Convert text to an audio file.

        Args:
            text: The text to convert to speech.
            output_path: Path where the output audio file should be saved.
        """


class StorageUploader(ABC):
    """Uploads files to remote storage."""

    @abstractmethod
    def upload(self, file_path: str, blob_name: str) -> str | None:
        """Upload a file to remote storage.

        Args:
            file_path: Local path to the file to upload.
            blob_name: The name/key for the file in remote storage.

        Returns:
            The URL of the uploaded file, or None if upload failed.
        """
