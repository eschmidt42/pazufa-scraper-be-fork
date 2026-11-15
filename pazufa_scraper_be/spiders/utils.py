import logging
from pathlib import Path

from lxml.etree import Element, QName
from scrapy import Selector
from scrapy.http import XmlResponse
from scrapy.settings import Settings

logger = logging.getLogger(__name__)


def convert_element_to_dict(node: Element | Selector, *, attributes: bool = True) -> dict:
    """Recursively convert an lxml Element or Scrapy Selector to a plain dict.

    Reference: https://gist.github.com/jacobian/795571
    """
    node = node if isinstance(node, Element) else node.root

    result = {}
    if attributes:
        for item in node.attrib.items():
            key, result[key] = item

    for element in node.iterchildren():
        # Remove namespace prefix
        key = QName(element).localname

        # Process element as tree element if the inner XML contains non-whitespace content
        value = element.text if element.text and element.text.strip() else convert_element_to_dict(element)

        if key in result:
            if type(result[key]) is list:
                result[key].append(value)

            else:
                result[key] = [result[key], value]

        else:
            result[key] = value

    return result


def store_feed(response: XmlResponse, settings: Settings) -> None:
    """Stores the feed as xml file on disk."""
    cache_dir = Path(settings.get("CACHE_DIR")) / str(settings.getint("WAHLPERIODE")) / "feeds"
    feed_file = cache_dir / f"{response.selector.xpath('/Export').attrib.get('aktualisiert')}.xml"

    if not feed_file.exists():
        logger.debug("Writing feed file to %s", feed_file)
        cache_dir.mkdir(parents=True, exist_ok=True)
        feed_file.write_text(response.text)
