# Copyright (c) 2025 Spencer Williams
# Licensed under the MIT License. See LICENSE file in the project root.

"""Azure Speech Service provider for text-to-speech synthesis.

Two synthesis paths are supported:

* **Chunked real-time** (REST ``/cognitiveservices/v1``): the text is split
  into chunks at paragraph/sentence boundaries, each chunk is synthesized
  separately, and the MP3 segments are concatenated. There is no overall
  length limit. This is the only path that supports MAI voices (e.g.
  ``en-US-Harper:MAI-Voice-2.1``) and HD voices (e.g.
  ``en-US-Ava:DragonHDLatestNeural``), which are real-time only.
* **Batch synthesis** (REST ``/texttospeech/batchsyntheses``): a single
  long-running job. Only supports standard neural voices (e.g.
  ``en-US-JennyNeural``).
"""

from __future__ import annotations

import html
import logging
import os
import re
import shutil
import time
import uuid
import zipfile

import requests

from paper_orator.providers.base import SpeechSynthesizer

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "en-US-Harper:MAI-Voice-2.1"
DEFAULT_OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"

BATCH_API_VERSION = "2024-04-01"

# Real-time requests are capped at 10 minutes of audio each. ~3,000 characters
# is roughly 3-4 minutes of speech, which leaves plenty of headroom.
MAX_CHUNK_CHARS = 3000

# Retry policy for transient real-time errors (throttling / server errors)
MAX_ATTEMPTS = 5
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


def is_batch_compatible_voice(voice: str) -> bool:
    """Return True if a voice can be used with the batch synthesis API.

    MAI and HD voices use a ``<voice>:<model>`` name (e.g.
    ``en-US-Harper:MAI-Voice-2.1``) and are only available for real-time
    synthesis.
    """
    return ":" not in voice


def voice_locale(voice: str) -> str:
    """Extract the locale (e.g. ``en-US``) from a voice name, defaulting to en-US."""
    match = re.match(r"^([a-z]{2,3}-[A-Z]{2})-", voice)
    return match.group(1) if match else "en-US"


def build_ssml(text: str, voice: str) -> str:
    """Wrap plain text in an SSML document for the given voice."""
    lang = voice_locale(voice)
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{lang}">'
        f'<voice name="{html.escape(voice)}">{html.escape(text)}</voice></speak>'
    )


