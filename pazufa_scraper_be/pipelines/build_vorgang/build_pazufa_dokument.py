from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pazufa_corelib.api_client.models import Autor, Doktyp, DokumentHash, HashStrategy, Mime, Zusammenfassungstupel
from pazufa_corelib.api_client.models import Dokument as PaZuFaDokument
from pazufa_corelib.api_client.types import UNSET, Unset
from pazufa_corelib.normalization import hash_bytes, hash_text

from pazufa_scraper_be.cache import Key
from pazufa_scraper_be.pardok import APrDokument, BaseGesetzDokument, DokTyp, DrsDokument, GVBlDokument, PlPrDokument
from pazufa_scraper_be.pardok.dokument import AnyGesetzDokument, DokArt, ProtokollTyp
from pazufa_scraper_be.pipelines.build_vorgang.utils import get_document_schlagworte

if TYPE_CHECKING:
    from pydantic import HttpUrl

    from pazufa_scraper_be.cache import Cache

logger = logging.getLogger(__name__)

# Maps form DokArt-DokTyp combinations defined in this package to DokTyp values in the PaZuFa core package.
_PARDOK_PAZUFA_DOKTYP_MAPPING = {
    # Gesetzentwuerfe
    (DokArt.Drs, DokTyp.Antr_GesEntw): Doktyp.ENTWURF,
    (DokArt.Drs, DokTyp.VorlBeschl_GesEntw): Doktyp.ENTWURF,
    (DokArt.Drs, DokTyp.VorlBeschl_GesEntwErg): Doktyp.ENTWURF,
    # Lesungen
    (DokArt.PlPr, DokTyp.Behandlung_im_Plenum): Doktyp.REDEPROTOKOLL,
    (DokArt.PlPr, DokTyp.Lesung_I): Doktyp.REDEPROTOKOLL,
    (DokArt.PlPr, DokTyp.Lesung_II): Doktyp.REDEPROTOKOLL,
    # Ausschussberatung und Beschlussempfehlung
    (DokArt.APr, DokTyp.Ausschussberatung): Doktyp.REDEPROTOKOLL,
    (DokArt.APr, DokTyp.ABespr_Par_21_Abs_3_GO): Doktyp.REDEPROTOKOLL,
    (DokArt.APr, DokTyp.APr): Doktyp.REDEPROTOKOLL,
    (DokArt.APr, DokTyp.BeschlEmpf): Doktyp.BESCHLUSSEMPF,
    (DokArt.Drs, DokTyp.BeschlEmpf): Doktyp.BESCHLUSSEMPF,
    # Gesetzesblatt
    (DokArt.GVBl, DokTyp.GVBl): Doktyp.GESETZ,
    (DokArt.GVBl, DokTyp.Bekannt_GVBl): Doktyp.SONSTIG,
    (DokArt.GVBl, DokTyp.Neufassung): Doktyp.GESETZ,
    # Verschiedenes
    (DokArt.Drs, DokTyp.AendAntr): Doktyp.ANTRAG,
    (DokArt.Drs, DokTyp.Antr): Doktyp.ANTRAG,
}


def _get_typ(dokument: BaseGesetzDokument) -> Doktyp:
    if ret_val := _PARDOK_PAZUFA_DOKTYP_MAPPING.get((dokument.art, dokument.typ)):
        return ret_val

    msg = f"[{dokument.vorgang.id} - {dokument.id}]: Using fallback for DokTyp. Got the following (DokArt, DokTyp): ({dokument.art}, {dokument.typ})"
    logger.info(msg)
    return Doktyp.SONSTIG


def _get_drucksnr(dokument: BaseGesetzDokument, cache: Cache) -> str:
    if isinstance(dokument, (DrsDokument, PlPrDokument)):
        return dokument.nr

    # Ausschussprotokolle append their type abbreviation to avoid Backend treating them as the same document due to the same Nr.
    if isinstance(dokument, APrDokument) and dokument.lok_url:
        document_name_suffix = cache.name[-3:]
        return f"{dokument.nr}{document_name_suffix}"

    if isinstance(dokument, GVBlDokument):
        return f"{dokument.h_nr}/{dokument.jg}"

    return ""


def _compute_and_get_hashes(cache: Cache) -> list[DokumentHash]:
    document_hashes = [(Mime.APPLICATIONPDF, x) for x in hash_bytes(cache.get_bytes(Key.DOCUMENT))]
    text_hash = (Mime.TEXTPLAIN, hash_text(cache.get_text(Key.TEXT)))
    hashes = [*document_hashes, text_hash]

    return [DokumentHash(mime=mime, strategy=HashStrategy(type_), value=content) for mime, (content, type_) in hashes]


def _get_zusammenfassung(cache: Cache) -> list[Zusammenfassungstupel] | Unset:
    if Key.SUMMARY not in cache:
        return UNSET

    summary = cache.get_text(Key.SUMMARY)
    return [Zusammenfassungstupel(inhalt=summary, typ="full-llm")]


_APR_SUFFIX_LABELS: dict[ProtokollTyp, str] = {
    ProtokollTyp.Beschluss: "Ausschuss Beschlussprotokoll",
    ProtokollTyp.Inhalt: "Ausschuss Inhaltsprotokoll",
    ProtokollTyp.Wort: "Ausschuss Wortprotokoll",
}

