import logging
from typing import Self

from scrapy.core.engine import ExecutionEngine
from scrapy.crawler import Crawler

from pazufa_scraper_be.pardok import AnyGesetzDokument, GesetzVorgang
from pazufa_scraper_be.pardok.url import UrlResolution, add_additional_urls, add_missing_plprdokument_primary_url, fix_url, resolve_document_urls
from pazufa_scraper_be.pipeline_guards import engine_guard, engine_guard2, vorgang_guard
from pazufa_scraper_be.pipelines.common import StatsPipeline, StatsReporter, get_wahlperiode
from pazufa_scraper_be.pipelines.stats_counter import DokumentCounter

logger = logging.getLogger(__name__)


class PrepareDocumentUrls2:
    """Pipeline that fixes and adds additional document URLs."""

    wahlperiode: int
    _stats: StatsReporter
    _engine: ExecutionEngine

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "PrepareDocumentUrls2":
        """Create a pipeline using the crawler's settings, stats, and engine."""
        return cls(wahlperiode=get_wahlperiode(crawler), stats=StatsReporter(crawler.stats), engine=crawler.engine)

    def __init__(self, wahlperiode: int, stats: StatsReporter, engine: ExecutionEngine) -> None:
        """Initialize the pipeline with its election period, stats reporter, and engine."""
        self.wahlperiode = wahlperiode
        self._stats = stats
        self._engine = engine

    async def process_item(self: Self, vorgang: GesetzVorgang) -> GesetzVorgang:
        """Check for additional Ausschussprotokoll URLs and append them to each document."""
        vorgang_guard(vorgang)
        engine_guard2(self._engine)

        for dokument in vorgang.dokumente:
            dokument.lok_url = fix_url(dokument)
            dokument.lok_url = add_missing_plprdokument_primary_url(dokument, self.wahlperiode)
            dokument.lok_url, dokument.additional_urls = add_additional_urls(dokument)
            dokument.additional_urls, res = await resolve_document_urls(dokument, self._engine)

            self._count_url_resolution(dokument, res)

        return vorgang

    def _count_url_resolution(self, dokument: AnyGesetzDokument, res: UrlResolution) -> None:
        """Increment stats based on url resolutions."""
        if res.missing_primary:
            self._stats.increment(DokumentCounter.MISSING_PRIMARY)
            msg = f"[{dokument.vorgang.id} - {dokument.id}]: Missing URL."
            logger.warning(msg)

        if res.recovered_from:
            self._stats.increment(DokumentCounter.RECOVERED_FROM_ADDITIONAL)

        if res.pruned:
            self._stats.increment(DokumentCounter.ADDITIONAL_PRUNED)


class PrepareDocumentUrls(StatsPipeline):
    """Pipeline that fixes and adds additional document URLs."""

    async def process_item(self: Self, vorgang: GesetzVorgang) -> GesetzVorgang:
        """Check for additional Ausschussprotokoll URLs and append them to each document."""
        vorgang_guard(vorgang)
        engine_guard(self.crawler)

        for dokument in vorgang.dokumente:
            dokument.lok_url = fix_url(dokument)
            dokument.lok_url = add_missing_plprdokument_primary_url(dokument, self.wahlperiode)
            dokument.lok_url, dokument.additional_urls = add_additional_urls(dokument)
            dokument.additional_urls, res = await resolve_document_urls(dokument, self.crawler.engine)

            self._count_url_resolution(dokument, res)

        return vorgang

    def _count_url_resolution(self, dokument: AnyGesetzDokument, res: UrlResolution) -> None:
        """Increment stats based on url resolutions."""
        if res.missing_primary:
            self.increment_stats(DokumentCounter.MISSING_PRIMARY)
            msg = f"[{dokument.vorgang.id} - {dokument.id}]: Missing URL."
            logger.warning(msg)

        if res.recovered_from:
            self.increment_stats(DokumentCounter.RECOVERED_FROM_ADDITIONAL)

        if res.pruned:
            self.increment_stats(DokumentCounter.ADDITIONAL_PRUNED)