def split_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split text into chunks of at most ``max_chars`` characters.

    Splits on paragraph boundaries where possible, then sentence boundaries,
    then whitespace, so chunks never break mid-word.
    """
    pieces: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        if len(paragraph) <= max_chars:
            pieces.append(paragraph)
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
            while len(sentence) > max_chars:
                cut = sentence.rfind(" ", 0, max_chars)
                if cut <= 0:
                    cut = max_chars
                pieces.append(sentence[:cut].strip())
                sentence = sentence[cut:].strip()
            if sentence:
                pieces.append(sentence)

    # Greedily pack pieces into chunks, keeping paragraph breaks
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}\n\n{piece}" if current else piece
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return chunks


class AzureSpeechSynthesizer(SpeechSynthesizer):
    """Converts text to speech using Azure Speech (Foundry Tools)."""

    def __init__(
        self,
        config: dict,
        voice: str = DEFAULT_VOICE,
        use_batch: bool = False,
        output_format: str = DEFAULT_OUTPUT_FORMAT,
    ):
        """Initialize with Azure Speech credentials.

        Args:
            config: Dict with keys 'key' and 'region'.
            voice: The TTS voice name to use.
            use_batch: If True and the voice supports it, use the batch synthesis
                       API. Otherwise use chunked real-time synthesis.
            output_format: Azure audio output format (must be an MP3 format).
        """
        self.key = config["key"]
        self.region = config["region"]
        self.voice = voice
        self.output_format = output_format
        self.max_chunk_chars = MAX_CHUNK_CHARS
        self.use_batch = use_batch
        if use_batch and not is_batch_compatible_voice(voice):
            logger.info(
                f"Voice '{voice}' is not supported by batch synthesis; "
                "using chunked real-time synthesis instead"
            )
            self.use_batch = False

    def synthesize(self, text: str, output_path: str) -> None:
        output_dir = os.path.dirname(output_path)
        if self.use_batch:
            zip_path = os.path.join(output_dir, "batch_results.zip")
            self._batch_synthesize(text, zip_path)
            self._unzip_batch_results(zip_path, output_dir, output_path)
        else:
            self._chunked_synthesize(text, output_path)

    # ------------------------------------------------------------------
    # Chunked real-time synthesis
    # ------------------------------------------------------------------

    def _chunked_synthesize(self, text: str, output_path: str) -> None:
        """Synthesize long text by concatenating real-time MP3 segments."""
        chunks = split_text(text, self.max_chunk_chars)
        if not chunks:
            raise RuntimeError("No text to synthesize")

        url = f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {
            "Ocp-Apim-Subscription-Key": self.key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": self.output_format,
            "User-Agent": "paper-orator",
        }

        # Write to a temporary file so an interrupted run never leaves a partial
        # MP3 that a later run would mistake for finished output.
        part_path = output_path + ".part"
        logger.info(f"Synthesizing {len(chunks)} chunk(s) with voice '{self.voice}'...")
        try:
            with requests.Session() as session, open(part_path, "wb") as out:
                for index, chunk in enumerate(chunks, start=1):
                    logger.info(f"Synthesizing chunk {index}/{len(chunks)}...")
                    audio = self._synthesize_chunk(session, url, headers, chunk)
                    out.write(audio)
            os.replace(part_path, output_path)
        finally:
            if os.path.exists(part_path):
                os.remove(part_path)
        logger.info(f"Audio saved to {output_path}")

    def _synthesize_chunk(self, session, url: str, headers: dict, text: str) -> bytes:
        ssml = build_ssml(text, self.voice).encode("utf-8")
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = session.post(url, headers=headers, data=ssml, timeout=300)
            except (requests.ConnectionError, requests.Timeout) as e:
                if attempt == MAX_ATTEMPTS:
                    raise RuntimeError(f"Speech synthesis request failed: {e}") from e
                error = str(e)
            else:
                if response.status_code == 200 and response.content:
                    return response.content
                if response.status_code not in RETRY_STATUS_CODES or attempt == MAX_ATTEMPTS:
                    raise RuntimeError(
                        f"Speech synthesis failed: {response.status_code} - {response.text[:500]}"
                    )
                error = f"HTTP {response.status_code}"
                retry_after = response.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    time.sleep(int(retry_after))
                    continue
            delay = 2 ** attempt
            logger.warning(f"Transient synthesis error ({error}); retrying in {delay}s...")
            time.sleep(delay)
        raise RuntimeError("Speech synthesis failed")  # pragma: no cover

    # ------------------------------------------------------------------
    # Batch synthesis (standard neural voices only)
    # ------------------------------------------------------------------

    def _batch_synthesize(self, text: str, zip_path: str) -> None:
        """Use Azure Batch Synthesis API for long audio generation."""
        synthesis_id = f"paper-synthesis-{uuid.uuid4()}"
        base_url = f"https://{self.region}.api.cognitive.microsoft.com"
        job_url = (
            f"{base_url}/texttospeech/batchsyntheses/{synthesis_id}"
            f"?api-version={BATCH_API_VERSION}"
        )

        headers = {
            "Ocp-Apim-Subscription-Key": self.key,
            "Content-Type": "application/json",
        }

        payload = {
            "description": "Paper Orator text-to-speech conversion",
            "inputKind": "SSML",
            "inputs": [{"content": build_ssml(text, self.voice)}],
            "properties": {
                "outputFormat": self.output_format,
                "wordBoundaryEnabled": False,
                "sentenceBoundaryEnabled": False,
                "concatenateResult": True,
            },
        }

        logger.info(f"Submitting batch synthesis request (ID: {synthesis_id})...")
        response = requests.put(job_url, headers=headers, json=payload, timeout=60)

        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to create batch synthesis: {response.status_code} - {response.text}"
            )

        try:
            self._wait_for_batch(job_url, headers, zip_path)
        finally:
            # Clean up the batch synthesis job whether it succeeded or not
            try:
                requests.delete(job_url, headers=headers, timeout=60)
            except requests.RequestException as e:
                logger.warning(f"Failed to delete batch synthesis job {synthesis_id}: {e}")

    def _wait_for_batch(self, job_url: str, headers: dict, zip_path: str) -> None:
        logger.info("Waiting for batch synthesis to complete...")

        max_wait_time = 60 * 60  # 60 minutes
        poll_interval = 30
        elapsed_time = 0

        while elapsed_time < max_wait_time:
            time.sleep(poll_interval)
            elapsed_time += poll_interval

            response = requests.get(job_url, headers=headers, timeout=60)
            if response.status_code != 200:
                raise RuntimeError(
                    f"Failed to get synthesis status: {response.status_code} - {response.text}"
                )

            result = response.json()
            status = result.get("status", "Unknown")

            if status == "Succeeded":
                logger.info("Batch synthesis completed successfully!")
                result_url = result.get("outputs", {}).get("result")
                if not result_url:
                    raise RuntimeError("No result URL found in batch synthesis response")

                # The result URL is a pre-signed (SAS) URL; it must not receive
                # the subscription key.
                logger.info("Downloading synthesized audio...")
                download_response = requests.get(result_url, timeout=300)
                if download_response.status_code != 200:
                    raise RuntimeError(
                        f"Failed to download results: {download_response.status_code}"
                    )

                with open(zip_path, "wb") as f:
                    f.write(download_response.content)
                return

            if status == "Failed":
                details = result.get("properties", {}).get("error") or result.get("error")
                raise RuntimeError(f"Batch synthesis failed: {details or 'no details returned'}")
            if status == "Running":
                logger.info(f"Synthesis in progress... (elapsed: {elapsed_time}s)")
            else:
                logger.info(f"Synthesis status: {status}")

        raise RuntimeError(f"Synthesis timed out after {max_wait_time} seconds")

    @staticmethod
    def _unzip_batch_results(zip_path: str, output_dir: str, output_mp3_path: str) -> None:
        """Extract audio file from the batch synthesis ZIP results."""
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            audio_files = [f for f in zip_ref.namelist() if f.endswith(".mp3")]
            if not audio_files:
                raise RuntimeError("No audio files found in the batch synthesis results")
            zip_ref.extract(audio_files[0], output_dir)
            extracted_path = os.path.join(output_dir, audio_files[0])
            shutil.move(extracted_path, output_mp3_path)
            logger.info(f"Audio saved to {output_mp3_path}")
