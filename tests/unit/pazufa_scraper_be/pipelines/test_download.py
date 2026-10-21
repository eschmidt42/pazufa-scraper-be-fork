import asyncio
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import HttpUrl
from scrapy import Spider
from scrapy.crawler import Crawler
from scrapy.http import Response
from scrapy.http.request import NO_CALLBACK
from scrapy.settings import Settings
from scrapy.statscollectors import StatsCollector

from pazufa_scraper_be.cache import Cache, Key
from pazufa_scraper_be.constants import DOCUMENT_CHECK_MODIFIED_EVERY_DAYS
from pazufa_scraper_be.pardok import GesetzVorgang
from pazufa_scraper_be.pipelines.documents.download_and_cache_documents import (
    LAST_MODIFIED_TIME_FORMAT,
    DownloadAndCacheDocuments,
    _fetch_last_modified,
    _is_recheck_due,
    _reset_cache_if_file_got_modified,
)
from pazufa_scraper_be.pipelines.stats_counter import DokumentCounter

DOCUMENT_URL = HttpUrl("https://example.com/doc123.pdf")
LAST_MODIFIED_HEADER = "Fri, 21 Oct 2022 07:28:00 GMT"


@pytest.fixture
def download_engine() -> MagicMock:
    """Create a crawler engine with a mocked asynchronous download method."""
    engine = MagicMock()
    engine.download_async = AsyncMock()
    return engine


@pytest.fixture
def download_pipeline(tmp_path: Path, download_engine: MagicMock) -> DownloadAndCacheDocuments:
    """Create a download pipeline with a temporary cache and mocked engine."""
    crawler = Crawler(Spider, Settings({"WAHLPERIODE": 19, "CACHE_DIR": tmp_path}))
    crawler.stats = StatsCollector(crawler)
    crawler.engine = download_engine
    return DownloadAndCacheDocuments(crawler)


@pytest.fixture
def download_item(base_vorgang_data: dict[str, Any], plpr_data: dict[str, Any]) -> GesetzVorgang:
    """Create a Vorgang with one associated document URL."""
    return GesetzVorgang.model_validate({**base_vorgang_data, "Dokument": [{**plpr_data, "LokURL": str(DOCUMENT_URL)}]})


def _item_cache(pipeline: DownloadAndCacheDocuments, item: GesetzVorgang) -> Cache:
    document = item.dokumente[0]
    assert document.lok_url is not None
    return pipeline.get_cache(document=document, document_url=document.lok_url)


@pytest.mark.parametrize(
    ("last_check_age_days", "download_age_days", "expected"),
    [
        (None, DOCUMENT_CHECK_MODIFIED_EVERY_DAYS + 1, True),
        (DOCUMENT_CHECK_MODIFIED_EVERY_DAYS + 1, DOCUMENT_CHECK_MODIFIED_EVERY_DAYS + 1, True),
        (1, DOCUMENT_CHECK_MODIFIED_EVERY_DAYS + 1, False),
        (None, 1, False),
    ],
)
def test_is_recheck_due(
    last_check_age_days: int | None,
    download_age_days: int,
    expected: bool,
) -> None:
    """Rechecks require both the last check and original download to be old enough."""
    now = datetime.now(UTC)
    last_check_time = now - timedelta(days=last_check_age_days) if last_check_age_days is not None else None
    download_time = now - timedelta(days=download_age_days)

    assert _is_recheck_due(last_check_time, download_time) is expected


def test_fetch_last_modified_returns_utc_datetime() -> None:
    """A HEAD response's Last-Modified header is parsed and normalized to UTC."""
    engine = MagicMock()
    engine.download_async = AsyncMock(return_value=Response(url=str(DOCUMENT_URL), headers={"Last-Modified": LAST_MODIFIED_HEADER}))

    result = asyncio.run(_fetch_last_modified(DOCUMENT_URL, engine))

    call = engine.download_async.await_args
    assert call is not None
    request = call.args[0]
    assert request.method == "HEAD"
    assert request.callback is NO_CALLBACK
    assert result == datetime.strptime(LAST_MODIFIED_HEADER, LAST_MODIFIED_TIME_FORMAT).replace(tzinfo=UTC)


def test_fetch_last_modified_returns_none_without_header() -> None:
    """A HEAD response without Last-Modified does not produce a timestamp."""
    engine = MagicMock()
    engine.download_async = AsyncMock(return_value=Response(url=str(DOCUMENT_URL)))

    assert asyncio.run(_fetch_last_modified(DOCUMENT_URL, engine)) is None


def test_reset_cache_if_file_got_modified_returns_false_without_download_time(tmp_path: Path) -> None:
    """A cache without a recorded download time is not checked remotely."""
    cache = Cache(base_dir=tmp_path, name="document")
    engine = MagicMock()
    engine.download_async = AsyncMock()

    result = asyncio.run(_reset_cache_if_file_got_modified(cache, DOCUMENT_URL, engine))

    assert result is False
    engine.download_async.assert_not_awaited()


def test_reset_cache_if_file_got_modified_records_check_without_last_modified(tmp_path: Path) -> None:
    """A due recheck without a Last-Modified header updates the check timestamp only."""
    cache = Cache(base_dir=tmp_path, name="document")
    cache[Key.DOWNLOAD_TIME] = datetime.now(UTC) - timedelta(days=DOCUMENT_CHECK_MODIFIED_EVERY_DAYS + 1)
    engine = MagicMock()
    engine.download_async = AsyncMock(return_value=Response(url=str(DOCUMENT_URL)))

    result = asyncio.run(_reset_cache_if_file_got_modified(cache, DOCUMENT_URL, engine))

    assert result is False
    assert cache.get_last_checked() is not None
    assert cache.get_timestamp(Key.DOWNLOAD_TIME) is not None


