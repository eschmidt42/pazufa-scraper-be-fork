import logging
from collections.abc import AsyncGenerator, Generator
from typing import ClassVar

import scrapy
import scrapy.core.scheduler
from pydantic import ValidationError
from scrapy import Request
from scrapy.http import Response, XmlResponse

from pazufa_scraper_be.pardok import GesetzVorgang
from pazufa_scraper_be.spiders.utils import convert_element_to_dict, store_feed

logger = logging.getLogger(__name__)

ALLOWED_DOMAINS = ["parlament-berlin.de"]
START_URL_TEMPLATE = "https://www.parlament-berlin.de/opendata/pardok-wp{}.xml"


class GesetzVorgangSpider(scrapy.Spider):
    """A Scrapy spider for scraping process ('Vorgang') documents from the Berlin Parliament."""

    name = "gesetz-vorgang"

    allowed_domains: ClassVar[list[str]] = ALLOWED_DOMAINS

    start_url_template = START_URL_TEMPLATE

    async def start(self) -> AsyncGenerator:
        """Yield the initial request for the pardok XML feed."""
        yield Request(url=self.start_url_template.format(self.crawler.settings.getint("WAHLPERIODE")))

    def parse(self, response: Response) -> Generator[dict | GesetzVorgang]:  # ty: ignore[invalid-mutable-override]
        """Parse the XML feed response into GesetzVorgang items or error dicts."""
        if not isinstance(response, XmlResponse):
            msg = f"Expecting {XmlResponse} but got {type(response)}."
            raise TypeError(msg)

        store_feed(response, self.crawler.settings)

        gesetz_vorgang_dicts = [convert_element_to_dict(x) for x in response.selector.xpath("/Export/Vorgang[./VTyp[text() = 'Gesetz']]")]

        for gesetz_vorgang_dict in gesetz_vorgang_dicts:
            try:
                yield GesetzVorgang.model_validate(gesetz_vorgang_dict)

            except ValidationError as error:
                yield {"dict": gesetz_vorgang_dict, "error": error}
