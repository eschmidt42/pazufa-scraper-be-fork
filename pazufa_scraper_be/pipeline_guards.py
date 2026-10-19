from scrapy.crawler import Crawler
from scrapy.exceptions import DropItem

from pazufa_scraper_be.pardok import GesetzVorgang


def vorgang_guard(vorgang: GesetzVorgang) -> None:
    """Guards against unexpected `vorgang` type passed at runtime."""
    if not isinstance(vorgang, GesetzVorgang):
        msg = f"Expected {GesetzVorgang.__name__} object but got {vorgang.__class__.__name__}."
        raise DropItem(msg)


def engine_guard(crawler: Crawler) -> None:
    """Guards against missing crawler engine."""
    if crawler.engine is None:
        msg = "crawler.engine is None. The crawler seems improperly initialized."
        raise ValueError(msg)
