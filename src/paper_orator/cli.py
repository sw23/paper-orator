# Copyright (c) 2025 Spencer Williams
# Licensed under the MIT License. See LICENSE file in the project root.

"""Command-line interface for Paper Orator."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from paper_orator import __version__
from paper_orator.config import create_default_config, load_config
from paper_orator.pipeline import run_pipeline

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_FILENAME = "paper_orator.yaml"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="paper-orator",
        description="Turn PDF papers into narrated audio podcasts with an RSS feed.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- init subcommand ---
    init_parser = subparsers.add_parser(
        "init",
        help="Create a starter config file in the current directory.",
    )
    init_parser.add_argument(
        "-o", "--output",
        default=DEFAULT_CONFIG_FILENAME,
        help=f"Output path for the config file (default: {DEFAULT_CONFIG_FILENAME})",
    )

    # --- process subcommand ---
    process_parser = subparsers.add_parser(
        "process",
        help="Process a PDF paper into narrated audio.",
    )
    process_parser.add_argument(
        "pdf_path",
        help="Path to the PDF file to process.",
    )
    process_parser.add_argument(
        "-n", "--name",
        dest="paper_name",
        help="Name for the paper (used for output directory and filenames). "
             "Defaults to the PDF filename.",
    )
    process_parser.add_argument(
        "-c", "--config",
        default=DEFAULT_CONFIG_FILENAME,
        help=f"Path to the config file (default: {DEFAULT_CONFIG_FILENAME})",
    )
    process_parser.add_argument(
        "-o", "--output-dir",
        dest="output_dir",
        help="Base output directory (default: ./output)",
    )
    process_parser.add_argument(
        "--web-url",
        dest="web_url",
        help="URL to the original paper (used as <link> in RSS feed).",
    )
    process_parser.add_argument(
        "--update-rss",
        action="store_true",
        help="Update the RSS feed with this paper.",
    )
    process_parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload the MP3 and RSS feed to remote storage.",
    )
    process_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output files without prompting.",
    )
    process_parser.add_argument(
        "--interactive",
        action="store_true",
        help="Prompt before overwriting existing output files.",
    )
    process_parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Set the logging level (default: INFO).",
    )

    args = parser.parse_args(argv)

    if args.command == "init":
        _handle_init(args)
    elif args.command == "process":
        _handle_process(args)


def _handle_init(args) -> None:
    output_path = args.output
    if os.path.exists(output_path):
        print(f"Config file already exists: {output_path}")
        sys.exit(1)
    create_default_config(output_path)
    print(f"Created config file: {output_path}")
    print("Edit it with your feed settings, then set the required environment variables.")


def _handle_process(args) -> None:
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )

    # Validate PDF exists
    if not os.path.exists(args.pdf_path):
        logger.error(f"PDF file not found: {args.pdf_path}")
        sys.exit(1)

    # Load config
    try:
        config = load_config(args.config)
    except (FileNotFoundError, EnvironmentError) as e:
        logger.error(str(e))
        sys.exit(1)

    # Run pipeline
    run_pipeline(
        pdf_path=args.pdf_path,
        config=config,
        paper_name=args.paper_name,
        output_dir=args.output_dir,
        update_rss=args.update_rss,
        upload=args.upload,
        web_url=args.web_url,
        force=args.force,
        interactive=args.interactive,
    )


if __name__ == "__main__":
    main()
