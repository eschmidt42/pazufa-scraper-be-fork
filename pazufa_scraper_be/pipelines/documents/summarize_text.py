import logging
from typing import Self

import litellm
from pazufa_corelib.llm import LLMConnector, LLMProviderError
from pydantic import HttpUrl
from scrapy.crawler import Crawler

from pazufa_scraper_be.cache import Cache, Key
from pazufa_scraper_be.pardok import AnyGesetzDokument, DrsDokument, GesetzVorgang, GVBlDokument
from pazufa_scraper_be.pardok.dokument import DeskTitelSbMixin, Protokoll
from pazufa_scraper_be.pipeline_guards import vorgang_guard
from pazufa_scraper_be.pipelines.common import DocumentCacheFactory, StatsReporter
from pazufa_scraper_be.pipelines.stats_counter import LLMCounter, SummaryCounter

logger = logging.getLogger(__name__)


class SummarizeText2:
    """Pipeline that summarizes extracted document text via an LLM."""

    _llm_token: str | None
    llm_model_name: str
    llm_connector: LLMConnector | None
    _cache_factory: DocumentCacheFactory
    _stats: StatsReporter

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "SummarizeText2":
        """Create the pipeline with dependencies initialized from the crawler."""
        return cls(
            crawler=crawler,
            llm_token=crawler.settings.get("LLM_TOKEN", None),
            llm_model_name=crawler.settings.get("LLM_MODEL", None),
            cache_factory=DocumentCacheFactory.from_crawler(crawler),
            stats=StatsReporter(crawler.stats),
        )

    def __init__(self, crawler: Crawler, llm_token: str | None, llm_model_name: str, cache_factory: DocumentCacheFactory, stats: StatsReporter) -> None:
        """Load and validate LLM settings and initialize the connector."""
        self._cache_factory = cache_factory
        self._stats = stats
        self.llm_model_name = llm_model_name
        self._llm_token = llm_token
        self.llm_connector = None

        if self._llm_token is not None:
            if self.llm_model_name is None:
                msg = "If LLM_TOKEN is set, LLM_MODEL setting is required."
                raise ValueError(msg)

            logging.getLogger("LiteLLM").setLevel(logging.FATAL)
            litellm.suppress_debug_info = True

            logging.getLogger("pazufa_corelib.llm.llm_connector").setLevel(logging.FATAL)

            llm_timeout = crawler.settings.getint("LLM_TIMEOUT")
            if not isinstance(llm_timeout, int) or llm_timeout <= 0:
                msg = "Invalid LLM_TIMEOUT setting, must but integer greater than 0."
                raise ValueError(msg)

            self.llm_connector = LLMConnector(model=self.llm_model_name, api_key=self._llm_token, timeout_seconds=llm_timeout)

        else:
            msg = "LLM_TOKEN is not set. Skipping Document summarization."
            logger.info(msg)

    async def summarize(self: Self, dokument: AnyGesetzDokument, cache: Cache) -> str | None:
        """Summarize extracted document text via the LLM connector, dispatching by document type."""
        if self.llm_connector is None:
            return None

        self._stats.increment(LLMCounter.SUMMARIZE_TOTAL)

        titel: str = ""
        vorgang_nr: str = ""

        if len(dokument.vorgang.dokumente) > 0:
            first_document = dokument.vorgang.dokumente[0]
            if isinstance(first_document, DeskTitelSbMixin):
                titel = first_document.titel or ""

            vorgang_nr = first_document.nr or ""

        text = cache.get_text(Key.TEXT)
        art_l_summary_name = LLMCounter.summarize_art(dokument.art_l.lower())

        if isinstance(dokument, Protokoll):
            self._stats.increment(LLMCounter.EXTRACT_RELEVANT_SECTION_TOTAL)

            relevant_section = await self.llm_connector.extract_relevant_section(text=text, vorgang_titel=titel, vorgang_vnr=vorgang_nr)

            if relevant_section:
                self._stats.increment(LLMCounter.EXTRACT_RELEVANT_SECTION_DONE)
                self._stats.increment(art_l_summary_name)

                return await self.llm_connector.summarize_dokument(titel=titel, text=relevant_section)

            cache[Key.SUMMARY_IGNORE] = "Ignoring because no relevant section was found."
            self._stats.increment(LLMCounter.EXTRACT_RELEVANT_SECTION_FAILED)

        elif isinstance(dokument, GVBlDokument):
            self._stats.increment(art_l_summary_name)

            return await self.llm_connector.summarize_gesetzentwurf(titel=titel, text=text)

        elif isinstance(dokument, DrsDokument):
            self._stats.increment(art_l_summary_name)

            return await self.llm_connector.summarize_dokument(titel=titel, text=text)

        return None

    async def process_item(self: Self, vorgang: GesetzVorgang) -> GesetzVorgang:
        """Summarize extracted text for each document in the Vorgang and cache the result."""
        vorgang_guard(vorgang)

        if self.llm_connector is None:
            return vorgang

        for dokument in vorgang.dokumente:
            for dokument_url in dokument.all_urls:
                await self._process_url(vorgang, dokument, dokument_url)

        return vorgang

    async def _process_url(self, vorgang: GesetzVorgang, dokument: AnyGesetzDokument, dokument_url: HttpUrl) -> None:
        cache = self._cache_factory.for_document(document=dokument, url=dokument_url)

        if Key.SUMMARY_IGNORE in cache:
            self._stats.increment(SummaryCounter.IGNORE)
            return

        # There is no text to summarize => skip
        if Key.TEXT not in cache:
            return

        # If model specific summary exist => link and skip
        if self.llm_model_name is not None and cache.exist_model_specific_summary(self.llm_model_name):
            self._stats.increment(SummaryCounter.CACHE_HIT)
            cache.link_model_specific_summary_file(llm_model_name=self.llm_model_name)
            return

        self._stats.increment(SummaryCounter.CACHE_MISS)
        try:
            summary = await self.summarize(dokument=dokument, cache=cache)

        except LLMProviderError as error:
            self._stats.increment(LLMCounter.SUMMARIZE_FAILED_PROVIDER)
            msg = f"[{vorgang.id} - {dokument.id}]: LLM summarization failed due to provider problem."
            logger.warning(msg)

            cache[Key.SUMMARY_IGNORE] = repr(error)
            return

        if summary is None:
            self._stats.increment(LLMCounter.SUMMARIZE_FAILED_APPLICATION)
            msg = f"[{vorgang.id} - {dokument.id}]: LLM summarization failed due to application problem."
            logger.warning(msg)

        elif len(summary) == 0:
            self._stats.increment(LLMCounter.SUMMARIZE_FAILED_EMPTY_SUMMARY)
            msg = f"[{vorgang.id} - {dokument.id}]: Summary is empty."
            logger.warning(msg)

        else:
            self._stats.increment(LLMCounter.SUMMARIZE_DONE)
            cache.set_model_specific_summary(llm_model_name=self.llm_model_name, summary=summary)
            cache.link_model_specific_summary_file(llm_model_name=self.llm_model_name)