def test_download_and_cache_stores_document_and_metadata(
    download_item: GesetzVorgang,
    download_pipeline: DownloadAndCacheDocuments,
    download_engine: MagicMock,
) -> None:
    """A successful cache miss stores document bytes, URL, timestamps, and stats."""
    response = Response(
        url=str(DOCUMENT_URL),
        headers={"Last-Modified": LAST_MODIFIED_HEADER},
        body=b"document contents",
    )
    download_engine.download_async.return_value = response

    result = asyncio.run(download_pipeline.process_item(download_item))

    cache = _item_cache(download_pipeline, download_item)
    assert result is download_item
    assert cache[Key.DOCUMENT] == b"document contents"
    assert cache[Key.URL] == str(DOCUMENT_URL)
    assert cache.get_timestamp(Key.DOWNLOAD_TIME).tzinfo == UTC
    assert cache[Key.LAST_MODIFIED] == datetime.strptime(LAST_MODIFIED_HEADER, LAST_MODIFIED_TIME_FORMAT).replace(tzinfo=UTC)
    assert download_engine.download_async.await_count == 1
    call = download_engine.download_async.await_args
    assert call is not None
    request = call.args[0]
    assert request.method == "GET"
    assert request.callback is NO_CALLBACK
    assert download_pipeline.stats.get_value(DokumentCounter.CACHE_MISS.value) == 1
    assert download_pipeline.stats.get_value(DokumentCounter.DOWNLOAD_DONE.value) == 1


def test_download_and_cache_skips_cached_document(
    download_item: GesetzVorgang,
    download_pipeline: DownloadAndCacheDocuments,
    download_engine: MagicMock,
) -> None:
    """A cached document whose recheck is not due counts as a cache hit."""
    cache = _item_cache(download_pipeline, download_item)
    cache[Key.DOCUMENT] = b"cached contents"
    cache[Key.DOWNLOAD_TIME] = datetime.now(UTC)

    result = asyncio.run(download_pipeline.process_item(download_item))

    assert result is download_item
    download_engine.download_async.assert_not_awaited()
    assert download_pipeline.stats.get_value(DokumentCounter.CACHE_HIT.value) == 1


def test_download_and_cache_redownloads_modified_document(
    download_item: GesetzVorgang,
    download_pipeline: DownloadAndCacheDocuments,
    download_engine: MagicMock,
) -> None:
    """A changed Last-Modified header resets the old cache and downloads fresh bytes."""
    cache = _item_cache(download_pipeline, download_item)
    cache[Key.DOCUMENT] = b"old contents"
    cache[Key.DOWNLOAD_TIME] = datetime.now(UTC) - timedelta(days=DOCUMENT_CHECK_MODIFIED_EVERY_DAYS + 1)
    cache[Key.LAST_MODIFIED] = datetime.strptime(LAST_MODIFIED_HEADER, LAST_MODIFIED_TIME_FORMAT).replace(tzinfo=UTC)
    modified_header = "Mon, 21 Oct 2024 07:28:00 GMT"
    download_engine.download_async.side_effect = [
        Response(url=str(DOCUMENT_URL), headers={"Last-Modified": modified_header}),
        Response(url=str(DOCUMENT_URL), headers={"Last-Modified": modified_header}, body=b"new contents"),
    ]

    asyncio.run(download_pipeline.process_item(download_item))

    assert cache[Key.DOCUMENT] == b"new contents"
    assert cache[Key.LAST_MODIFIED] == datetime.strptime(modified_header, LAST_MODIFIED_TIME_FORMAT).replace(tzinfo=UTC)
    assert download_engine.download_async.await_count == 2
    assert download_pipeline.stats.get_value(DokumentCounter.CACHE_RESET.value) == 1
    assert download_pipeline.stats.get_value(DokumentCounter.DOWNLOAD_DONE.value) == 1


def test_download_and_cache_skips_document_from_another_wahlperiode(
    base_vorgang_data: dict,
    plpr_data: dict,
    download_pipeline: DownloadAndCacheDocuments,
    download_engine: MagicMock,
) -> None:
    """Documents from another Wahlperiode are not cached or downloaded."""
    item = GesetzVorgang.model_validate({**base_vorgang_data, "Dokument": [{**plpr_data, "Wp": 18}]})

    asyncio.run(download_pipeline.process_item(item))

    download_engine.download_async.assert_not_awaited()
    assert download_pipeline.stats.get_value(DokumentCounter.CACHE_MISS.value) is None


def test_download_and_cache_counts_incorrect_response(
    download_item: GesetzVorgang,
    download_pipeline: DownloadAndCacheDocuments,
    download_engine: MagicMock,
) -> None:
    """A non-Response download result is counted and not cached."""
    download_engine.download_async.return_value = object()

    asyncio.run(download_pipeline.process_item(download_item))

    assert download_pipeline.stats.get_value(DokumentCounter.DOWNLOAD_FAILED_INCORRECT_RESPONSE.value) == 1
    assert Key.DOCUMENT not in _item_cache(download_pipeline, download_item)


def test_download_and_cache_counts_incorrect_status(
    download_item: GesetzVorgang,
    download_pipeline: DownloadAndCacheDocuments,
    download_engine: MagicMock,
) -> None:
    """A non-200 download response is counted and not cached."""
    download_engine.download_async.return_value = Response(url=str(DOCUMENT_URL), status=HTTPStatus.NOT_FOUND)

    asyncio.run(download_pipeline.process_item(download_item))

    assert download_pipeline.stats.get_value(DokumentCounter.DOWNLOAD_FAILED_INCORRECT_STATUS.value) == 1
    assert Key.DOCUMENT not in _item_cache(download_pipeline, download_item)
