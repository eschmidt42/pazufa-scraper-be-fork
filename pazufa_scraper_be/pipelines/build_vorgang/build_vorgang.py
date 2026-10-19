from __future__ import annotations

import logging
import re
import uuid
from typing import Self, cast
from uuid import UUID

from pazufa_corelib.api_client.models import Dokument, Ressort, Sachgebiet, Station, VgIdent, Vorgang, Vorgangstyp
from pazufa_corelib.api_client.models import Vorgang as PaZuFaVorgang
from pazufa_corelib.api_client.types import UNSET, Unset
from scrapy.exceptions import DropItem

from pazufa_scraper_be.constants import ANGENOMMEN, VERTAGT
from pazufa_scraper_be.pardok import APrDokument, DokTyp, DrsDokument, GesetzVorgang, GVBlDokument, PlPrDokument
from pazufa_scraper_be.pipelines._base import CachePipeline, StatsPipeline
from pazufa_scraper_be.pipelines.build_vorgang import build_pazufa_dokument
from pazufa_scraper_be.pipelines.build_vorgang.rules import (
    BackwardMergeRule,
    DropRule,
    ForwardMergeRule,
    TransformRule,
    apply_rules,
    get_change_abstract_transform_fn,
    get_change_urheber_transform_fn,
)
from pazufa_scraper_be.pipelines.build_vorgang.utils import (
    DokumentContainer,
    check_and_create_vote_outcome_station,
    get_document_schlagworte,
    get_station_typ_and_gremium,
    get_station_zeitpunkte,
    get_vorgang_schlagworte,
    uniqify,
)
from pazufa_scraper_be.pipelines.stats_counter import VorgangCounter

logger = logging.getLogger(__name__)


RULES = [
    DropRule(
        name="Drop Ausschussberatung '19/100' after Rejection for Vorgang 'V-435029'",
        when=lambda current: isinstance(current.pardok, APrDokument) and current.pardok.nr == "19/100" and current.pardok.vorgang.id == "V-435029",
    ),
    DropRule(
        name="Drop postponed Lesung",
        when=lambda current: (
            isinstance(current.pardok, PlPrDokument)
            and current.pardok.typ == DokTyp.Behandlung_im_Plenum
            and current.pardok.abstract is not None
            and bool(re.search(rf"\b{VERTAGT}\b", current.pardok.abstract))
        ),
    ),
    TransformRule(
        name="Change Autor/Urheber of Beschlussempfehlung '19/2984' to 'Ausschuss für Bildung, Jugend und Familie'",
        when=lambda current: isinstance(current.pardok, DrsDokument) and current.pardok.typ == DokTyp.BeschlEmpf and current.pardok.nr == "19/2984",
        transform_function=get_change_urheber_transform_fn("Ausschuss für Bildung, Jugend und Familie"),
    ),
    TransformRule(
        name="Change Abstract of Lesung '19/50' to 'Angenommen'",
        when=lambda current: isinstance(current.pardok, PlPrDokument) and current.pardok.typ == DokTyp.Lesung_II and current.pardok.nr == "19/50",
        transform_function=get_change_abstract_transform_fn(ANGENOMMEN),
    ),
    ForwardMergeRule(
        name="Merge Änderungsantrag onto next Lesung",
        when=lambda current: isinstance(current.pardok, DrsDokument) and current.pardok.typ == DokTyp.AendAntr,
        merge_into=lambda _, target: isinstance(target.pardok, PlPrDokument) and target.pardok.typ in (DokTyp.Lesung_I, DokTyp.Lesung_II, DokTyp.Lesung_III),
    ),
    BackwardMergeRule(
        name="Merge Lesungen split into multiple onto first of its kind",
        when=lambda current: isinstance(current.pardok, PlPrDokument) and current.pardok.typ in (DokTyp.Lesung_I, DokTyp.Lesung_II, DokTyp.Lesung_III),
        merge_into=lambda current, target: isinstance(target.pardok, PlPrDokument) and current.pardok.typ == target.pardok.typ,
    ),
    BackwardMergeRule(
        name="Merge Beschlussempfehlung onto prev. Ausschussberatung of the same Ausschuss",
        when=lambda current: isinstance(current.pardok, DrsDokument) and current.pardok.typ == DokTyp.BeschlEmpf,
        merge_into=lambda current, target: isinstance(target.pardok, APrDokument) and current.pazufa[0].autoren == target.pazufa[0].autoren,
    ),
    BackwardMergeRule(
        name="Merge all Gesetz- und Verordnungsblatt onto first one",
        when=lambda current: isinstance(current.pardok, GVBlDokument),
        merge_into=lambda _, target: isinstance(target.pardok, GVBlDokument),
    ),
    BackwardMergeRule(
        name="Merge Gesetzentwurf Ergänzung onto initial Gesetzentwurf",
        when=lambda current: isinstance(current.pardok, DrsDokument) and current.pardok.typ == DokTyp.VorlBeschl_GesEntwErg,
        merge_into=lambda _, target: isinstance(target.pardok, DrsDokument) and target.pardok.typ == DokTyp.VorlBeschl_GesEntw,
    ),
]


def _merge_schlagworte(document_schlagworte: list[str] | Unset, vorgang_schlagworte: list[str] | Unset) -> list[str] | Unset:
    """Merge vorgang schlagworte with schlagworte of this document schlagworte (deduplicated)."""
    schlagworte = uniqify((document_schlagworte or []) + (vorgang_schlagworte or []))

    if not schlagworte:
        schlagworte = UNSET

    return schlagworte


