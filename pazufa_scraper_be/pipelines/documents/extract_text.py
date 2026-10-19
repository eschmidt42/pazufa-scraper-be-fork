import logging
from typing import Self

import xberg
from scrapy.exceptions import DropItem
from xberg import ExtractInput, ExtractInputKind, ExtractionConfig, OcrConfig, PageConfig

from pazufa_scraper_be.cache import Key
from pazufa_scraper_be.pardok import GesetzVorgang
from pazufa_scraper_be.pipelines._base import CachePipeline, StatsPipeline
from pazufa_scraper_be.pipelines.stats_counter import TextCounter

logger = logging.getLogger(__name__)


def _get_xberg_config(*, ocr: bool) -> ExtractionConfig:
    page_config = PageConfig(extract_pages=True)

    if ocr:
        ocr_config = OcrConfig(
            backend="tesseract",
            language=["deu"],
        )
        force_ocr = True

    else:
        ocr_config = None
        force_ocr = False

    return ExtractionConfig(enable_quality_processing=True, pages=page_config, use_cache=False, ocr=ocr_config, force_ocr=force_ocr)


async def _extract_text(document_bytes: bytes, *, ocr: bool) -> str:
    extract_input = ExtractInput(kind=ExtractInputKind.BYTES, bytes=document_bytes)  # ty: ignore[invalid-argument-type] NOTE: This is actually fine and should be a temporary bug
    extraction_result = await xberg.extract(
        input=extract_input,
        config=_get_xberg_config(ocr=ocr),
    )
    extraction_result = extraction_result.results[0]
    text = "\n".join([page.content for page in extraction_result.pages or []])

    # In the few cases, where we could not extract text, apply OCR
    if len(text) == 0 and not ocr:
        return await _extract_text(document_bytes=document_bytes, ocr=True)

    return text


class ExtractTextFromPDF(CachePipeline, StatsPipeline):
    """Pipeline that extracts plain text from cached PDF documents using xberg."""

    async def process_item(self: Self, vorgang: GesetzVorgang) -> GesetzVorgang:
        """Extract text from cached PDFs for each document in the Vorgang."""
        if not isinstance(vorgang, GesetzVorgang):
            msg = f"Expected {GesetzVorgang.__name__} object but got {vorgang.__class__.__name__}."
            raise DropItem(msg)

        for dokument in vorgang.dokumente:
            for dokument_url in dokument.all_urls:
                cache = self.get_cache(document=dokument, document_url=dokument_url)

                if Key.DOCUMENT in cache:
                    if Key.TEXT in cache:
                        self.increment_stats(TextCounter.CACHE_HIT)
                        continue

                    self.increment_stats(TextCounter.CACHE_MISS)
                    text = await _extract_text(document_bytes=cache.get_bytes(Key.DOCUMENT), ocr=False)

                    # fmt: off
                    # Some postprocessing that was necessary after eyeballing documents
                    text = (
                        text
                        .strip()                                                      # remove leading/trailing spaces
                        .replace("\x02", "")                                          # hyphens (line-breaks with -)
                        .replace("\x15", "").replace("\x16", "").replace("\x18", "")  # showed up when bold face Drucksache Nummer could not be extracted
                    )
                    # fmt: on

                    if len(text) == 0:
                        self.increment_stats(TextCounter.EXTRACT_FAILED_EMPTY_TEXT)
                        msg = f"[{vorgang.id} - {dokument.id}]: No text extracted."
                        logger.warning(msg)

                    else:
                        self.increment_stats(TextCounter.EXTRACT_DONE)
                        cache[Key.TEXT] = text

        return vorgang
