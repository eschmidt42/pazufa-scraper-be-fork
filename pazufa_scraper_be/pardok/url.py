import asyncio
from dataclasses import dataclass
from http import HTTPStatus
from typing import Self

from pydantic import HttpUrl
from scrapy import Request
from scrapy.core.engine import ExecutionEngine
from scrapy.http.request import NO_CALLBACK

from pazufa_scraper_be.constants import DOK_BASE_URL
from pazufa_scraper_be.pardok import AnyGesetzDokument, APrDokument, PlPrDokument
from pazufa_scraper_be.pardok.dokument import ProtokollTyp

CORRECTED_URL_PART = "/h/h19-076-"
INCORRECT_URL_PART = "/iso/h19-076-"


def build_plenarprotokoll_url(wahlperiode: int, dokument_nr: str) -> HttpUrl | None:
    """Build a PlPr LokURL from a DokNr like "19/2" → p19-002-wp.pdf.

    Returns None if DokNr has no numeric second segment.
    """
    parts = dokument_nr.split("/")
    n_parts = 2
    if len(parts) < n_parts or not parts[1].isdigit():
        return None

    nr = int(parts[1])
    url = f"{DOK_BASE_URL}/{wahlperiode}/PlenarPr/p{wahlperiode}-{nr:03d}-{ProtokollTyp.Wort}.pdf"

    return HttpUrl(url)


def build_ausschussprotokoll_variant_url(url: HttpUrl, typ: ProtokollTyp) -> HttpUrl:
    """Return the URL for a specific APr variant by swapping the trailing-typ segment.

    Robust to non-3-digit numbering (ParlKBB19-001) and arbitrary abbrpaths;
    only assumes the variant is the segment after the final '-' before .pdf.
    """
    if url.path is None:
        msg = f"{url=} should contain the path to a file but lacks any path."
        raise ValueError(msg)

    stem, dot, ext = url.path.rpartition(".")
    base_stem, sep, _old = stem.rpartition("-")
    if not sep or dot != "." or ext != "pdf":
        msg = f"Cannot derive APr variant from {url=}"
        raise ValueError(msg)

    new_path = f"{base_stem}-{typ}{dot}{ext}"
    return HttpUrl(str(url).replace(url.path, new_path))


def fix_url(dokument: AnyGesetzDokument) -> None:
    """Swap incorrect for correct url part, if detected."""
    # NOTE: We need to fix this that early.
    # Using Rule is not possible because we already tried to download the incorrect URL.
    # We could change it and yield a new (changed) Item from a later stage
    if INCORRECT_URL_PART in str(dokument.lok_url):
        dokument.lok_url = HttpUrl(str(dokument.lok_url).replace(INCORRECT_URL_PART, CORRECTED_URL_PART))


def add_missing_plprdokument_primary_url(dokument: AnyGesetzDokument, wahlperiode: int) -> None:
    """Construct url, if missing, for PlPrDokument."""
    # TODO(se-jaeger): Similarly could work for Ausschussprotokolle but those are trickier due to their URL containing abbreviation of Ausschussname
    if isinstance(dokument, PlPrDokument) and dokument.lok_url is None:
        dokument.lok_url = build_plenarprotokoll_url(wahlperiode, dokument.nr)


def add_additional_urls(dokument: AnyGesetzDokument) -> None:
    """Construct and order additionl urls.

    Ausschussprotokolle can have up to three documents: Beschlussprotokoll, Inhaltsprotokoll and Wortprotokoll.
    The last two are optional but the pardok XML does not always serve the first one.
    So we order here to our liking.
    """
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


@dataclass
class UrlResolution:
    """Data container summarizing resolve_dokument_urls outcome."""

    primary_was_reachable: bool
    recovered_from: HttpUrl | None
    pruned: list[HttpUrl]

    @property
    def missing_primary(self: Self) -> bool:
        """Denotes weather primary URL is missing."""
        return not self.primary_was_reachable and self.recovered_from is None


async def url_is_reachable(engine: ExecutionEngine, url: HttpUrl | None) -> bool:
    """HEAD-check a URL; treats non-OK or exceptions as unreachable."""
    try:
        request = Request(str(url), method="HEAD", callback=NO_CALLBACK)
        response = await engine.download_async(request)

    except Exception:  # noqa: BLE001
        return False

    return response.status == HTTPStatus.OK


async def resolve_document_urls(dokument: AnyGesetzDokument, engine: ExecutionEngine) -> UrlResolution:
    """Single pass: probe primary once, probe each additional once, then mutate."""
    additional_urls = dokument.additional_urls or []

    primary_ok = await url_is_reachable(engine, dokument.lok_url)
    additional_ok = await asyncio.gather(*(url_is_reachable(engine, u) for u in additional_urls))

    reachable, pruned = [], []
    for url, ok in zip(additional_urls, additional_ok, strict=True):
        if ok:
            reachable.append(url)

        else:
            pruned.append(url)

    recovered_from = None
    if not primary_ok and reachable:
        recovered_from = reachable.pop(0)
        dokument.lok_url = recovered_from

    dokument.additional_urls = reachable or None
    return UrlResolution(
        primary_was_reachable=primary_ok,
        recovered_from=recovered_from,
        pruned=pruned,
    )
