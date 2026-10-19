import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import HttpUrl
from scrapy import Spider
from scrapy.crawler import Crawler
from scrapy.exceptions import DropItem
from scrapy.settings import Settings
from scrapy.statscollectors import StatsCollector

from pazufa_scraper_be.pardok import GesetzVorgang, PlPrDokument
from pazufa_scraper_be.pardok.url import UrlResolution
from pazufa_scraper_be.pipelines.documents.prepare_document_urls import PrepareDocumentUrls
from pazufa_scraper_be.pipelines.stats_counter import DokumentCounter


@pytest.fixture
def prepare_document_urls_pipeline() -> PrepareDocumentUrls:
    """Create a PrepareDocumentUrls pipeline with a minimal crawler."""
    crawler = Crawler(Spider, Settings({"WAHLPERIODE": 19}))
    crawler.stats = StatsCollector(crawler)
    crawler.engine = MagicMock()
    return PrepareDocumentUrls(crawler)


def test_prepare_document_urls_drops_unexpected_item(
    prepare_document_urls_pipeline: PrepareDocumentUrls,
) -> None:
    """An unexpected item type is dropped."""
    with pytest.raises(DropItem, match="Expected GesetzVorgang object but got str"):
        asyncio.run(prepare_document_urls_pipeline.process_item("unexpected"))  # ty: ignore[invalid-argument-type]


def test_prepare_document_urls_raises_when_engine_is_missing(
    base_vorgang_data: dict[str, Any],
    prepare_document_urls_pipeline: PrepareDocumentUrls,
) -> None:
    """A missing crawler engine indicates an improperly initialized crawler."""
    item = GesetzVorgang.model_validate(base_vorgang_data)

    with (
        patch.object(prepare_document_urls_pipeline, "crawler", MagicMock(engine=None)),
        pytest.raises(ValueError, match=r"crawler\.engine is None"),
    ):
        asyncio.run(prepare_document_urls_pipeline.process_item(item))


def test_prepare_document_urls_normalizes_and_prepares_document_urls(
    base_vorgang_data: dict[str, Any],
    plpr_data: dict[str, Any],
    apr_data: dict[str, Any],
    prepare_document_urls_pipeline: PrepareDocumentUrls,
) -> None:
    """Incorrect URLs are corrected and missing/variant protocol URLs are prepared."""
    plpr_data = {**plpr_data, "DokNr": "19/2", "LokURL": "https://example.com/iso/h19-076-plpr.pdf"}
    missing_url_plpr_data = {**plpr_data, "DBID": "missing-url", "LokURL": None}
    apr_data = {**apr_data, "LokURL": "https://example.com/doc123-wp.pdf"}
    item = GesetzVorgang.model_validate(
        {
            **base_vorgang_data,
            "Dokument": [plpr_data, missing_url_plpr_data, apr_data],
        }
    )

    with patch(
        "pazufa_scraper_be.pipelines.documents.prepare_document_urls.resolve_document_urls",
        new_callable=AsyncMock,
        return_value=UrlResolution(primary_was_reachable=True, recovered_from=None, pruned=[]),
    ):
        result = asyncio.run(prepare_document_urls_pipeline.process_item(item))

    assert result is item
    corrected_plpr, missing_url_plpr, apr = item.dokumente
    assert isinstance(corrected_plpr, PlPrDokument)
    assert isinstance(missing_url_plpr, PlPrDokument)
    assert str(corrected_plpr.lok_url) == "https://example.com/h/h19-076-plpr.pdf"
    assert str(missing_url_plpr.lok_url) == "https://pardok.parlament-berlin.de/starweb/adis/citat/VT/19/PlenarPr/p19-002-wp.pdf"
    assert str(apr.lok_url) == "https://example.com/doc123-bp.pdf"
    assert [str(url) for url in (apr.additional_urls or [])] == [
        "https://example.com/doc123-ip.pdf",
        "https://example.com/doc123-wp.pdf",
    ]


def test_prepare_document_urls_counts_resolver_results(
    base_vorgang_data: dict[str, Any],
    plpr_data: dict[str, Any],
    prepare_document_urls_pipeline: PrepareDocumentUrls,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Missing, recovered, and pruned resolver outcomes update their counters."""
    documents = [
        {**plpr_data, "DBID": "missing"},
        {**plpr_data, "DBID": "recovered"},
        {**plpr_data, "DBID": "pruned"},
    ]
    item = GesetzVorgang.model_validate({**base_vorgang_data, "Dokument": documents})
    results = [
        UrlResolution(primary_was_reachable=False, recovered_from=None, pruned=[]),
        UrlResolution(primary_was_reachable=False, recovered_from=HttpUrl("https://example.com/recovered.pdf"), pruned=[]),
        UrlResolution(primary_was_reachable=True, recovered_from=None, pruned=[HttpUrl("https://example.com/pruned.pdf")]),
    ]

    with (
        caplog.at_level(logging.WARNING),
        patch(
            "pazufa_scraper_be.pipelines.documents.prepare_document_urls.resolve_document_urls",
            new_callable=AsyncMock,
            side_effect=results,
        ),
    ):
        asyncio.run(prepare_document_urls_pipeline.process_item(item))

    assert prepare_document_urls_pipeline.stats.get_value(DokumentCounter.MISSING_PRIMARY.value) == 1
    assert prepare_document_urls_pipeline.stats.get_value(DokumentCounter.RECOVERED_FROM_ADDITIONAL.value) == 1
    assert prepare_document_urls_pipeline.stats.get_value(DokumentCounter.ADDITIONAL_PRUNED.value) == 1
    assert "[vorg123 - missing]: Missing URL." in caplog.text
