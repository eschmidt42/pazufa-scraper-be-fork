from unittest.mock import patch

import pytest
from scrapy import Spider
from scrapy.crawler import Crawler
from scrapy.settings import Settings
from scrapy.statscollectors import StatsCollector

from pazufa_scraper_be.pipelines._support.common import (
    StatsReporter,
    get_wahlperiode,
)
from pazufa_scraper_be.pipelines.stats_counter import DokumentCounter

WAHLPERIODE = 19


def make_crawler(settings: dict | None = None, stats: StatsCollector | None = None) -> Crawler:
    """Create a minimal crawler double."""
    crawler = Crawler(Spider, Settings(settings or {}))
    crawler.stats = stats or StatsCollector(crawler)
    return crawler


def test_get_wahlperiode_returns_configured_value() -> None:
    """The configured Wahlperiode setting is returned."""
    assert get_wahlperiode(make_crawler({"WAHLPERIODE": WAHLPERIODE})) == WAHLPERIODE


def test_get_wahlperiode_uses_scrapy_default_when_setting_is_missing() -> None:
    """Scrapy's default is returned when WAHLPERIODE is absent."""
    assert get_wahlperiode(make_crawler()) == 0


def test_get_wahlperiode_raises_when_setting_is_none() -> None:
    """A None setting raises a clear error."""
    crawler = make_crawler()
    with patch.object(crawler.settings, "getint", return_value=None), pytest.raises(ValueError, match="Missing WAHLPERIODE"):
        get_wahlperiode(crawler)


def test_stats_reporter_increments_enum_and_string_counters() -> None:
    """StatsReporter increments counters identified by enum values or literal keys."""
    stats = StatsCollector(make_crawler())
    reporter = StatsReporter(stats)

    reporter.increment(DokumentCounter.CACHE_HIT)
    reporter.increment(DokumentCounter.CACHE_HIT)
    reporter.increment("custom/key")

    assert reporter.get_value(DokumentCounter.CACHE_HIT.value) == 2
    assert reporter.get_value("custom/key") == 1


def test_stats_reporter_get_value_returns_value_and_default() -> None:
    """StatsReporter returns stored values and the requested default for missing keys."""
    stats = StatsCollector(make_crawler())
    reporter = StatsReporter(stats)
    stats.set_value("existing/key", "value")

    assert reporter.get_value("existing/key") == "value"
    assert reporter.get_value("missing/key") is None
    assert reporter.get_value("missing/key", 0) == 0
