import logging
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from typing import ClassVar

import scrapy
import scrapy.core.scheduler
from pydantic import ValidationError
from scrapy import Request
from scrapy.http import Response, XmlResponse

from pazufa_scraper_be.pardok import GesetzVorgang
from pazufa_scraper_be.spiders.utils import convert_element_to_dict

logger = logging.getLogger(__name__)


class GesetzVorgangSpider(scrapy.Spider):
    """A Scrapy spider for scraping process ('Vorgang') documents from the Berlin Parliament."""

    name = "gesetz-vorgang"
    allowed_domains: ClassVar[list[str]] = ["parlament-berlin.de"]
    start_url_template = "https://www.parlament-berlin.de/opendata/pardok-wp{}.xml"

    async def start(self) -> AsyncGenerator:
        """Yield the initial request for the pardok XML feed."""
        yield Request(url=self.start_url_template.format(self.crawler.settings.getint("WAHLPERIODE")))

    def parse(self, response: Response) -> Generator[dict | GesetzVorgang]:  # ty: ignore[invalid-mutable-override]
        """Parse the XML feed response into GesetzVorgang items or error dicts."""
        if not isinstance(response, XmlResponse):
            msg = f"Expecting {XmlResponse} but got {type(response)}."
            raise TypeError(msg)

        cache_dir = Path(self.crawler.settings.get("CACHE_DIR")) / str(self.crawler.settings.getint("WAHLPERIODE")) / "feeds"
        feed_file = cache_dir / f"{response.selector.xpath('/Export').attrib.get('aktualisiert')}.xml"

        if not feed_file.exists():
            logger.debug("Writing feed file to %s", feed_file)
            cache_dir.mkdir(parents=True, exist_ok=True)
            feed_file.write_text(response.text)

        gesetz_vorgang_dicts = [convert_element_to_dict(x) for x in response.selector.xpath("/Export/Vorgang[./VTyp[text() = 'Gesetz']]")]

        for gesetz_vorgang_dict in gesetz_vorgang_dicts:
            try:
                gesetz_vorgang = GesetzVorgang(**gesetz_vorgang_dict)
                yield gesetz_vorgang

            except ValidationError as error:
                yield {"dict": gesetz_vorgang_dict, "error": error}
