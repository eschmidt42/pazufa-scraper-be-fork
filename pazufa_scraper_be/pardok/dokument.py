from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Literal, get_args

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, HttpUrl, PrivateAttr, ValidationError

# NOTE: imports are required for pydantic, moving into type check block not possible
from pazufa_scraper_be.pardok.utils import CoercedStrList, GermanDate  # noqa: TC001

if TYPE_CHECKING:
    from pazufa_scraper_be.pardok.vorgang import GesetzVorgang

logger = logging.getLogger(__name__)


class DokArt(StrEnum):
    """Document type identifier codes from the pardok XML feed."""

    PlPr = "PlPr"
    APr = "APr"
    GVBl = "GVBl"
    Drs = "Drs"


class ProtokollTyp(StrEnum):
    """URL abbreviation codes for the three variants of Protokoll documents."""

    Beschluss = "bp"
    Inhalt = "ip"
    Wort = "wp"


class DokTyp(StrEnum):
    """Document process type (DokTyp) values from the pardok XML feed."""

    APr = "APr"
    ABespr_Par_21_Abs_3_GO = "ABespr § 21 Abs. 3 GO"
    ABespr = "ABespr"
    Antr_GesEntw = "Antr (GesEntw)"
    Antr = "Antr"
    Ausschussberatung = "Ausschussberatung"
    ABericht_Zwischenbericht = "ABericht (Zwischenbericht)"
    Behandlung_im_Plenum = "Behandlung im Plenum"
    Bekannt_GVBl = "Bekannt (GVBl)"
    BeschlEmpf = "BeschlEmpf"
    GVBl = "GVBl"
    Lesung_I = "I. Lesung"
    Lesung_II = "II. Lesung"
    Lesung_III = "III. Lesung"
    Neufassung = "Neufassung"
    VorlBeschl = "VorlBeschl"
    VorlBeschl_GesEntw = "VorlBeschl (GesEntw)"
    VorlBeschl_GesEntwErg = "VorlBeschl (GesEntwErg)"
    AendAntr = "ÄndAntr"
    MittlgKenntn = "MittlgKenntn"
    MittlgKenntn_Zwischenber = "MittlgKenntn (Zwischenber)"
    MittlgKenntn_Schlussber = "MittlgKenntn (Schlussber)"


class BaseGesetzDokument(BaseModel):
    """Base Pydantic model shared by all document types in a Gesetz Vorgang."""

    model_config = ConfigDict(extra="forbid", revalidate_instances="always", populate_by_name=True)
    _vorgang: GesetzVorgang | None = PrivateAttr(default=None)

    art: DokArt = Field(alias="DokArt")
    art_l: str = Field(alias="DokArtL")

    herk: str = Field(alias="DHerk")
    herk_l: str = Field(alias="DHerkL")

    typ: DokTyp = Field(alias="DokTyp")
    typ_l: Annotated[str, BeforeValidator(lambda x: "" if type(x) is dict else x)] = Field(alias="DokTypL")

    id: str = Field(alias="DBID")
    wp: int = Field(alias="Wp")
    reih_nr: int = Field(alias="ReihNr", gt=0)
    nr: str = Field(alias="DokNr")
    dat: GermanDate = Field(alias="DokDat")
    abstract: str | None = Field(default=None, alias="Abstract")

    lok_url: HttpUrl | None = Field(default=None, alias="LokURL")
    additional_urls: Annotated[list[HttpUrl] | None, BeforeValidator(lambda v: None if v == [] else [v] if isinstance(v, str) else v)] = Field(default=None)

    def set_vorgang(self, vorgang: GesetzVorgang) -> None:
        """Attach this document to its parent Vorgang."""
        self._vorgang = vorgang

    @property
    def vorgang(self) -> GesetzVorgang:
        """Return the parent Vorgang, raising RuntimeError if the document is standalone."""
        if self._vorgang is None:
            msg = "Dokument is standalone and is not attached to a Vorgang."
            raise RuntimeError(msg)

        return self._vorgang

    @property
    def all_urls(self) -> list[HttpUrl]:
        """Return all document URLs: primary URL followed by any additional URLs."""
        return ([self.lok_url] if self.lok_url else []) + (self.additional_urls or [])


