import logging
from typing import Self

import xberg
from pydantic import HttpUrl
from scrapy.crawler import Crawler
from xberg import ExtractInput, ExtractInputKind

from pazufa_scraper_be.cache import Key
from pazufa_scraper_be.pardok import AnyGesetzDokument, GesetzVorgang
from pazufa_scraper_be.pipeline_guards import gesetzvorgang_guard
from pazufa_scraper_be.pipelines._support.common import DocumentCacheFactory, StatsReporter
from pazufa_scraper_be.pipelines._support.stats_counter import TextCounter
from pazufa_scraper_be.xberg_config import get_xberg_config

logger = logging.getLogger(__name__)


async def _extract_text(extract_input: ExtractInput, *, ocr: bool) -> str:
    extraction_result = await xberg.extract(
        input=extract_input,
        config=get_xberg_config(ocr=ocr),
    )
    extraction_result = extraction_result.results[0]
    return "\n".join([page.content for page in extraction_result.pages or []])


async def extract_text_with_ocr_backup(document_bytes: bytes) -> str:
    """Optionally extract text using OCR."""
    extract_input = ExtractInput(kind=ExtractInputKind.BYTES, bytes=document_bytes)  # ty: ignore[invalid-argument-type] NOTE: This is actually fine and should be a temporary bug

    text = await _extract_text(extract_input, ocr=False)

    if len(text) == 0:
        text = await _extract_text(extract_input, ocr=True)

    return text


def _text_edits(text: str) -> str:
    return (
        text.strip()  # remove leading/trailing spaces
        .replace("\x02", "")  # hyphens (line-breaks with -)
        .replace("\x15", "")
        .replace("\x16", "")
        .replace("\x18", "")  # showed up when bold face Drucksache Nummer could not be extracted
    )


class ExtractText:
    """Pipeline that extracts plain text from cached PDF documents using xberg."""

    _cache_factory: DocumentCacheFactory
    _stats: StatsReporter

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "ExtractText":
        """Create the pipeline with dependencies initialized from the crawler."""
        return cls(cache_factory=DocumentCacheFactory.from_crawler(crawler), stats=StatsReporter(crawler.stats))

    def __init__(self, cache_factory: DocumentCacheFactory, stats: StatsReporter) -> None:
        """Initialize the pipeline with crawler, election period, cache factory, and stats."""
        self._cache_factory = cache_factory
        self._stats = stats

    async def process_item(self: Self, vorgang: GesetzVorgang) -> GesetzVorgang:
        """Extract text from cached PDFs for each document in the Vorgang."""
        gesetzvorgang_guard(vorgang)

        for dokument in vorgang.dokumente:
            for dokument_url in dokument.all_urls:
                await self._process_url(vorgang, dokument, dokument_url)

        return vorgang

    async def _process_url(self, vorgang: GesetzVorgang, dokument: AnyGesetzDokument, dokument_url: HttpUrl) -> None:
        cache = self._cache_factory.for_document(document=dokument, url=dokument_url)

        if Key.DOCUMENT not in cache:
            return

        if Key.TEXT in cache:
            self._stats.increment(TextCounter.CACHE_HIT)
            return

        self._stats.increment(TextCounter.CACHE_MISS)

        text = await extract_text_with_ocr_backup(document_bytes=cache.get_bytes(Key.DOCUMENT))

        text = _text_edits(text)

        if len(text) == 0:
            self._stats.increment(TextCounter.EXTRACT_FAILED_EMPTY_TEXT)
            msg = f"[{vorgang.id} - {dokument.id}]: No text extracted."
            logger.warning(msg)

        else:
            self._stats.increment(TextCounter.EXTRACT_DONE)
            cache[Key.TEXT] = text
