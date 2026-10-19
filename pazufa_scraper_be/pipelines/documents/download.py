import logging
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import Self

from pydantic import HttpUrl
from scrapy import Request
from scrapy.core.engine import ExecutionEngine
from scrapy.exceptions import DropItem
from scrapy.http import Response
from scrapy.http.request import NO_CALLBACK

from pazufa_scraper_be.cache import Cache, Key
from pazufa_scraper_be.constants import DOCUMENT_CHECK_MODIFIED_EVERY_DAYS
from pazufa_scraper_be.pardok import GesetzVorgang
from pazufa_scraper_be.pipelines._base import CachePipeline, StatsPipeline
from pazufa_scraper_be.pipelines.stats_counter import DokumentCounter

logger = logging.getLogger(__name__)

LAST_MODIFIED_TIME_FORMAT = "%a, %d %b %Y %H:%M:%S %Z"


async def _reset_cache_if_file_got_modified(cache: Cache, dokument_url: HttpUrl, engine: ExecutionEngine) -> bool:
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


def _is_recheck_due(last_check_time: datetime | None, download_time: datetime) -> bool:
    interval = timedelta(days=DOCUMENT_CHECK_MODIFIED_EVERY_DAYS)
    check_due = last_check_time is None or (datetime.now(UTC) - last_check_time) >= interval
    grace_period_done = (datetime.now(UTC) - download_time) >= interval
    return check_due and grace_period_done


async def _fetch_last_modified(dokument_url: HttpUrl, engine: ExecutionEngine) -> datetime | None:
    request = Request(dokument_url.encoded_string(), method="HEAD", callback=NO_CALLBACK)
    response = await engine.download_async(request)
    header = response.headers.get("Last-Modified")
    if not header:
        return None

    return datetime.strptime(header.decode("utf-8"), LAST_MODIFIED_TIME_FORMAT).astimezone(tz=UTC)


class DownloadAndCacheDocuments(CachePipeline, StatsPipeline):
    """Pipeline that downloads and caches PDF documents for each Vorgang."""

    # TODO(anyone): refactor to reduce complexity
    async def process_item(self: Self, vorgang: GesetzVorgang) -> GesetzVorgang:  # noqa: C901
        """Download and cache all document PDFs for the given Vorgang."""
        if not isinstance(vorgang, GesetzVorgang):
            msg = f"Expected {GesetzVorgang.__name__} object but got {vorgang.__class__.__name__}."
            raise DropItem(msg)

        if self.crawler.engine is None:
            msg = "crawler.engine is None. The crawler seems improperly initialized."
            raise ValueError(msg)

        for dokument in vorgang.dokumente:
            if dokument.wp != self.wahlperiode:
                msg = (
                    f"[{vorgang.id} - {dokument.id}]: Wahlperiode from scraping run ('{self.wahlperiode}') "
                    + f"differs from this document's metadata: '{dokument.wp}'"
                )
                logger.warning(msg)
                continue

            for dokument_url in dokument.all_urls:
                cache = self.get_cache(document=dokument, document_url=dokument_url)

                if Key.DOCUMENT in cache:
                    if await _reset_cache_if_file_got_modified(cache, dokument_url, engine=self.crawler.engine):
                        self.increment_stats(DokumentCounter.CACHE_RESET)

                    else:
                        self.increment_stats(DokumentCounter.CACHE_HIT)
                        continue
                else:
                    self.increment_stats(DokumentCounter.CACHE_MISS)

                download_time = datetime.now(tz=UTC)
                request = Request(dokument_url.encoded_string(), callback=NO_CALLBACK)
                response = await self.crawler.engine.download_async(request)

                if not isinstance(response, Response):
                    self.increment_stats(DokumentCounter.DOWNLOAD_FAILED_INCORRECT_RESPONSE)
                    msg = f"[{vorgang.id} - {dokument.id}]: Expected 'scrapy.Response' but got '{type(response)}'"
                    logger.warning(msg)
                    continue

                if response.status != HTTPStatus.OK:
                    self.increment_stats(DokumentCounter.DOWNLOAD_FAILED_INCORRECT_STATUS)
                    msg = f"[{vorgang.id} - {dokument.id}]: Got {response.status} status code for URL: {response.url}"
                    logger.warning(msg)
                    continue

                if last_modified_header_as_byte := response.headers.get("Last-Modified"):
                    cache[Key.LAST_MODIFIED] = datetime.strptime(last_modified_header_as_byte.decode("utf-8"), LAST_MODIFIED_TIME_FORMAT).astimezone(UTC)

                self.increment_stats(DokumentCounter.DOWNLOAD_DONE)
                cache[Key.URL] = response.url
                cache[Key.DOWNLOAD_TIME] = download_time
                cache[Key.DOCUMENT] = response.body

        return vorgang
