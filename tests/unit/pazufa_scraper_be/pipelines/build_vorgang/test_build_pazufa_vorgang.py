from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid5

import pytest
from pazufa_corelib.api_client.models import Dokument as PaZuFaDokument
from pazufa_corelib.api_client.models import Stationstyp, Vorgangstyp
from scrapy import Spider
from scrapy.crawler import Crawler
from scrapy.exceptions import DropItem
from scrapy.settings import Settings
from scrapy.statscollectors import StatsCollector

from pazufa_scraper_be.cache import Cache, Key
from pazufa_scraper_be.pardok import AnyGesetzDokument, GesetzVorgang
from pazufa_scraper_be.pipelines.build_vorgang.build_vorgang import BuildPaZuFaVorgang
from pazufa_scraper_be.pipelines.stats_counter import VorgangCounter

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def build_pipeline(tmp_path: Path) -> BuildPaZuFaVorgang:
    """Create a Vorgang builder with an isolated cache and stats collector."""
    crawler = Crawler(
        Spider,
        Settings(
            {
                "WAHLPERIODE": 19,
                "CACHE_DIR": tmp_path,
                "SCRAPER_UUID": UUID("12345678-1234-5678-1234-567812345678"),
            }
        ),
    )
    crawler.stats = StatsCollector(crawler)
    return BuildPaZuFaVorgang(crawler)


def _cache_for_document(pipeline: BuildPaZuFaVorgang, document: AnyGesetzDokument) -> Cache:
    assert document.lok_url is not None
    return pipeline.get_cache(document=document, document_url=document.lok_url)


def test_build_pazufa_vorgang_rejects_non_vorgang(build_pipeline: BuildPaZuFaVorgang) -> None:
    """Items of an unexpected type are dropped."""
    invalid_item: Any = object()

    with pytest.raises(DropItem, match="Expected GesetzVorgang object"):
        asyncio.run(build_pipeline.process_item(invalid_item))


def test_build_pazufa_vorgang_builds_vorgang_and_station(
    build_pipeline: BuildPaZuFaVorgang,
    base_vorgang_data: dict[str, Any],
    plpr_data: dict[str, Any],
) -> None:
    """A cached document is converted into a PaZuFa Vorgang with its station."""
    item = GesetzVorgang.model_validate({**base_vorgang_data, "Dokument": [plpr_data]})
    document = item.dokumente[0]
    cache = _cache_for_document(build_pipeline, document)
    cache[Key.DOCUMENT] = b"document bytes"
    cache[Key.TEXT] = "extracted document text"

    result = asyncio.run(build_pipeline.process_item(item))

    assert result.api_id == uuid5(UUID("12345678-1234-5678-1234-567812345678"), item.id)
    assert result.titel == "Plenumsprotokoll - 123/2024"
    assert result.wahlperiode == 19
    assert result.typ == Vorgangstyp.GG_LAND_PARL
    assert isinstance(result.ids, list)
    assert len(result.ids) == 2
    assert result.ids[0].id == item.id
    assert result.ids[0].typ == "vorgnr"
    assert result.ids[1].id == document.id
    assert result.links == [f"https://pardok.parlament-berlin.de/portala/vorgang/{item.id}"]
    assert len(result.stationen) == 1

    station = result.stationen[0]
    assert station.api_id == uuid5(UUID("12345678-1234-5678-1234-567812345678"), f"Station-{document.id}")
    assert station.typ == Stationstyp.PARL_VOLLVLSGN
    assert station.gremium.name == "Plenum"
    assert len(station.dokumente) == 1
    pazufa_document = station.dokumente[0]
    assert isinstance(pazufa_document, PaZuFaDokument)
    assert pazufa_document.volltext == "extracted document text"
    assert pazufa_document.link == str(document.lok_url)


def test_build_pazufa_vorgang_drops_when_no_documents_can_be_built(
    build_pipeline: BuildPaZuFaVorgang,
    base_vorgang_data: dict[str, Any],
    plpr_data: dict[str, Any],
) -> None:
    """Documents without cached text cause the Vorgang to be dropped and counted."""
    item = GesetzVorgang.model_validate({**base_vorgang_data, "Dokument": [plpr_data]})

    with pytest.raises(DropItem, match="Could not create any Dokument from Vorgang"):
        asyncio.run(build_pipeline.process_item(item))

    assert build_pipeline.stats.get_value(VorgangCounter.DROP_NO_DOCUMENTS.value) == 1


def test_build_pazufa_vorgang_drops_when_rules_remove_all_stations(
    build_pipeline: BuildPaZuFaVorgang,
    base_vorgang_data: dict[str, Any],
    apr_data: dict[str, Any],
) -> None:
    """A document removed by build rules results in a no-stations drop."""
    item = GesetzVorgang.model_validate(
        {
            **base_vorgang_data,
            "VID": "V-435029",
            "Dokument": [{**apr_data, "DokNr": "19/100"}],
        }
    )
    document = item.dokumente[0]
    cache = _cache_for_document(build_pipeline, document)
    cache[Key.DOCUMENT] = b"document bytes"
    cache[Key.TEXT] = "extracted document text"

    with pytest.raises(DropItem, match="Could not create any Stations"):
        asyncio.run(build_pipeline.process_item(item))

    assert build_pipeline.stats.get_value(VorgangCounter.DROP_NO_STATIONS.value) == 1


def test_build_pazufa_vorgang_drops_single_gvbl_as_out_of_scope(
    build_pipeline: BuildPaZuFaVorgang,
    base_vorgang_data: dict[str, Any],
    gvbl_data: dict[str, Any],
) -> None:
    """A Vorgang containing only one Gesetzblatt is dropped as out of scope."""
    item = GesetzVorgang.model_validate({**base_vorgang_data, "Dokument": [gvbl_data]})

    with pytest.raises(DropItem, match=r"Out of scope\. Single Gesetz- und Verordnungsblatt"):
        asyncio.run(build_pipeline.process_item(item))

    assert build_pipeline.stats.get_value(VorgangCounter.DROP_OUT_OF_SCOPE.value) == 1
