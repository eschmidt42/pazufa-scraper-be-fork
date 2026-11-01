import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import HttpUrl
from scrapy import Spider
from scrapy.crawler import Crawler
from scrapy.settings import Settings
from scrapy.statscollectors import StatsCollector

from pazufa_scraper_be.constants import DOK_BASE_URL
from pazufa_scraper_be.pardok import GesetzVorgang, PlPrDokument
from pazufa_scraper_be.pipelines.common import (
    BasePipeline,
    CachePipeline,
    LLMPipeline,
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


def test__cache_pipeline_raises_when_cache_dir_setting_missing() -> None:
    """Initialization fails when CACHE_DIR setting is missing."""
    crawler = make_crawler({"WAHLPERIODE": WAHLPERIODE})
    with pytest.raises(TypeError, match="Missing CACHE_DIR"):
        CachePipeline(crawler)


def test__cache_pipeline_rejects_unassociated_url(base_vorgang_data: dict[str, Any], tmp_path: Path, plpr_data: dict) -> None:
    """A URL not belonging to the document is not cached."""
    pipeline = CachePipeline(make_crawler({"WAHLPERIODE": WAHLPERIODE, "CACHE_DIR": tmp_path / "cache"}))
    document = PlPrDokument.model_validate(
        {
            **plpr_data,
            "additional_urls": ["https://example.com/additional.pdf"],
        }
    )
    document.set_vorgang(GesetzVorgang.model_validate(base_vorgang_data))

    with pytest.raises(ValueError, match="Did not setup dokument cache because given URL is unknown"):
        pipeline.get_cache(document, HttpUrl("https://example.com/other.pdf"))


def test__cache_pipeline_accepts_additional_url(tmp_path: Path, plpr_data: dict) -> None:
    """Additional document URLs use the same cache path logic."""
    additional_url = HttpUrl(f"{DOK_BASE_URL}/19/19/124.pdf")
    pipeline = CachePipeline(make_crawler({"WAHLPERIODE": WAHLPERIODE, "CACHE_DIR": tmp_path / "cache"}))
    document = PlPrDokument.model_validate({**plpr_data, "additional_urls": [str(additional_url)]})

    result = pipeline.get_cache(document, additional_url)
    assert result


def test__llm_pipeline_without_token_skips_connector(caplog: pytest.LogCaptureFixture) -> None:
    """Without an LLM token, summarization is disabled."""
    with caplog.at_level(logging.INFO):
        pipeline = LLMPipeline(make_crawler({"WAHLPERIODE": WAHLPERIODE}))

    assert pipeline.llm_connector is None
    assert "LLM_TOKEN is not set" in caplog.text


def test__llm_pipeline_requires_model_when_token_is_set() -> None:
    """An LLM token requires a model name."""
    settings = {"WAHLPERIODE": WAHLPERIODE, "LLM_TOKEN": "token"}

    with pytest.raises(ValueError, match="LLM_MODEL setting is required"):
        LLMPipeline(make_crawler(settings))


@pytest.mark.parametrize("timeout", [0, -1])
def test__llm_pipeline_requires_positive_timeout(timeout: int) -> None:
    """LLM timeout must be a positive integer."""
    settings = {"WAHLPERIODE": WAHLPERIODE, "LLM_TOKEN": "token", "LLM_MODEL": "model", "LLM_TIMEOUT": timeout}

    with pytest.raises(ValueError, match="Invalid LLM_TIMEOUT"):
        LLMPipeline(make_crawler(settings))


def test__llm_pipeline_creates_connector_and_configures_litellm() -> None:
    """Configured LLM settings are passed to LLMConnector."""
    settings = {"WAHLPERIODE": WAHLPERIODE, "LLM_TOKEN": "token", "LLM_MODEL": "model", "LLM_TIMEOUT": 30}
    with patch("pazufa_scraper_be.pipelines.common.LLMConnector") as connector:
        pipeline = LLMPipeline(make_crawler(settings))

    assert pipeline.llm_connector is connector.return_value
    connector.assert_called_once_with(model="model", api_key="token", timeout_seconds=30)
