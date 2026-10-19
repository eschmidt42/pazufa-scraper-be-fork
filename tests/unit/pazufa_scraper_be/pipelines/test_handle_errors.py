from typing import Any

import pytest
from scrapy import Spider
from scrapy.crawler import Crawler
from scrapy.exceptions import DropItem
from scrapy.settings import Settings
from scrapy.statscollectors import StatsCollector

from pazufa_scraper_be.pardok import GesetzVorgang
from pazufa_scraper_be.pipelines.handle_errors import HandleErrors
from pazufa_scraper_be.pipelines.stats_counter import VorgangCounter


@pytest.fixture
def handle_errors_pipeline() -> HandleErrors:
    """Create a HandleErrors pipeline with a minimal crawler."""
    crawler = Crawler(Spider, Settings({"WAHLPERIODE": 19}))
    crawler.stats = StatsCollector(crawler)
    return HandleErrors(crawler)


def test_handle_errors_passes_through_vorgang_and_increments_total(
    base_vorgang_data: dict[str, Any],
    handle_errors_pipeline: HandleErrors,
) -> None:
    """A valid Vorgang passes through and is counted."""
    item = GesetzVorgang.model_validate(base_vorgang_data)

    result = handle_errors_pipeline.process_item(item)

    assert result is item
    assert handle_errors_pipeline.stats.get_value(VorgangCounter.TOTAL.value) == 1


def test_handle_errors_drops_error_dict_and_increments_incorrect(
    base_vorgang_data: dict[str, Any],
    handle_errors_pipeline: HandleErrors,
) -> None:
    """An error dictionary is dropped with the malformed Vorgang's VID."""
    item = {"dict": base_vorgang_data}

    with pytest.raises(DropItem, match="Could not properly parse Vorgang 'vorg123'"):
        handle_errors_pipeline.process_item(item)

    assert handle_errors_pipeline.stats.get_value(VorgangCounter.DROP_INCORRECT.value) == 1


def test_handle_errors_drops_unexpected_item_without_incrementing_stats(
    handle_errors_pipeline: HandleErrors,
) -> None:
    """An unexpected item type is dropped without changing the counters."""
    item: Any = "unexpected"

    with pytest.raises(DropItem, match="This should not happen"):
        handle_errors_pipeline.process_item(item)

    assert handle_errors_pipeline.stats.get_stats() == {}
