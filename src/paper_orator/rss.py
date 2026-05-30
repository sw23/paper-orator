# Copyright (c) 2025 Spencer Williams
# Licensed under the MIT License. See LICENSE file in the project root.

"""RSS feed management for Paper Orator.

Creates and updates an RSS/podcast feed XML file with entries for each
processed paper.
"""

from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import quote, urljoin

logger = logging.getLogger(__name__)


def update_rss_feed(
    rss_file_path: str,
    paper_name: str,
    cleaned_text: str,
    paper_file_size: int,
    feed_config: dict,
    web_url: str | None = None,
    force: bool = False,
    interactive: bool = False,
) -> None:
    """Update the RSS feed with a new or updated paper entry.

    Args:
        rss_file_path: Path to the feed.xml file.
        paper_name: Identifier for the paper (used in URLs and titles).
        cleaned_text: The cleaned paper text (first 200 chars used as description).
        paper_file_size: Size of the MP3 file in bytes.
        feed_config: Dict with keys: title, description, link, base_url, language.
        web_url: Optional URL to the original paper. Defaults to the audio URL.
        force: If True, overwrite existing entries without prompting.
        interactive: If True, prompt the user before overwriting.
    """
    feed_title = feed_config.get("title", "Research Audio Feed")
    feed_description = feed_config.get("description", "")
    feed_link = feed_config.get("link", "")
    feed_base_url = feed_config.get("base_url", "")
    feed_language = feed_config.get("language", "en-us")

    paper_title = paper_name.replace("-", " ").replace("_", " ").title()

    description = cleaned_text[:200].replace("\n", " ").strip()
    if len(cleaned_text) > 200:
        description += "..."

    pub_date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    audio_url = urljoin(feed_base_url, f"{quote(paper_name)}.mp3")
    link_url = web_url if web_url else audio_url

    # Load or create RSS structure
    existing_item = None
    root = None

    if os.path.exists(rss_file_path):
        try:
            tree = ET.parse(rss_file_path)
            root = tree.getroot()
            channel = root.find("channel")

            for item in channel.findall("item"):
                guid_elem = item.find("guid")
                if guid_elem is not None and guid_elem.text == audio_url:
                    existing_item = item
                    break

            if existing_item is not None:
                if interactive:
                    response = (
                        input(
                            f"Paper '{paper_name}' already exists in RSS feed.\n"
                            f"Update it with new information? (y/n): "
                        )
                        .strip()
                        .lower()
                    )
                    if response != "y":
                        logger.info("Skipping RSS feed update")
                        return
                elif not force:
                    logger.info(
                        f"Paper '{paper_name}' already in RSS feed, skipping (use --force to update)"
                    )
                    return

        except ET.ParseError:
            logger.warning("Existing RSS feed is malformed, creating new one")
            root = None

    if root is None:
        root = ET.Element("rss", version="2.0")
        root.set("xmlns:atom", "http://www.w3.org/2005/Atom")

        channel = ET.SubElement(root, "channel")
        ET.SubElement(channel, "title").text = feed_title
        ET.SubElement(channel, "description").text = feed_description
        ET.SubElement(channel, "link").text = feed_link

        atom_link = ET.SubElement(channel, "atom:link")
        atom_link.set("href", feed_link)
        atom_link.set("rel", "self")
        atom_link.set("type", "application/rss+xml")

        ET.SubElement(channel, "language").text = feed_language
        ET.SubElement(channel, "lastBuildDate").text = pub_date
    else:
        channel = root.find("channel")
        last_build_date = channel.find("lastBuildDate")
        if last_build_date is not None:
            last_build_date.text = pub_date
        else:
            ET.SubElement(channel, "lastBuildDate").text = pub_date

    if existing_item is not None:
        logger.info(f"Updating existing RSS entry for '{paper_name}'")

        title_elem = existing_item.find("title")
        if title_elem is not None:
            title_elem.text = paper_title

        description_elem = existing_item.find("description")
        if description_elem is not None:
            description_elem.text = description

        link_elem = existing_item.find("link")
        if link_elem is not None:
            link_elem.text = link_url

        pub_date_elem = existing_item.find("pubDate")
        if pub_date_elem is not None:
            pub_date_elem.text = pub_date

        enclosure_elem = existing_item.find("enclosure")
        if enclosure_elem is not None:
            enclosure_elem.set("length", str(paper_file_size))

        # Move updated item to top
        channel.remove(existing_item)
        _insert_item_after_metadata(channel, existing_item)
    else:
        logger.info(f"Adding new RSS entry for '{paper_name}'")
        item = ET.Element("item")
        ET.SubElement(item, "title").text = paper_title
        ET.SubElement(item, "description").text = description
        ET.SubElement(item, "link").text = link_url
        ET.SubElement(item, "guid").text = audio_url
        ET.SubElement(item, "pubDate").text = pub_date

        enclosure = ET.SubElement(item, "enclosure")
        enclosure.set("url", audio_url)
        enclosure.set("type", "audio/mpeg")
        enclosure.set("length", str(paper_file_size))

        _insert_item_after_metadata(channel, item)

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ", level=0)

    with open(rss_file_path, "wb") as f:
        tree.write(f, encoding="utf-8", xml_declaration=True)
    logger.info(f"RSS feed updated: {rss_file_path}")


def _insert_item_after_metadata(channel: ET.Element, item: ET.Element) -> None:
    """Insert an item element after the channel metadata (lastBuildDate)."""
    last_build_date = channel.find("lastBuildDate")
    if last_build_date is not None:
        channel_children = list(channel)
        insert_position = channel_children.index(last_build_date) + 1
        channel.insert(insert_position, item)
    else:
        channel.append(item)
