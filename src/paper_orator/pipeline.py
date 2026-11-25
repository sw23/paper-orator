# Copyright (c) 2025 Spencer Williams
# Licensed under the MIT License. See LICENSE file in the project root.

"""Pipeline orchestration for Paper Orator.

Coordinates the end-to-end flow: PDF extraction → text cleaning →
speech synthesis → RSS update → upload.
"""

from __future__ import annotations

import base64
import logging
import os

from paper_orator.config import get_provider_config
from paper_orator.providers import get_provider
from paper_orator.rss import update_rss_feed

logger = logging.getLogger(__name__)


def run_pipeline(
    pdf_path: str,
    config: dict,
    paper_name: str | None = None,
    output_dir: str | None = None,
    update_rss: bool = False,
    upload: bool = False,
    web_url: str | None = None,
    force: bool = False,
    interactive: bool = False,
) -> None:
    """Run the full paper-to-audio pipeline.

    Args:
        pdf_path: Path to the input PDF file.
        config: Resolved configuration dict (from config.load_config).
        paper_name: Name for the paper. Defaults to the PDF filename stem.
        output_dir: Base output directory. Defaults to ./output.
        update_rss: Whether to update the RSS feed.
        upload: Whether to upload files to remote storage.
        web_url: URL to the original paper (for RSS <link>).
        force: Overwrite existing output files without prompting.
        interactive: Prompt before overwriting existing files.
    """
    if not paper_name:
        paper_name = os.path.splitext(os.path.basename(pdf_path))[0]

    if not output_dir:
        output_dir = os.path.join(os.getcwd(), "output")

    paper_output_dir = os.path.join(output_dir, paper_name)
    os.makedirs(paper_output_dir, exist_ok=True)
    logger.info(f"Output directory: {paper_output_dir}")

    # --- Stage 1: Extract PDF contents ---
    raw_text_path = os.path.join(paper_output_dir, "raw_text.txt")
    page_lines = _run_extraction(pdf_path, paper_output_dir, raw_text_path, config, force, interactive)

    # --- Stage 2: Clean text with LLM ---
    cleaned_text_path = os.path.join(paper_output_dir, "cleaned_text.txt")
    cleaned_text = _run_cleaning(page_lines, cleaned_text_path, config, force, interactive)

    # --- Stage 3: Synthesize speech ---
    output_audio_path = os.path.join(paper_output_dir, f"{paper_name}.mp3")
    _run_synthesis(cleaned_text, output_audio_path, config, force, interactive)

    # --- Stage 4: Update RSS feed ---
    rss_file_path = None
    if update_rss and os.path.exists(output_audio_path):
        rss_file_path = os.path.join(output_dir, "feed.xml")
        paper_file_size = os.path.getsize(output_audio_path)
        logger.info("Updating RSS feed...")
        update_rss_feed(
            rss_file_path=rss_file_path,
            paper_name=paper_name,
            cleaned_text=cleaned_text,
            paper_file_size=paper_file_size,
            feed_config=config.get("feed", {}),
            web_url=web_url,
            force=force,
            interactive=interactive,
        )

    # --- Stage 5: Upload to storage ---
    if upload and os.path.exists(output_audio_path):
        _run_upload(output_audio_path, rss_file_path, paper_name, config)

    logger.info(f"Processing complete for paper: {paper_name}")


def _should_run_stage(file_path: str, stage_name: str, force: bool, interactive: bool) -> bool:
    """Determine whether a pipeline stage should run.

    Returns True if:
    - The output file doesn't exist yet, or
    - force=True (overwrite without asking), or
    - interactive=True and the user confirms.

    Skips the stage if the file exists and neither force nor interactive is set.
    """
    if not os.path.exists(file_path):
        return True
    if force:
        logger.info(f"Overwriting existing file: {file_path}")
        return True
    if interactive:
        response = (
            input(f"File {file_path} already exists.\nRe-run {stage_name}? (y/n): ")
            .strip()
            .lower()
        )
        return response == "y"
    logger.info(f"Skipping {stage_name} (output exists, use --force to overwrite): {file_path}")
    return False


