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
from pazufa_scraper_be.pipelines._base import (
    ApiPipeline,
    BasePipeline,
    CachePipeline,
    LLMPipeline,
    StatsPipeline,
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


def test__api_pipeline_requires_scraper_uuid() -> None:
    """ApiPipeline requires the scraper UUID setting."""
    with pytest.raises(ValueError, match="Missing SCRAPER_UUID"):
        ApiPipeline(make_crawler({"WAHLPERIODE": WAHLPERIODE}))


def test__api_pipeline_requires_api_url_when_token_is_set() -> None:
    """An API token requires an API URL."""
    with pytest.raises(ValueError, match="API_URL setting is required"):
        ApiPipeline(make_crawler({"WAHLPERIODE": WAHLPERIODE, "API_TOKEN": "token", "SCRAPER_UUID": "uuid"}))


def test__api_pipeline_without_token_has_no_client(caplog: pytest.LogCaptureFixture) -> None:
    """Without a token, API submission is disabled."""
    with caplog.at_level(logging.INFO):
        pipeline = ApiPipeline(make_crawler({"WAHLPERIODE": WAHLPERIODE, "SCRAPER_UUID": "uuid"}))

    assert pipeline.get_client() is None
    assert "API_TOKEN is not set" in caplog.text


def test__api_pipeline_creates_authenticated_client() -> None:
    """Configured API credentials are passed to AuthenticatedClient."""
    settings = {"WAHLPERIODE": WAHLPERIODE, "API_URL": "https://api.example", "API_TOKEN": "test-value", "SCRAPER_UUID": "uuid"}
    with patch("pazufa_scraper_be.pipelines._base.AuthenticatedClient") as client:
        pipeline = ApiPipeline(make_crawler(settings))

        result = pipeline.get_client()

    assert result is client.return_value
    client.assert_called_once()
    assert client.call_args.kwargs == {
        "base_url": "https://api.example",
        "token": "test-value",
        "prefix": "",
        "auth_header_name": "X-API-Key",
    }


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
    with patch("pazufa_scraper_be.pipelines._base.LLMConnector") as connector:
        pipeline = LLMPipeline(make_crawler(settings))

    assert pipeline.llm_connector is connector.return_value
    connector.assert_called_once_with(model="model", api_key="token", timeout_seconds=30)
