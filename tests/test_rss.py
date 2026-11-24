"""Tests for RSS feed generation."""

import xml.etree.ElementTree as ET

from paper_orator.rss import ATOM_NS, update_rss_feed

FEED = {
    "title": "Test Feed",
    "description": "Desc",
    "link": "https://example.com/feed/feed.xml",
    "base_url": "https://example.com/feed/",
    "language": "en-us",
}


def _items(path):
    return ET.parse(path).getroot().find("channel").findall("item")


def test_creates_feed_with_item(tmp_path):
    feed = tmp_path / "feed.xml"
    update_rss_feed(str(feed), "my-paper", "Some text", 1234, FEED, web_url="https://arxiv.org/x")

    items = _items(feed)
    assert len(items) == 1
    item = items[0]
    assert item.findtext("title") == "My Paper"
    assert item.findtext("link") == "https://arxiv.org/x"
    assert item.findtext("guid") == "https://example.com/feed/my-paper.mp3"
    enclosure = item.find("enclosure")
    assert enclosure.get("length") == "1234"
    assert enclosure.get("type") == "audio/mpeg"


def test_atom_prefix_survives_rewrites(tmp_path):
    feed = tmp_path / "feed.xml"
    update_rss_feed(str(feed), "paper-one", "text", 1, FEED)
    update_rss_feed(str(feed), "paper-two", "text", 1, FEED)

    content = feed.read_text()
    assert "ns0" not in content
    assert 'xmlns:atom="http://www.w3.org/2005/Atom"' in content
    assert "<atom:link" in content
    channel = ET.parse(feed).getroot().find("channel")
    assert len(channel.findall(f"{{{ATOM_NS}}}link")) == 1


def test_newest_item_first(tmp_path):
    feed = tmp_path / "feed.xml"
    update_rss_feed(str(feed), "first", "text", 1, FEED)
    update_rss_feed(str(feed), "second", "text", 1, FEED)
    assert [i.findtext("title") for i in _items(feed)] == ["Second", "First"]


def test_existing_item_skipped_without_force(tmp_path):
    feed = tmp_path / "feed.xml"
    update_rss_feed(str(feed), "paper", "old text", 1, FEED)
    update_rss_feed(str(feed), "paper", "new text", 2, FEED)

    items = _items(feed)
    assert len(items) == 1
    assert items[0].findtext("description") == "old text"


def test_existing_item_updated_with_force(tmp_path):
    feed = tmp_path / "feed.xml"
    update_rss_feed(str(feed), "a", "text", 1, FEED)
    update_rss_feed(str(feed), "b", "text", 1, FEED)
    update_rss_feed(str(feed), "a", "new text", 99, FEED, force=True)

    items = _items(feed)
    assert [i.findtext("title") for i in items] == ["A", "B"]
    assert items[0].findtext("description") == "new text"
    assert items[0].find("enclosure").get("length") == "99"


def test_long_description_truncated(tmp_path):
    feed = tmp_path / "feed.xml"
    update_rss_feed(str(feed), "p", "x" * 500, 1, FEED)
    description = _items(feed)[0].findtext("description")
    assert description == "x" * 200 + "..."


def test_malformed_feed_is_recreated(tmp_path):
    feed = tmp_path / "feed.xml"
    feed.write_text("<rss><channel>")
    update_rss_feed(str(feed), "p", "text", 1, FEED)
    assert len(_items(feed)) == 1
