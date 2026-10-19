from typing import Self

from scrapy.exceptions import DropItem

from pazufa_scraper_be.pardok import GesetzVorgang
from pazufa_scraper_be.pipelines._base import StatsPipeline
from pazufa_scraper_be.pipelines.stats_counter import VorgangCounter


class HandleErrors(StatsPipeline):
    """Pipeline that reports parse errors and drops malformed items."""

    def process_item(self: Self, item: dict | GesetzVorgang) -> GesetzVorgang:
        """Pass through valid GesetzVorgang items; raise DropItem for error dicts."""
        if isinstance(item, GesetzVorgang):
            self.increment_stats(VorgangCounter.TOTAL)
            return item

        if isinstance(item, dict):
            self.increment_stats(VorgangCounter.DROP_INCORRECT)
            msg = f"Could not properly parse Vorgang '{item['dict']['VID']}'."
            raise DropItem(msg)

        msg = "This should not happen."
        raise DropItem(msg)
