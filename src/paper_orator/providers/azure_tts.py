# Copyright (c) 2025 Spencer Williams
# Licensed under the MIT License. See LICENSE file in the project root.

"""Azure Speech Service provider for text-to-speech synthesis."""

import html
import logging
import os
import shutil
import time
import uuid
import zipfile

import requests

from paper_orator.providers.base import SpeechSynthesizer

logger = logging.getLogger(__name__)


class AzureSpeechSynthesizer(SpeechSynthesizer):
    """Converts text to speech using Azure Cognitive Services.

    Supports both batch synthesis (for long content) and real-time SDK
    synthesis (for short content under 10 minutes).
    """

    def __init__(self, config: dict, voice: str = "en-US-JennyNeural", use_batch: bool = True):
        """Initialize with Azure Speech credentials.

        Args:
            config: Dict with keys 'key' and 'region'.
            voice: The TTS voice name to use.
            use_batch: If True, use batch synthesis API (supports long audio).
                       If False, use real-time SDK (limited to ~10 min).
        """
        self.key = config["key"]
        self.region = config["region"]
        self.voice = voice
        self.use_batch = use_batch

    def synthesize(self, text: str, output_path: str) -> None:
        output_dir = os.path.dirname(output_path)
        if self.use_batch:
            zip_path = os.path.join(output_dir, "batch_results.zip")
            self._batch_synthesize(text, zip_path)
            self._unzip_batch_results(zip_path, output_dir, output_path)
        else:
            self._realtime_synthesize(text, output_path)

    def _batch_synthesize(self, text: str, zip_path: str) -> None:
        """Use Azure Batch Synthesis API for long audio generation."""
        escaped_text = html.escape(text)
        ssml_text = (
            f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">'
            f'<voice name="{self.voice}">{escaped_text}</voice></speak>'
        )

        synthesis_id = f"paper-synthesis-{uuid.uuid4()}"
        base_url = f"https://{self.region}.api.cognitive.microsoft.com"
        create_url = f"{base_url}/texttospeech/batchsyntheses/{synthesis_id}?api-version=2024-04-01"

        headers = {
            "Ocp-Apim-Subscription-Key": self.key,
            "Content-Type": "application/json",
        }

        payload = {
            "description": "Paper Orator text-to-speech conversion",
            "inputKind": "SSML",
            "inputs": [{"content": ssml_text}],
            "properties": {
                "outputFormat": "audio-24khz-48kbitrate-mono-mp3",
                "wordBoundaryEnabled": False,
                "sentenceBoundaryEnabled": False,
                "concatenateResult": True,
            },
        }

        logger.info(f"Submitting batch synthesis request (ID: {synthesis_id})...")
        response = requests.put(create_url, headers=headers, json=payload, timeout=60)

        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to create batch synthesis: {response.status_code} - {response.text}"
            )

        # Poll for completion
        get_url = f"{base_url}/texttospeech/batchsyntheses/{synthesis_id}?api-version=2024-04-01"
        logger.info("Waiting for batch synthesis to complete...")

        max_wait_time = 60 * 60  # 60 minutes
        poll_interval = 30
        elapsed_time = 0

        while elapsed_time < max_wait_time:
            time.sleep(poll_interval)
            elapsed_time += poll_interval

            response = requests.get(get_url, headers=headers, timeout=60)
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

                logger.info("Downloading synthesized audio...")
                download_response = requests.get(
                    result_url,
                    headers={"Ocp-Apim-Subscription-Key": self.key},
                    timeout=300,
                )
                if download_response.status_code != 200:
                    raise RuntimeError(
                        f"Failed to download results: {download_response.status_code}"
                    )

                with open(zip_path, "wb") as f:
                    f.write(download_response.content)

                # Clean up the batch synthesis job
                delete_url = (
                    f"{base_url}/texttospeech/batchsyntheses/{synthesis_id}?api-version=2024-04-01"
                )
                requests.delete(delete_url, headers=headers, timeout=60)
                return

            elif status == "Failed":
                raise RuntimeError("Batch synthesis failed")
            elif status == "Running":
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

    def _realtime_synthesize(self, text: str, output_path: str) -> None:
        """Convert text to speech using the Azure Speech SDK (limited to ~10 min)."""
        import azure.cognitiveservices.speech as speechsdk

        speech_config = speechsdk.SpeechConfig(subscription=self.key, region=self.region)
        speech_config.speech_synthesis_voice_name = self.voice
        audio_config = speechsdk.audio.AudioOutputConfig(filename=output_path)
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config, audio_config=audio_config
        )

        logger.info("Synthesizing speech...")
        result = synthesizer.speak_text_async(text).get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            logger.info(f"Audio saved to {output_path}")
        else:
            raise RuntimeError(f"Speech synthesis failed: {result.reason}")
