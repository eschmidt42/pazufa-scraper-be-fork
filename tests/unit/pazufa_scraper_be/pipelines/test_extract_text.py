import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from scrapy import Spider
from scrapy.crawler import Crawler
from scrapy.exceptions import DropItem
from scrapy.settings import Settings
from scrapy.statscollectors import StatsCollector

from pazufa_scraper_be.cache import Key
from pazufa_scraper_be.pardok import GesetzVorgang
from pazufa_scraper_be.pipelines.documents.extract_text import (
    ExtractText,
    extract_text_with_ocr_backup,
)
from pazufa_scraper_be.pipelines.stats_counter import TextCounter


@pytest.fixture
def extract_pipeline(tmp_path: Path) -> ExtractText:
    """Create an extraction pipeline with a temporary cache and Scrapy stats."""
    crawler = Crawler(Spider, Settings({"WAHLPERIODE": 19, "CACHE_DIR": tmp_path}))
    crawler.stats = StatsCollector(crawler)
    return ExtractText(crawler)


@pytest.fixture
def extract_item(base_vorgang_data: dict[str, Any], plpr_data: dict[str, Any]) -> GesetzVorgang:
    """Create a Vorgang with one associated document URL."""
    return GesetzVorgang.model_validate({**base_vorgang_data, "Dokument": [plpr_data]})


def _extraction_result(*contents: str) -> SimpleNamespace:
    return SimpleNamespace(results=[SimpleNamespace(pages=[SimpleNamespace(content=content) for content in contents])])


def test_extract_text_joins_pages_without_retrying_ocr() -> None:
    """Page contents are joined with newlines when ordinary extraction succeeds."""
    with patch("pazufa_scraper_be.pipelines.documents.extract_text.xberg.extract", new_callable=AsyncMock) as extract:
        extract.return_value = _extraction_result("First page", "Second page")

        text = asyncio.run(extract_text_with_ocr_backup(b"pdf bytes"))

    assert text == "First page\nSecond page"
    assert extract.await_count == 1
    call = extract.await_args
    assert call is not None
    config = call.kwargs["config"]
    assert config.force_ocr is False


def test_extract_text_retries_with_ocr_only_when_text_is_empty() -> None:
    """An empty ordinary extraction is retried once using OCR."""
    with patch("pazufa_scraper_be.pipelines.documents.extract_text.xberg.extract", new_callable=AsyncMock) as extract:
        extract.side_effect = [_extraction_result(), _extraction_result("OCR text")]

        text = asyncio.run(extract_text_with_ocr_backup(b"pdf bytes"))

    assert text == "OCR text"
    assert extract.await_count == 2
    assert extract.await_args_list[0].kwargs["config"].force_ocr is False
    assert extract.await_args_list[1].kwargs["config"].force_ocr is True


def test_extract_pipeline_normalizes_and_caches_text(
    extract_item: GesetzVorgang,
    extract_pipeline: ExtractText,
) -> None:
    """A cache miss extracts text, removes known control characters, and records stats."""
    document = extract_item.dokumente[0]
    assert document.lok_url is not None
    cache = extract_pipeline.get_cache(document, document.lok_url)
    cache[Key.DOCUMENT] = b"pdf bytes"

    with patch(
        "pazufa_scraper_be.pipelines.documents.extract_text.extract_text_with_ocr_backup",
        new_callable=AsyncMock,
        return_value=" \x02A\x15B\x16C\x18 ",
    ) as extract:
        result = asyncio.run(extract_pipeline.process_item(extract_item))

    assert result is extract_item
    assert cache[Key.TEXT] == "ABC"
    extract.assert_awaited_once_with(document_bytes=b"pdf bytes")
    assert extract_pipeline.stats.get_value(TextCounter.CACHE_MISS.value) == 1
    assert extract_pipeline.stats.get_value(TextCounter.EXTRACT_DONE.value) == 1


def test_extract_pipeline_skips_cached_text(
    extract_item: GesetzVorgang,
    extract_pipeline: ExtractText,
) -> None:
    """A document with cached text is counted as a hit without re-extraction."""
    document = extract_item.dokumente[0]
    assert document.lok_url is not None
    cache = extract_pipeline.get_cache(document, document.lok_url)
    cache[Key.DOCUMENT] = b"pdf bytes"
    cache[Key.TEXT] = "cached text"

    with patch("pazufa_scraper_be.pipelines.documents.extract_text._extract_text", new_callable=AsyncMock) as extract:
        asyncio.run(extract_pipeline.process_item(extract_item))

    extract.assert_not_awaited()
    assert extract_pipeline.stats.get_value(TextCounter.CACHE_HIT.value) == 1


def test_extract_pipeline_counts_and_logs_empty_text(
    extract_item: GesetzVorgang,
    extract_pipeline: ExtractText,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Empty output is logged and counted without adding a text cache entry."""
    document = extract_item.dokumente[0]
    assert document.lok_url is not None
    cache = extract_pipeline.get_cache(document, document.lok_url)
    cache[Key.DOCUMENT] = b"pdf bytes"

    with patch(
        "pazufa_scraper_be.pipelines.documents.extract_text._extract_text",
        new_callable=AsyncMock,
        return_value="",
    ):
        asyncio.run(extract_pipeline.process_item(extract_item))

    assert Key.TEXT not in cache
    assert extract_pipeline.stats.get_value(TextCounter.EXTRACT_FAILED_EMPTY_TEXT.value) == 1
    assert f"[{extract_item.id} - {document.id}]: No text extracted." in caplog.text


def test_extract_pipeline_rejects_non_vorgang(extract_pipeline: ExtractText) -> None:
    """Items of an unexpected type are dropped."""
    invalid_item: Any = object()
    with pytest.raises(DropItem, match="Expected GesetzVorgang object"):
        asyncio.run(extract_pipeline.process_item(invalid_item))