def _run_extraction(pdf_path, output_dir, raw_text_path, config, force, interactive):
    """Run the PDF extraction stage."""
    if _should_run_stage(raw_text_path, "PDF extraction", force, interactive):
        logger.info("Extracting PDF contents...")
        ocr_config = get_provider_config(config, "ocr")
        extractor = get_provider("ocr", config["providers"]["ocr"], ocr_config)
        page_lines = extractor.extract(pdf_path, output_dir)

        logger.info(f"Saving {raw_text_path}")
        with open(raw_text_path, "w") as f:
            for page_contents in page_lines:
                f.write("--- Page ---\n")
                for line in page_contents:
                    if isinstance(line, dict) and line.get("type") == "image":
                        f.write(f"--- Figure --- : {line['index']} : {line['path']}\n")
                    else:
                        f.write(line + "\n")
        return page_lines

    # Load from existing raw_text.txt
    logger.info(f"Loading existing extracted text: {raw_text_path}")
    return _load_raw_text(raw_text_path)


def _load_raw_text(raw_text_path):
    """Parse the raw_text.txt intermediate file back into page_lines structure."""
    page_lines = []
    with open(raw_text_path) as f:
        content = f.read()
    for page_block in content.split("--- Page ---\n"):
        if not page_block:
            continue
        new_page_lines = []
        for line in page_block.split("\n"):
            if line.startswith("--- Figure ---"):
                parts = line.split(" : ")
                figure_index = parts[1]
                figure_path = parts[2]
                try:
                    with open(figure_path, "rb") as img_file:
                        image_data = base64.b64encode(img_file.read()).decode("utf-8")
                except FileNotFoundError:
                    logger.warning(f"Figure file not found: {figure_path}, skipping")
                    continue
                new_page_lines.append({
                    "type": "image",
                    "index": figure_index,
                    "data": image_data,
                    "path": figure_path,
                })
            else:
                new_page_lines.append(line)
        page_lines.append(new_page_lines)
    return page_lines


def _run_cleaning(page_lines, cleaned_text_path, config, force, interactive):
    """Run the text cleaning stage."""
    if _should_run_stage(cleaned_text_path, "text cleaning", force, interactive):
        logger.info("Cleaning text with LLM...")
        llm_config = get_provider_config(config, "llm")
        cleaner = get_provider("llm", config["providers"]["llm"], llm_config)
        cleaned_text = cleaner.clean(page_lines)

        with open(cleaned_text_path, "w") as f:
            f.write(cleaned_text)
        return cleaned_text

    logger.info(f"Loading existing cleaned text: {cleaned_text_path}")
    with open(cleaned_text_path) as f:
        return f.read()


def _run_synthesis(cleaned_text, output_audio_path, config, force, interactive):
    """Run the speech synthesis stage."""
    if _should_run_stage(output_audio_path, "speech synthesis", force, interactive):
        logger.info("Synthesizing speech...")
        tts_config = get_provider_config(config, "tts")
        tts_kwargs = {
            "voice": config.get("tts", {}).get("voice", "en-US-JennyNeural"),
            "use_batch": config.get("tts", {}).get("use_batch", True),
        }
        synthesizer = get_provider("tts", config["providers"]["tts"], tts_config, **tts_kwargs)
        synthesizer.synthesize(cleaned_text, output_audio_path)


def _run_upload(output_audio_path, rss_file_path, paper_name, config):
    """Run the storage upload stage."""
    logger.info("Uploading files to remote storage...")
    storage_config = get_provider_config(config, "storage")
    uploader = get_provider("storage", config["providers"]["storage"], storage_config)

    uploads = [(output_audio_path, f"feed/{paper_name}.mp3")]
    if rss_file_path and os.path.exists(rss_file_path):
        uploads.append((rss_file_path, "feed/feed.xml"))

    failed = [path for path, blob_name in uploads if uploader.upload(path, blob_name) is None]
    if failed:
        raise RuntimeError(f"Upload failed for: {', '.join(failed)}")
