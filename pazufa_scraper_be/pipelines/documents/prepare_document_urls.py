import logging
from typing import Self

from scrapy.crawler import Crawler

from pazufa_scraper_be.pardok import AnyGesetzDokument, GesetzVorgang
from pazufa_scraper_be.pardok.url import UrlResolution, add_additional_urls, add_missing_plprdokument_primary_url, fix_url, resolve_document_urls
from pazufa_scraper_be.pipeline_guards import engine_guard, gesetzvorgang_guard
from pazufa_scraper_be.pipelines.common import StatsReporter, get_wahlperiode
from pazufa_scraper_be.pipelines.stats_counter import DokumentCounter

logger = logging.getLogger(__name__)


class PrepareDocumentUrls:
    """Pipeline that fixes and adds additional document URLs."""

    _wahlperiode: int
    _stats: StatsReporter
    _crawler: Crawler

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "PrepareDocumentUrls":
        """Create a pipeline using the crawler's settings, stats, and engine."""
        return cls(wahlperiode=get_wahlperiode(crawler), stats=StatsReporter(crawler.stats), crawler=crawler)

    def __init__(self, wahlperiode: int, stats: StatsReporter, crawler: Crawler) -> None:
        """Initialize the pipeline with its election period, stats reporter, and engine."""
        self._wahlperiode = wahlperiode
        self._stats = stats
        self._crawler = crawler

    async def process_item(self: Self, vorgang: GesetzVorgang) -> GesetzVorgang:
        """Check for additional Ausschussprotokoll URLs and append them to each document."""
        gesetzvorgang_guard(vorgang)
        engine_guard(self._crawler)

        for dokument in vorgang.dokumente:
            dokument.lok_url = fix_url(dokument)
            dokument.lok_url = add_missing_plprdokument_primary_url(dokument, self._wahlperiode)
            dokument.lok_url, dokument.additional_urls = add_additional_urls(dokument)
            dokument.additional_urls, res = await resolve_document_urls(dokument, self._crawler.engine)

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
