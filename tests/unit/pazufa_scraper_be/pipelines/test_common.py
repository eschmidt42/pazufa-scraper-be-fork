from unittest.mock import patch

import pytest
from scrapy import Spider
from scrapy.crawler import Crawler
from scrapy.settings import Settings
from scrapy.statscollectors import StatsCollector

from pazufa_scraper_be.pipelines.common import (
    BasePipeline,
    StatsPipeline,
    StatsReporter,
    get_wahlperiode,
)
from pazufa_scraper_be.pipelines.stats_counter import DokumentCounter

WAHLPERIODE = 19


class ConcreteBasePipeline(BasePipeline):
    """Concrete pipeline for testing the abstract base class."""

    def init(self) -> None:
        """Mark the test pipeline as initialized."""
        self.initialized = True


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


def test__base_pipeline_from_crawler_initializes_pipeline() -> None:
    """from_crawler creates a pipeline and passes through the crawler."""
    crawler = make_crawler({"WAHLPERIODE": WAHLPERIODE})

    pipeline = ConcreteBasePipeline.from_crawler(crawler)

    assert pipeline.crawler is crawler
    assert pipeline.wahlperiode == WAHLPERIODE
    assert pipeline.initialized is True


def test__base_pipeline_uses_scrapy_default_for_missing_wahlperiode() -> None:
    """Construction uses Scrapy's zero default when WAHLPERIODE is missing."""
    pipeline = ConcreteBasePipeline(make_crawler())

    assert pipeline.wahlperiode == 0


def test__base_pipeline_raises_when_wahlperiode_is_none() -> None:
    """Construction fails when the settings object returns None."""
    crawler = make_crawler()
    with patch.object(crawler.settings, "getint", return_value=None), pytest.raises(ValueError, match="Missing WAHLPERIODE"):
        ConcreteBasePipeline(crawler)


def test__stats_pipeline_increments_enum_and_string_counters() -> None:
    """StatsPipeline supports StatsCounter values and literal keys."""
    crawler = make_crawler({"WAHLPERIODE": WAHLPERIODE})
    stats = StatsCollector(crawler)
    crawler.stats = stats
    pipeline = StatsPipeline(crawler)

    with patch.object(StatsCollector, "inc_value") as increment:
        pipeline.increment_stats(DokumentCounter.CACHE_HIT)
        pipeline.increment_stats("custom/key")

    increment.assert_any_call(DokumentCounter.CACHE_HIT.value)
    increment.assert_any_call("custom/key")


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
