from pathlib import Path

from lxml import etree
from scrapy import Selector
from scrapy.http import XmlResponse
from scrapy.settings import Settings

from pazufa_scraper_be.spiders.utils import convert_element_to_dict, store_feed


def test_convert_element_to_dict_handles_nested_repeated_and_namespaced_elements() -> None:
    """Converts nested XML, repeated tags, attributes, and namespace-qualified tags."""
    node = etree.fromstring(
        b"""<root id="root">
            <item>first</item>
            <item>second</item>
            <group><child>nested</child></group>
            <ns:entry xmlns:ns="https://example.com/ns">value</ns:entry>
        </root>"""
    )

    assert convert_element_to_dict(node) == {
        "id": "root",
        "item": ["first", "second"],
        "group": {"child": "nested"},
        "entry": "value",
    }


def test_convert_element_to_dict_accepts_selector() -> None:
    """Converts the root of a Scrapy XML selector."""
    selector = Selector(text="<root><name>Berlin</name></root>", type="xml")

    assert convert_element_to_dict(selector) == {"name": "Berlin"}


def test_convert_element_to_dict_can_omit_attributes() -> None:
    """Omits XML attributes when attributes is false."""
    node = etree.fromstring(b'<root id="root"><child code="x">value</child></root>')

    assert convert_element_to_dict(node, attributes=False) == {"child": "value"}


def test_store_feed_writes_feed_to_period_cache_directory(tmp_path: Path) -> None:
    """Writes feed content under the configured period and update timestamp."""
    response = XmlResponse(
        url="https://example.com/feed.xml",
        body=b'<Export aktualisiert="2024-05-10T12:30:00"><item>value</item></Export>',
        encoding="utf-8",
    )
    settings = Settings({"CACHE_DIR": str(tmp_path), "WAHLPERIODE": 19})

    store_feed(response, settings)

    feed_file = tmp_path / "19" / "feeds" / "2024-05-10T12:30:00.xml"
    assert feed_file.read_text() == response.text


def test_store_feed_does_not_overwrite_existing_feed(tmp_path: Path) -> None:
    """Preserves an existing feed file with the same update timestamp."""
    settings = Settings({"CACHE_DIR": str(tmp_path), "WAHLPERIODE": 19})
    feed_file = tmp_path / "19" / "feeds" / "2024-05-10T12:30:00.xml"
    feed_file.parent.mkdir(parents=True)
    feed_file.write_text("original feed")
    response = XmlResponse(
        url="https://example.com/feed.xml",
        body=b'<Export aktualisiert="2024-05-10T12:30:00"><item>changed</item></Export>',
        encoding="utf-8",
    )

    store_feed(response, settings)

    assert feed_file.read_text() == "original feed"