def _get_ids(vorgang: GesetzVorgang) -> list[VgIdent]:
    return [VgIdent(id=vorgang.id, typ="vorgnr"), VgIdent(id=vorgang.dokumente[0].id, typ="initdrucks")]


def _get_links(vorgang: GesetzVorgang) -> list[str]:
    return [f"https://pardok.parlament-berlin.de/portala/vorgang/{vorgang.id}"]


def _get_sachgebiete(vorgang: GesetzVorgang) -> list[Sachgebiet] | Unset:
    return [Sachgebiet(sys) for sys in vorgang.sys] or UNSET


def _get_ressort() -> Ressort | Unset | None:
    return UNSET


class BuildPaZuFaVorgang(CachePipeline, StatsPipeline):
    """Pipeline that converts a GesetzVorgang into a PaZuFa Vorgang API model."""

    # TODO(se-jaeger): refactor to reduce complexity
    async def process_item(self: Self, vorgang: GesetzVorgang) -> PaZuFaVorgang:  # noqa: C901
        """Build and return a PaZuFa Vorgang from a parsed GesetzVorgang."""
        if not isinstance(vorgang, GesetzVorgang):
            msg = f"Expected {GesetzVorgang.__name__} object but got {vorgang.__class__.__name__}."
            raise DropItem(msg)

        if len(vorgang.dokumente) == 1 and isinstance(vorgang.dokumente[0], GVBlDokument):
            self.increment_stats(VorgangCounter.DROP_OUT_OF_SCOPE)
            msg = f"[{vorgang.id}]: Out of scope. Single Gesetz- und Verordnungsblatt."
            raise DropItem(msg, log_level="INFO")

        dok_containers = []
        for pardok in vorgang.dokumente:
            pazufa = []
            for dokument_url in pardok.all_urls:
                cache = self.get_cache(document=pardok, document_url=dokument_url)

                pazufa_dokument = build_pazufa_dokument(dokument=pardok, cache=cache, url=dokument_url)

                if pazufa_dokument:
                    pazufa.append(pazufa_dokument)

            if len(pazufa) > 0:
                dok_containers.append(DokumentContainer(pardok, pazufa))

        if len(dok_containers) == 0:
            self.increment_stats(VorgangCounter.DROP_NO_DOCUMENTS)
            msg = f"[{vorgang.id}]: Could not create any Dokument from Vorgang."
            raise DropItem(msg)

        dok_containers = apply_rules(pardok_pazufa_doks=dok_containers, rules=RULES)

        if len(dok_containers) == 0:
            self.increment_stats(VorgangCounter.DROP_NO_STATIONS)
            msg = f"[{vorgang.id}]: Could not create any Stations."
            raise DropItem(msg)

        stationen: list[Station] = []
        for dok_container in dok_containers:
            station_typ, (gremium, gremium_federf) = get_station_typ_and_gremium(dok_container)
            zp_start, zp_modifiziert = get_station_zeitpunkte(dok_container)

            station = Station(
                api_id=uuid.uuid5(self.crawler.settings.get("SCRAPER_UUID"), f"Station-{dok_container.pardok.id}"),
                zp_start=zp_start,
                zp_modifiziert=zp_modifiziert,
                gremium=gremium,
                typ=station_typ,
                dokumente=cast("list[Dokument | UUID]", dok_container.pazufa),
                titel=dok_container.pardok.typ_l or UNSET,
                gremium_federf=gremium_federf,
                # NOTE: Following should be revisited
                link=UNSET,
                additional_links=UNSET,
                stellungnahmen=UNSET,
            )
            stationen.append(station)

            if dok_container.pardok.abstract is not None and (
                new_station := check_and_create_vote_outcome_station(station=station, dok_abstract=dok_container.pardok.abstract)
            ):
                new_station.api_id = uuid.uuid5(self.crawler.settings.get("SCRAPER_UUID"), f"Station-{dok_container.pardok.id}-{new_station.typ}")
                stationen.append(new_station)

        dokument = stationen[0].dokumente[0]
        if isinstance(dokument, Dokument):
            titel = dokument.titel
            initiatoren = dokument.autoren

        else:
            msg = f"[{vorgang.id}]: Could not create titel and autoren."
            raise DropItem(msg)

        vorgang_schlagworte = get_vorgang_schlagworte(vorgang)
        document_schlagworte = get_document_schlagworte(dok_containers[0].pardok)
        return Vorgang(
            api_id=uuid.uuid5(self.crawler.settings.get("SCRAPER_UUID"), vorgang.id),
            titel=titel,
            wahlperiode=self.wahlperiode,
            typ=Vorgangstyp.GG_LAND_PARL,
            initiatoren=initiatoren,
            stationen=stationen,
            ids=_get_ids(vorgang=vorgang),
            links=_get_links(vorgang=vorgang),
            sachgebiete=_get_sachgebiete(vorgang=vorgang),
            ressort=_get_ressort(),
            schlagworte=_merge_schlagworte(document_schlagworte=document_schlagworte, vorgang_schlagworte=vorgang_schlagworte),
            # NOTE: Following should be revisited
            verfassungsaendernd=False,
            kurztitel=UNSET,
            lobbyregister=UNSET,
        )
