import logging
from typing import Self

from pazufa_scraper_be.pardok import GesetzVorgang
from pazufa_scraper_be.pardok.url import add_additional_urls, add_missing_plprdokument_primary_url, fix_url, resolve_document_urls
from pazufa_scraper_be.pipeline_guards import engine_guard, vorgang_guard
from pazufa_scraper_be.pipelines._base import StatsPipeline
from pazufa_scraper_be.pipelines.stats_counter import DokumentCounter

logger = logging.getLogger(__name__)


class PrepareDocumentUrls(StatsPipeline):
    """Pipeline that fixes and adds additional document URLs."""

    async def process_item(self: Self, vorgang: GesetzVorgang) -> GesetzVorgang:
        """Check for additional Ausschussprotokoll URLs and append them to each document."""
        vorgang_guard(vorgang)
        engine_guard(self.crawler)

        for dokument in vorgang.dokumente:
            fix_url(dokument)
            add_missing_plprdokument_primary_url(dokument, self.wahlperiode)
            add_additional_urls(dokument)

            res = await resolve_document_urls(dokument, self.crawler.engine)

            if res.missing_primary:
                self.increment_stats(DokumentCounter.MISSING_PRIMARY)
                msg = f"[{dokument.vorgang.id} - {dokument.id}]: Missing URL."
                logger.warning(msg)

            if res.recovered_from:
                self.increment_stats(DokumentCounter.RECOVERED_FROM_ADDITIONAL)

            if res.pruned:
                self.increment_stats(DokumentCounter.ADDITIONAL_PRUNED)

        return vorgang