_DRS_TYP_LABELS: dict[DokTyp, str] = {
    DokTyp.BeschlEmpf: "Ausschuss Beschlussempfehlung",
    DokTyp.AendAntr: "Änderungsantrag",
}


def _get_titel(dokument: AnyGesetzDokument, cache: Cache) -> str:
    """Derive a human-readable title for a document, falling back to its art label."""
    if isinstance(dokument, (GVBlDokument, DrsDokument)) and isinstance(dokument.titel, str):
        return dokument.titel

    drucksnr = _get_drucksnr(dokument, cache=cache)
    suffix = f" - {drucksnr}" if drucksnr else ""

    if isinstance(dokument, APrDokument) and dokument.lok_url:
        for typ, label in _APR_SUFFIX_LABELS.items():
            if cache.name.endswith(f"-{typ}"):
                return f"{label}{suffix[:-3]}"  # for Dokument Titel, we do not need the '-ip' suffix

    if isinstance(dokument, DrsDokument) and (label := _DRS_TYP_LABELS.get(dokument.typ)):
        return f"{label}{suffix}"

    if isinstance(dokument, GVBlDokument):
        return f"Gesetz- und Verordnungsblatt Nr. {drucksnr}"

    if dokument.nr is not None:
        return f"{dokument.art_l} - {dokument.nr}"

    msg = f"[{dokument.vorgang.id} - {dokument.id}]: Using fallback (DokArtL) for document titel."
    logger.info(msg)
    return dokument.art_l


def _clean_urheber(urheber: str) -> str:
    return re.sub(r"\s*\(federführend\)", "", urheber, flags=re.IGNORECASE).strip()


def _get_autoren(dokument: AnyGesetzDokument) -> list[Autor]:
    autoren = []

    if not isinstance(dokument, (DrsDokument, APrDokument)):
        return autoren

    is_apr = isinstance(dokument, APrDokument)

    for urheber in dokument.urheber:
        organisation = _clean_urheber(urheber)
        isnt_ausschuss = not bool(re.search("ausschuss", organisation, flags=re.IGNORECASE))

        if is_apr and isnt_ausschuss:
            continue

        autoren.append(
            Autor(
                organisation=organisation,
            )
        )

    return autoren


def _get_zp_modifiziert(dokument: AnyGesetzDokument, cache: Cache) -> datetime:
    if Key.LAST_MODIFIED in cache:
        dt = cache.get_timestamp(Key.LAST_MODIFIED)
        return datetime(dt.year, dt.month, dt.day, tzinfo=UTC)

    if dokument.dat is not None:
        return dokument.dat

    msg = "Could not resolve zp_modifiziert."
    raise ValueError(msg)


def _get_zp_referenz(dokument: AnyGesetzDokument) -> datetime:

    if dokument.dat is not None:
        return dokument.dat

    msg = f"[{dokument.vorgang.id} - {dokument.id}]: Using fallback for document timestamp zp_referenz."
    logger.warning(msg)
    return datetime.now(tz=UTC)


def _get_zeitpunkte(dokument: AnyGesetzDokument, cache: Cache) -> tuple[Unset | datetime, datetime, datetime]:
    """Extract timestamps relevant for document."""
    zp_referenz = _get_zp_referenz(dokument)
    zp_modifiziert = _get_zp_modifiziert(dokument, cache)

    # TODO(anyone): revisit this
    zp_erstellt = UNSET

    return zp_erstellt, zp_referenz, zp_modifiziert


def _check_text_file(dokument: AnyGesetzDokument, cache: Cache) -> bool:
    text_file_missing = Key.TEXT not in cache

    if text_file_missing:
        msg = f"[{dokument.vorgang.id} - {dokument.id}]: Text file does not exist, ignoring Dokument."
        logger.warning(msg)

    return text_file_missing


def _check_summary_file(dokument: AnyGesetzDokument, cache: Cache) -> bool:
    summary_file_missing = Key.SUMMARY not in cache

    if summary_file_missing:
        msg = f"[{dokument.vorgang.id} - {dokument.id}]: Summary file does not exist."
        logger.info(msg)

    return summary_file_missing


def build_pazufa_dokument(dokument: AnyGesetzDokument, cache: Cache, url: HttpUrl) -> PaZuFaDokument | None:
    """Build a PaZuFaDokument from a cached document, returning None if required files are missing."""
    text_file_missing = _check_text_file(dokument, cache=cache)
    _check_summary_file(dokument=dokument, cache=cache)

    if text_file_missing:
        return None

    volltext = cache.get_text(Key.TEXT)
    zp_erstellt, zp_referenz, zp_modifiziert = _get_zeitpunkte(dokument, cache=cache)

    return PaZuFaDokument(
        typ=_get_typ(dokument),
        titel=_get_titel(dokument, cache=cache),
        volltext=volltext,
        zp_erstellt=zp_erstellt,
        zp_referenz=zp_referenz,
        zp_modifiziert=zp_modifiziert,
        link=str(url),
        hash_=_compute_and_get_hashes(cache=cache),
        autoren=_get_autoren(dokument),
        schlagworte=get_document_schlagworte(dokument),
        drucksnr=_get_drucksnr(dokument, cache=cache),
        zusammenfassung=_get_zusammenfassung(cache=cache),
        # NOTE: Following should be revisited
        kurztitel=UNSET,
        vorwort=UNSET,
        meinung=UNSET,
    )
