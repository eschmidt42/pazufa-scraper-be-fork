import logging
from pathlib import Path
from typing import Self

from pazufa_corelib.llm import LLMProviderError
from scrapy.exceptions import DropItem

from pazufa_scraper_be.cache import Cache, Key
from pazufa_scraper_be.pardok import BaseGesetzDokument, DrsDokument, GesetzVorgang, GVBlDokument
from pazufa_scraper_be.pardok.dokument import Protokoll
from pazufa_scraper_be.pipelines._base import CachePipeline, LLMPipeline, StatsPipeline
from pazufa_scraper_be.pipelines.stats_counter import LLMCounter, SummaryCounter

logger = logging.getLogger(__name__)


class SummarizeExtractedPDFText(CachePipeline, LLMPipeline, StatsPipeline):
    """Pipeline that summarizes extracted document text via an LLM."""

    def link(self: Self, summary_file: Path, model_specific_summary_file: Path) -> None:
        """Create a symlink from summary_file pointing to the model-specific summary file."""
        summary_file.unlink(missing_ok=True)
        summary_file.symlink_to(model_specific_summary_file.relative_to(summary_file.parent))

    async def summarize(self: Self, dokument: BaseGesetzDokument, cache: Cache) -> str | None:
        """Summarize extracted document text via the LLM connector, dispatching by document type."""
        if self.llm_connector is None:
            return None

        self.increment_stats(LLMCounter.SUMMARIZE_TOTAL)
        if len(dokument.vorgang.dokumente) > 0:
            titel = getattr(dokument.vorgang.dokumente[0], "titel", "")
            vorgang_nr = dokument.vorgang.dokumente[0].nr or ""

        else:
            titel = vorgang_nr = ""

        text = cache.get_text(Key.TEXT)

        if isinstance(dokument, Protokoll):
            self.increment_stats(LLMCounter.EXTRACT_RELEVANT_SECTION_TOTAL)
            relevant_section = await self.llm_connector.extract_relevant_section(text=text, vorgang_titel=titel, vorgang_vnr=vorgang_nr)

            if relevant_section:
                self.increment_stats(LLMCounter.EXTRACT_RELEVANT_SECTION_DONE)
                self.increment_stats(LLMCounter.summarize_art(dokument.art_l.lower()))
                return await self.llm_connector.summarize_dokument(titel=titel, text=relevant_section)

            cache[Key.SUMMARY_IGNORE] = "Ignoring because no relevant section was found."
            self.increment_stats(LLMCounter.EXTRACT_RELEVANT_SECTION_FAILED)

        elif isinstance(dokument, GVBlDokument):
            self.increment_stats(LLMCounter.summarize_art(dokument.art_l.lower()))
            return await self.llm_connector.summarize_gesetzentwurf(titel=titel, text=text)

        elif isinstance(dokument, DrsDokument):
            self.increment_stats(LLMCounter.summarize_art(dokument.art_l.lower()))
            return await self.llm_connector.summarize_dokument(titel=titel, text=text)

        return None

    # TODO(se-jaeger): refactor to reduce complexity
    async def process_item(self: Self, vorgang: GesetzVorgang) -> GesetzVorgang:  # noqa: C901
        """Summarize extracted text for each document in the Vorgang and cache the result."""
        if not isinstance(vorgang, GesetzVorgang):
            msg = f"Expected {GesetzVorgang.__name__} object but got {vorgang.__class__.__name__}."
            raise DropItem(msg)

        if self.llm_connector is None:
            return vorgang

        for dokument in vorgang.dokumente:
            for dokument_url in dokument.all_urls:
                cache = self.get_cache(document=dokument, document_url=dokument_url)

                if Key.SUMMARY_IGNORE in cache:
                    self.increment_stats(SummaryCounter.IGNORE)
                    continue

                # There is no text to summarize => skip
                if Key.TEXT not in cache:
                    continue

                # If model specific summary exist => link and skip
                if self.llm_model_name is not None and cache.exist_model_specific_summary(self.llm_model_name):
                    self.increment_stats(SummaryCounter.CACHE_HIT)
                    cache.link_model_specific_summary_file(llm_model_name=self.llm_model_name)
                    continue

                self.increment_stats(SummaryCounter.CACHE_MISS)
                try:
                    summary = await self.summarize(dokument=dokument, cache=cache)

                except LLMProviderError as error:
                    self.increment_stats(LLMCounter.SUMMARIZE_FAILED_PROVIDER)
                    msg = f"[{vorgang.id} - {dokument.id}]: LLM summarization failed due to provider problem."
                    logger.warning(msg)

                    cache[Key.SUMMARY_IGNORE] = repr(error)
                    continue

                if summary is None:
                    self.increment_stats(LLMCounter.SUMMARIZE_FAILED_APPLICATION)
                    msg = f"[{vorgang.id} - {dokument.id}]: LLM summarization failed due to application problem."
                    logger.warning(msg)

                elif len(summary) == 0:
                    self.increment_stats(LLMCounter.SUMMARIZE_FAILED_EMPTY_SUMMARY)
                    msg = f"[{vorgang.id} - {dokument.id}]: Summary is empty."
                    logger.warning(msg)

                else:
                    self.increment_stats(LLMCounter.SUMMARIZE_DONE)
                    cache.set_model_specific_summary(llm_model_name=self.llm_model_name, summary=summary)
                    cache.link_model_specific_summary_file(llm_model_name=self.llm_model_name)

        return vorgang
