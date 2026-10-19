import logging
from typing import Self

from pydantic import HttpUrl
from scrapy.exceptions import DropItem

from pazufa_scraper_be.pardok import AnyGesetzDokument, APrDokument, GesetzVorgang, PlPrDokument
from pazufa_scraper_be.pardok.dokument import ProtokollTyp
from pazufa_scraper_be.pardok.url import build_ausschussprotokoll_variant_url, build_plenarprotokoll_url, resolve_document_urls
from pazufa_scraper_be.pipelines._base import StatsPipeline
from pazufa_scraper_be.pipelines.stats_counter import DokumentCounter

logger = logging.getLogger(__name__)

CORRECTED_URL_PART = "/h/h19-076-"
INCORRECT_URL_PART = "/iso/h19-076-"


class PrepareDocumentUrls(StatsPipeline):
    """Pipeline that fixes and adds additional document URLs."""

    def _add_missing_primary_url(self: Self, dokument: AnyGesetzDokument) -> None:

        # TODO(se-jaeger): Similarly could work for Ausschussprotokolle but those are trickier due to their URL containing abbreviation of Ausschussname
        if isinstance(dokument, PlPrDokument) and dokument.lok_url is None:
            dokument.lok_url = build_plenarprotokoll_url(self.wahlperiode, dokument.nr)

    def _add_additional_urls(self: Self, dokument: AnyGesetzDokument) -> None:
        # Ausschussprotokolle can have up to three documents: Beschlussprotokoll, Inhaltsprotokoll and Wortprotokoll.
        # The last two are optional but the pardok XML does not always serve the first one.
        # So we order here to our liking.
        if not isinstance(dokument, APrDokument) or dokument.lok_url is None:
            return

        additional_urls = []
        for typ in ProtokollTyp:
            url = build_ausschussprotokoll_variant_url(dokument.lok_url, typ)
            if typ is ProtokollTyp.Beschluss:
                dokument.lok_url = url

            else:
                additional_urls.append(url)

        dokument.additional_urls = additional_urls or None

    async def process_item(self: Self, vorgang: GesetzVorgang) -> GesetzVorgang:
        """Check for additional Ausschussprotokoll URLs and append them to each document."""
        if not isinstance(vorgang, GesetzVorgang):
            msg = f"Expected {GesetzVorgang.__name__} object but got {vorgang.__class__.__name__}."
            raise DropItem(msg)

        if self.crawler.engine is None:
            msg = "crawler.engine is None. The crawler seems improperly initialized."
            raise ValueError(msg)

        for dokument in vorgang.dokumente:
            # NOTE: We need to fix this that early.
            # Using Rule is not possible because we already tried to download the incorrect URL.
            # We could change it and yield a new (changed) Item from a later stage
            if INCORRECT_URL_PART in str(dokument.lok_url):
                dokument.lok_url = HttpUrl(str(dokument.lok_url).replace(INCORRECT_URL_PART, CORRECTED_URL_PART))

            self._add_missing_primary_url(dokument)
            self._add_additional_urls(dokument)

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
