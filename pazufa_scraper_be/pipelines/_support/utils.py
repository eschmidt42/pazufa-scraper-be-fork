from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from pazufa_corelib.api_client.models import Doktyp, Gremium, Parlament, Station, Stationstyp
from pazufa_corelib.api_client.models import Dokument as PaZuFaDokument
from pazufa_corelib.api_client.types import UNSET, Unset

from pazufa_scraper_be.constants import ABGELEHNT, ANGENOMMEN, ZURUECKGEZOGEN, ZUSTIMMUNG
from pazufa_scraper_be.pardok import APrDokument, BaseGesetzDokument, DrsDokument, GesetzVorgang, GVBlDokument, PlPrDokument
from pazufa_scraper_be.pardok.dokument import DeskTitelSbMixin

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class DokumentContainer:
    """Container pairing a pardok document with its derived PaZuFa documents."""

    pardok: BaseGesetzDokument
    pazufa: list[PaZuFaDokument]


def uniqify(sequence: Sequence) -> list:
    """Fast way to remove duplicates from a sequence (list) but keep order.

    See:
    - https://stackoverflow.com/a/480227
    - https://www.peterbe.com/plog/uniqifiers-benchmark
    """
    seen = set()
    seen_add = seen.add
    return [x for x in sequence if not (x in seen or seen_add(x))]  # ty: ignore[redundant-condition] NOTE: this is fine because we want to call that function inline


def get_document_schlagworte(dokument: BaseGesetzDokument) -> list[str] | Unset:
    """Get Schlagworte from Dokument's Nebeneinträge."""
    schlagworte = UNSET
    if isinstance(dokument, DeskTitelSbMixin):
        schlagworte = uniqify([dokument.desk]) if dokument.desk else UNSET

    return schlagworte


def get_vorgang_schlagworte(vorgang: GesetzVorgang) -> list[str] | Unset:
    """Get Schlagworte from Vorgang's Nebeneinträge."""
    schlagworte = uniqify([n.desk for n in vorgang.nebeneintraege])
    return schlagworte or UNSET


def get_station_typ_and_gremium(dok_container: DokumentContainer) -> tuple[Stationstyp, tuple[Gremium, bool | Unset]]:
    """Extract Stationstyp, Gremium and whether it was 'federführend'."""
    typ = Stationstyp.SONSTIG
    gremium_name = ""
    gremium_federf = UNSET

    if isinstance(dok_container.pardok, DrsDokument) and dok_container.pazufa[0].typ == Doktyp.ENTWURF:
        typ = Stationstyp.PARL_INITIATIV
        gremium_name = "Plenum"

    if isinstance(dok_container.pardok, PlPrDokument):
        typ = Stationstyp.PARL_VOLLVLSGN
        gremium_name = "Plenum"

    if isinstance(dok_container.pardok, APrDokument):
        typ = Stationstyp.PARL_AUSSCHBER

        # NOTE: It should always be a single value with Ausschuss name, so we take the first that fit
        for x in dok_container.pardok.urheber:
            if bool(re.search("ausschuss", x, flags=re.IGNORECASE)):
                gremium_name = x
                break

        if bool(re.search("federführend", gremium_name, flags=re.IGNORECASE)):
            gremium_name = re.sub(r"\s*\(federführend\)", "", gremium_name, flags=re.IGNORECASE).strip()
            gremium_federf = True

        else:
            gremium_name = gremium_name.strip()
            gremium_federf = False

    if isinstance(dok_container.pardok, GVBlDokument):
        typ = Stationstyp.POSTPARL_GSBLT
        gremium_name = "Gesetzesblatt"
        gremium_federf = UNSET

    gremium = Gremium(
        parlament=Parlament.BE,
        wahlperiode=dok_container.pardok.wp,
        name=gremium_name,
        # NOTE: Following should be revisited
        link=UNSET,
    )

    if typ == Stationstyp.SONSTIG:
        msg = f"[{dok_container.pardok.vorgang.id} - {dok_container.pardok.id}]: Using fallback for Stationstyp."
        logger.info(msg)

    return typ, (gremium, gremium_federf)


def get_station_zeitpunkte(dok_container: DokumentContainer) -> tuple[datetime, datetime]:
    """Extract timestamps relevant for station."""
    zp_start = dok_container.pazufa[0].zp_referenz
    zp_modifiziert = dok_container.pazufa[-1].zp_modifiziert

    if isinstance(dok_container.pardok, GVBlDokument):
        zp_start = dok_container.pardok.vk_dat

    return zp_start, zp_modifiziert


def check_and_create_vote_outcome_station(station: Station, dok_abstract: str) -> Station | None:
    """Check if station is Lesung and contains information about vote outcome. If so, create and return new station."""
    if station.typ == Stationstyp.PARL_VOLLVLSGN:
        typ = None
        if bool(re.search(rf"\b{ANGENOMMEN}\b|\b{ZUSTIMMUNG}\b", dok_abstract)):
            typ = Stationstyp.PARL_AKZEPTANZ
            titel = ANGENOMMEN

        elif bool(re.search(rf"\b{ABGELEHNT}\b", dok_abstract)):
            typ = Stationstyp.PARL_ABLEHNUNG
            titel = ABGELEHNT

        elif bool(re.search(rf"\b{ZURUECKGEZOGEN}\b", dok_abstract)):
            typ = Stationstyp.PARL_ZURUECKGZ
            titel = ZURUECKGEZOGEN

        if typ:
            new_station = Station.from_dict(station.to_dict() | {"typ": typ, "titel": titel})
            new_station.zp_start = station.zp_start + timedelta(minutes=30)

            return new_station

    return None
