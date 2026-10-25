import logging
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import Self

from pydantic import HttpUrl
from scrapy import Request
from scrapy.core.engine import ExecutionEngine
from scrapy.crawler import Crawler
from scrapy.http import Response
from scrapy.http.request import NO_CALLBACK

from pazufa_scraper_be.cache import Cache, Key
from pazufa_scraper_be.constants import DOCUMENT_CHECK_MODIFIED_EVERY_DAYS
from pazufa_scraper_be.pardok import AnyGesetzDokument, GesetzVorgang
from pazufa_scraper_be.pipeline_guards import engine_guard, vorgang_guard
from pazufa_scraper_be.pipelines._base import CachePipeline, StatsPipeline
from pazufa_scraper_be.pipelines.stats_counter import DokumentCounter

logger = logging.getLogger(__name__)

LAST_MODIFIED_TIME_FORMAT = "%a, %d %b %Y %H:%M:%S %Z"


def _is_recheck_due(last_check_time: datetime | None, download_time: datetime) -> bool:
    interval = timedelta(days=DOCUMENT_CHECK_MODIFIED_EVERY_DAYS)
    now = datetime.now(UTC)
    check_due = last_check_time is None or (now - last_check_time) >= interval
    grace_period_done = (now - download_time) >= interval
    return check_due and grace_period_done


async def _fetch_last_modified(dokument_url: HttpUrl, engine: ExecutionEngine) -> datetime | None:
    request = Request(dokument_url.encoded_string(), method="HEAD", callback=NO_CALLBACK)
    response = await engine.download_async(request)
    header = response.headers.get("Last-Modified")
    if not header:
        return None

    return datetime.strptime(header.decode("utf-8"), LAST_MODIFIED_TIME_FORMAT).replace(tzinfo=UTC)


async def _reset_cache_if_file_got_modified(cache: Cache, dokument_url: HttpUrl, engine: ExecutionEngine) -> bool:
    if not cache.has_entry(key=Key.DOWNLOAD_TIME):
        return False

    download_time = cache.get_timestamp(Key.DOWNLOAD_TIME)
    if not download_time:
        return False

    if not _is_recheck_due(cache.get_last_checked(), download_time):
        return False

    last_modified = await _fetch_last_modified(dokument_url, engine)
    cache.update_last_checked()

    if last_modified is None or cache[Key.LAST_MODIFIED] == last_modified:
        return False

    cache.reset()
    return True


async def download_document(dokument_url: HttpUrl, crawler: Crawler) -> tuple[datetime, Response]:
    """Download a single document."""
    downloaded_at = datetime.now(tz=UTC)
    request = Request(dokument_url.encoded_string(), callback=NO_CALLBACK)
    response = await crawler.engine.download_async(request)
    return downloaded_at, response


def _is_in_current_wahlperiode(wahlperiode: int, vorgang: GesetzVorgang, dokument: AnyGesetzDokument) -> bool:

    if dokument.wp != wahlperiode:
        msg = f"[{vorgang.id} - {dokument.id}]: Wahlperiode from scraping run ('{wahlperiode}') " + f"differs from this document's metadata: '{dokument.wp}'"
        logger.warning(msg)
        return False
    return True


class DownloadDocuments(CachePipeline, StatsPipeline):
    """Pipeline that downloads and caches PDF documents for each Vorgang."""

    async def process_item(self: Self, vorgang: GesetzVorgang) -> GesetzVorgang:
        """Download and cache all document PDFs for the given Vorgang."""
        vorgang_guard(vorgang)
        engine_guard(self.crawler)

        for dokument in vorgang.dokumente:
            if not _is_in_current_wahlperiode(self.wahlperiode, vorgang, dokument):
                continue

            for dokument_url in dokument.all_urls:
                await self._process_url(vorgang, dokument, dokument_url)

        return vorgang

    async def _process_url(self, vorgang: GesetzVorgang, dokument: AnyGesetzDokument, dokument_url: HttpUrl) -> None:
        """Process a single url for a given `vorgang` and `dokument`."""
        cache = self.get_cache(dokument, dokument_url)

        if await self._should_skip_cached_case(cache, dokument_url):
            return

        download = await self._download_valid_response(vorgang, dokument, dokument_url)

        if download is None:
            return

        downloaded_at, response = download
        self._store_download(cache, response, downloaded_at)

    async def _should_skip_cached_case(self, cache: Cache, dokument_url: HttpUrl) -> bool:

        if Key.DOCUMENT not in cache:
            self.increment_stats(DokumentCounter.CACHE_MISS)
            return False

        reset = await _reset_cache_if_file_got_modified(cache, dokument_url, engine=self.crawler.engine)

        if reset:
            self.increment_stats(DokumentCounter.CACHE_RESET)
            return False

        self.increment_stats(DokumentCounter.CACHE_HIT)
        return True

    async def _download_valid_response(self, vorgang: GesetzVorgang, dokument: AnyGesetzDokument, dokument_url: HttpUrl) -> tuple[datetime, Response] | None:
        downloaded_at, response = await download_document(dokument_url, self.crawler)

        if not isinstance(response, Response):
            self.increment_stats(DokumentCounter.DOWNLOAD_FAILED_INCORRECT_RESPONSE)
            msg = f"[{vorgang.id} - {dokument.id}]: Expected 'scrapy.Response' but got '{type(response)}'"
            logger.warning(msg)
            return None

        if response.status != HTTPStatus.OK:
            self.increment_stats(DokumentCounter.DOWNLOAD_FAILED_INCORRECT_STATUS)
            msg = f"[{vorgang.id} - {dokument.id}]: Got {response.status} status code for URL: {response.url}"
            logger.warning(msg)
            return None

        return downloaded_at, response

    def _store_download(self, cache: Cache, response: Response, downloaded_at: datetime) -> None:
        if last_modified_header_as_byte := response.headers.get("Last-Modified"):
            cache[Key.LAST_MODIFIED] = datetime.strptime(last_modified_header_as_byte.decode("utf-8"), LAST_MODIFIED_TIME_FORMAT).replace(tzinfo=UTC)

        self.increment_stats(DokumentCounter.DOWNLOAD_DONE)
        cache[Key.URL] = response.url
        cache[Key.DOWNLOAD_TIME] = downloaded_at
        cache[Key.DOCUMENT] = response.body