class Protokoll(BaseGesetzDokument):
    """Base model for protocol documents (Plenarprotokoll, Ausschussprotokoll)."""

    dat: GermanDate | None = Field(default=None, alias="DokDat")  # ty: ignore[invalid-attribute-override]


class PlPrDokument(Protokoll):
    """Plenarprotokoll (PlPr) document."""

    art: Literal["PlPr"] = Field(alias="DokArt")  # ty: ignore[invalid-attribute-override]

    sb: str | None = Field(default=None, alias="Sb")
    redner: CoercedStrList = Field(default_factory=list, alias="Redner")


class APrDokument(Protokoll):
    """Ausschussprotokoll (APr) document."""

    art: Literal["APr"] = Field(alias="DokArt")  # ty: ignore[invalid-attribute-override]

    urheber: CoercedStrList = Field(default_factory=list, alias="Urheber")


class DeskTitelSbMixin:
    """Mixin providing desk, titel, and sb fields for documents."""

    desk: str | None = Field(default=None, alias="Desk")
    titel: str | None = Field(default=None, alias="Titel")
    sb: str | None = Field(default=None, alias="Sb")


class GVBlDokument(BaseGesetzDokument, DeskTitelSbMixin):
    """Gesetz- und Verordnungsblatt (GVBl) document."""

    art: Literal["GVBl"] = Field(alias="DokArt")  # ty: ignore[invalid-attribute-override]

    vk_dat: GermanDate = Field(alias="VkDat")
    jg: str = Field(alias="Jg")
    h_nr: str = Field(alias="HNr")
    nr: str | None = Field(default=None, alias="DokNr")  # ty: ignore[invalid-attribute-override]


class DrsDokument(BaseGesetzDokument, DeskTitelSbMixin):
    """Drucksache (Drs) document."""

    art: Literal["Drs"] = Field(alias="DokArt")  # ty: ignore[invalid-attribute-override]

    urheber: CoercedStrList = Field(default_factory=list, alias="Urheber")

    def model_post_init(self, _context: object) -> None:
        """Set Urheber for Vorlage zur Beschlussfassung Drucksachen."""
        is_relevant_typ = self.typ in [DokTyp.VorlBeschl_GesEntw, DokTyp.VorlBeschl_GesEntwErg]

        if is_relevant_typ:
            self.urheber = ["Landesregierung"]


AnyGesetzDokument = PlPrDokument | GVBlDokument | APrDokument | DrsDokument


def parse_dokument(data: dict | AnyGesetzDokument) -> AnyGesetzDokument | None:
    """Parse a raw dict or existing model into the appropriate AnyGesetzDokument subtype."""
    if isinstance(data, get_args(AnyGesetzDokument)):
        return data

    if not isinstance(data, dict):
        msg = f"Expected dict, got {type(data)}"
        raise TypeError(msg)

    art = data.get("DokArt")
    mapping: dict[str, type[AnyGesetzDokument]] = {
        DokArt.PlPr: PlPrDokument,
        DokArt.APr: APrDokument,
        DokArt.GVBl: GVBlDokument,
        DokArt.Drs: DrsDokument,
    }
    dokument_class = mapping.get(art)

    if dokument_class is None:
        msg = f"Unknown DokArt: {art}. Has to be one of: {', '.join(mapping.keys())}."
        raise ValueError(msg)

    try:
        dokument = dokument_class(**data)

    except ValidationError:
        msg = f"Ignoring invalid Dokument: {data['DBID']}"
        logger.info(msg)
        dokument = None

    return dokument
