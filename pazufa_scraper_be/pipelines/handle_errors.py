from typing import Self

from scrapy.crawler import Crawler
from scrapy.exceptions import DropItem

from pazufa_scraper_be.pardok import GesetzVorgang
from pazufa_scraper_be.pipelines._support.common import StatsReporter
from pazufa_scraper_be.pipelines._support.stats_counter import VorgangCounter


class HandleErrors:
    """Pipeline that reports parse errors and drops malformed items."""

    _stats: StatsReporter

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "HandleErrors":
        """Construct from crawler^^."""
        return cls(stats=StatsReporter(crawler.stats))

    def __init__(self, stats: StatsReporter) -> None:
        """Initialize the pipeline with its stats reporter."""
        self._stats = stats

    def process_item(self: Self, item: dict | GesetzVorgang) -> GesetzVorgang:
        """Pass through valid GesetzVorgang items; raise DropItem for error dicts."""
        if isinstance(item, GesetzVorgang):
            self._stats.increment(VorgangCounter.TOTAL)
            return item

        if isinstance(item, dict):
            self._stats.increment(VorgangCounter.DROP_INCORRECT)
            msg = f"Could not properly parse Vorgang '{item['dict']['VID']}'."
            raise DropItem(msg)

        msg = "This should not happen."
        raise DropItem(msg)
