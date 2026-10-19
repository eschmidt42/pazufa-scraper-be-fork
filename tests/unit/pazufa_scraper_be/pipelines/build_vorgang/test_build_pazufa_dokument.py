from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from pazufa_corelib.api_client.models import Autor
from pazufa_corelib.api_client.models import Doktyp as PaZuFa_DokTyp
from pazufa_corelib.api_client.types import UNSET
from pydantic import HttpUrl

from pazufa_scraper_be.cache import Cache, Key
from pazufa_scraper_be.pardok import DokTyp
from pazufa_scraper_be.pardok.dokument import (
    AnyGesetzDokument,
    APrDokument,
    BaseGesetzDokument,
    DokArt,
    DrsDokument,
    GVBlDokument,
    PlPrDokument,
    ProtokollTyp,
)
from pazufa_scraper_be.pardok.vorgang import GesetzVorgang
from pazufa_scraper_be.pipelines.build_vorgang.build_pazufa_dokument import (
    _check_summary_file,
    _check_text_file,
    _clean_urheber,
    _compute_and_get_hashes,
    _get_autoren,
    _get_drucksnr,
    _get_titel,
    _get_typ,
    _get_zeitpunkte,
    _get_zp_modifiziert,
    _get_zp_referenz,
    _get_zusammenfassung,
    build_pazufa_dokument,
)

if TYPE_CHECKING:
    from pathlib import Path

from tests.unit.pazufa_scraper_be.helpers import build_gesetz_vorgang_data


@pytest.fixture
def gesetz_vorgang_data() -> dict[str, Any]:
    """Provides a basic GesetzVorgang dict instance."""
    return {}


@pytest.mark.parametrize(
    ("dok_art", "dok_typ", "expected_pazufa_typ"),
    [
        # Gesetzentwuerfe
        (DokArt.Drs, DokTyp.Antr_GesEntw, PaZuFa_DokTyp.ENTWURF),
        (DokArt.Drs, DokTyp.VorlBeschl_GesEntw, PaZuFa_DokTyp.ENTWURF),
        (DokArt.Drs, DokTyp.VorlBeschl_GesEntwErg, PaZuFa_DokTyp.ENTWURF),
        # Lesungen
        (DokArt.PlPr, DokTyp.Behandlung_im_Plenum, PaZuFa_DokTyp.REDEPROTOKOLL),
        (DokArt.PlPr, DokTyp.Lesung_I, PaZuFa_DokTyp.REDEPROTOKOLL),
        (DokArt.PlPr, DokTyp.Lesung_II, PaZuFa_DokTyp.REDEPROTOKOLL),
        # Ausschussberatung und Beschlussempfehlung
        (DokArt.APr, DokTyp.Ausschussberatung, PaZuFa_DokTyp.REDEPROTOKOLL),
        (DokArt.APr, DokTyp.ABespr_Par_21_Abs_3_GO, PaZuFa_DokTyp.REDEPROTOKOLL),
        (DokArt.APr, DokTyp.APr, PaZuFa_DokTyp.REDEPROTOKOLL),
        (DokArt.APr, DokTyp.BeschlEmpf, PaZuFa_DokTyp.BESCHLUSSEMPF),
        (DokArt.Drs, DokTyp.BeschlEmpf, PaZuFa_DokTyp.BESCHLUSSEMPF),
        # Gesetzesblatt
        (DokArt.GVBl, DokTyp.GVBl, PaZuFa_DokTyp.GESETZ),
        (DokArt.GVBl, DokTyp.Bekannt_GVBl, PaZuFa_DokTyp.SONSTIG),
        (DokArt.GVBl, DokTyp.Neufassung, PaZuFa_DokTyp.GESETZ),
        # Verschiedenes
        (DokArt.Drs, DokTyp.AendAntr, PaZuFa_DokTyp.ANTRAG),
        (DokArt.Drs, DokTyp.Antr, PaZuFa_DokTyp.ANTRAG),
    ],
)
def test_get_typ(base_dok_data: dict[str, Any], dok_art: DokArt, dok_typ: DokTyp, expected_pazufa_typ: PaZuFa_DokTyp) -> None:
    """Verify mapping of (DokArt, DokTyp) to PaZuFa Doktyp for the mapped cases."""
    gesetz_dokument = BaseGesetzDokument.model_validate(base_dok_data)
    gesetz_dokument.art = dok_art
    gesetz_dokument.typ = dok_typ

    actual_pazufa_typ = _get_typ(gesetz_dokument)

    assert actual_pazufa_typ == expected_pazufa_typ


def test_get_typ_fallback(base_dok_data: dict[str, Any], base_vorgang_data: dict[str, Any], caplog: pytest.LogCaptureFixture) -> None:
    """Verify mapping of (DokArt, DokTyp) to PaZuFa Doktyp for the fallback case."""
    # random (*promise*) non-mapped combination
    dok_art, dok_typ, expected_pazufa_typ = (DokArt.GVBl, DokTyp.Antr_GesEntw, PaZuFa_DokTyp.SONSTIG)

    gesetz_dokument = BaseGesetzDokument.model_validate(base_dok_data)
    gesetz_dokument.art = dok_art
    gesetz_dokument.typ = dok_typ

    gesetz_vorgang_data = build_gesetz_vorgang_data(
        base_vorgang_data=base_vorgang_data,
        dok_datas=[base_dok_data],
        neben_eintrag_data=[
            {"ReihNr": 1, "Desk": "Desk 1"},
            {"ReihNr": 2, "Desk": "Desk 2"},
        ],
    )
    gesetz_vorgang = GesetzVorgang.model_validate(gesetz_vorgang_data)
    gesetz_dokument.set_vorgang(gesetz_vorgang)

    caplog.set_level(logging.INFO)

    actual_pazufa_typ = _get_typ(gesetz_dokument)

    assert actual_pazufa_typ == expected_pazufa_typ
    assert "Using fallback for DokTyp" in caplog.text


@pytest.mark.parametrize(
    ("fixture_name", "dokument_class", "expected_drucksnr"),
    [
        ("drs_data", DrsDokument, "123/2024"),
        ("plpr_data", PlPrDokument, "123/2024"),
        ("apr_data", APrDokument, "123/2024-wp"),
        ("gvbl_data", GVBlDokument, "12345/2024"),
        ("base_dok_data", BaseGesetzDokument, ""),
    ],
)
def test_get_drucksnr(
    tmp_path: Path, request: pytest.FixtureRequest, fixture_name: str, dokument_class: type[BaseGesetzDokument], expected_drucksnr: str
) -> None:
    """Verify Durchsachennummer assignment."""
    data = request.getfixturevalue(fixture_name)
    dokument = dokument_class.model_validate(data)
    cache = Cache(base_dir=tmp_path, name=expected_drucksnr)

    drucksnr = _get_drucksnr(dokument, cache=cache)
    assert drucksnr == expected_drucksnr


@pytest.mark.parametrize(
    ("dok_class", "fixture_name", "expected_titel"),
    [
        (GVBlDokument, "gvbl_data", "Title GVBl"),
        (DrsDokument, "drs_data", "Title Drs"),
    ],
)
def test_get_titel_returns_titel_string(
    tmp_path: Path,
    request: pytest.FixtureRequest,
    dok_class: type[GVBlDokument | DrsDokument],
    fixture_name: str,
    expected_titel: str,
) -> None:
    """Verify that a non-None titel field is returned directly for GVBl and Drs documents."""
    data = request.getfixturevalue(fixture_name)
    dokument = dok_class.model_validate(data)
    cache = Cache(base_dir=tmp_path, name="document-folder")

    assert _get_titel(dokument, cache) == expected_titel


@pytest.mark.parametrize(
    ("document_name_suffix", "expected_titel"),
    [
        (f"-{ProtokollTyp.Beschluss}", "Ausschuss Beschlussprotokoll - 123/2024"),
        (f"-{ProtokollTyp.Inhalt}", "Ausschuss Inhaltsprotokoll - 123/2024"),
        (f"-{ProtokollTyp.Wort}", "Ausschuss Wortprotokoll - 123/2024"),
    ],
)
def test_get_titel_apr(tmp_path: Path, apr_data: dict[str, Any], document_name_suffix: str, expected_titel: str) -> None:
    """Verify APrDokument title is derived from cache dir suffix."""
    dokument = APrDokument.model_validate(apr_data)
    dokument.lok_url = HttpUrl(f"https://example.com/doc123-{document_name_suffix}.pdf")
    cache = Cache(base_dir=tmp_path, name=f"document-folder/doc123-{document_name_suffix}")

    assert _get_titel(dokument, cache) == expected_titel


@pytest.mark.parametrize(
    ("dok_typ", "expected_titel"),
    [
        (DokTyp.BeschlEmpf, "Ausschuss Beschlussempfehlung - 123/2024"),
        (DokTyp.AendAntr, "Änderungsantrag - 123/2024"),
    ],
)
def test_get_titel_drs_typ(tmp_path: Path, drs_data: dict[str, Any], dok_typ: DokTyp, expected_titel: str) -> None:
    """Verify DrsDokument title is derived from DokTyp when titel is None."""
    data = {**drs_data, "Titel": None, "DokTyp": str(dok_typ)}
    dokument = DrsDokument.model_validate(data)
    cache = Cache(base_dir=tmp_path, name="document-folder")

    assert _get_titel(dokument, cache) == expected_titel


def test_get_titel_gvbl_fallback(tmp_path: Path, gvbl_data: dict[str, Any]) -> None:
    """Verify GVBlDokument falls back to HNr/Jg when titel is None."""
    data = {**gvbl_data, "Titel": None}
    dokument = GVBlDokument.model_validate(data)
    cache = Cache(base_dir=tmp_path, name="document-folder")

    assert _get_titel(dokument, cache) == "Gesetz- und Verordnungsblatt Nr. 12345/2024"


def test_get_titel_generic_fallback_with_nr(tmp_path: Path, plpr_data: dict[str, Any]) -> None:
    """Verify generic fallback returns '{art_l} - {nr}' for documents without a specific title rule."""
    dokument = PlPrDokument.model_validate(plpr_data)
    cache = Cache(base_dir=tmp_path, name="document-folder")

    assert _get_titel(dokument, cache) == "Plenumsprotokoll - 123/2024"


def test_compute_and_get_hashes(tmp_path: Path) -> None:
    """Verify PDF and extracted-text hashes include their MIME types and strategies."""
    cache = Cache(base_dir=tmp_path, name="document-folder")

    cache[Key.DOCUMENT] = b"document"
    cache[Key.TEXT] = "extracted text"

    hashes = _compute_and_get_hashes(cache)

    assert len(hashes) == 3
    assert {document_hash.mime for document_hash in hashes} == {"application/pdf", "text/plain"}
    assert all(document_hash.value for document_hash in hashes)


def test_get_zusammenfassung(tmp_path: Path) -> None:
    """Verify summary text is converted into a full-LLM summary tuple."""
    cache = Cache(base_dir=tmp_path, name="document-folder")
    cache[Key.SUMMARY] = "summary"

    result = _get_zusammenfassung(cache)

    assert isinstance(result, list)
    assert [(item.inhalt, item.typ) for item in result] == [("summary", "full-llm")]


def test_get_zusammenfassung_missing(tmp_path: Path) -> None:
    """Verify UNSET is returned when no summary file exists."""
    cache = Cache(base_dir=tmp_path, name="document-folder")

    assert _get_zusammenfassung(cache) is UNSET


def test_build_pazufa_dokument_missing_text_file(
    tmp_path: Path, plpr_data: dict[str, Any], base_vorgang_data: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """Verify building stops when the required extracted text file is missing."""
    dokument = PlPrDokument.model_validate(plpr_data)
    cache = Cache(base_dir=tmp_path, name="document-folder")
    dokument.set_vorgang(GesetzVorgang.model_validate(base_vorgang_data))

    caplog.set_level(logging.WARNING)
    result = build_pazufa_dokument(dokument, cache, HttpUrl("https://example.com/doc123"))

    assert result is None
    assert "Text file does not exist" in caplog.text


def test_build_pazufa_dokument_without_summary(
    tmp_path: Path, plpr_data: dict[str, Any], base_vorgang_data: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """Verify a document is built with an UNSET summary when the optional summary is missing."""
    cache = Cache(base_dir=tmp_path, name="document-folder")
    dokument = PlPrDokument.model_validate(plpr_data)
    dokument.set_vorgang(GesetzVorgang.model_validate(base_vorgang_data))

    cache[Key.DOCUMENT] = b"document"
    cache[Key.TEXT] = "some text"

    caplog.set_level(logging.INFO)
    result = build_pazufa_dokument(dokument, cache, HttpUrl("https://example.com/doc123"))

    assert result is not None
    assert result.zusammenfassung is UNSET
    assert "Summary file does not exist" in caplog.text


@pytest.mark.parametrize(
    ("input_text", "expected_text"),
    [
        ("Author Name", "Author Name"),
        ("Author Name(federführend)", "Author Name"),
        ("Author Name  (federführend)", "Author Name"),
        ("Author Name	(federführend)", "Author Name"),
        ("Author Name (federführend)", "Author Name"),
        ("Author Name (FEDERFÜHREND)", "Author Name"),
        (" Author Name (federführend) ", "Author Name"),
        ("Vorname (federführend) Nachname (federführend)", "Vorname Nachname"),
        ("(federführend)", ""),
        ("Name (federführend) Extra", "Name Extra"),
    ],
)
def test_clean_urheber(input_text: str, expected_text: str) -> None:
    """Verify that urheber strings are cleaned of '(federführend)' suffixes and whitespace."""
    assert _clean_urheber(input_text) == expected_text


@pytest.mark.parametrize(
    ("last_modified", "expected_date"),
    [
        (datetime(2024, 5, 10, 12, 34, 56, tzinfo=UTC), datetime(2024, 5, 10, tzinfo=UTC)),
        (datetime(2024, 12, 31, 23, 59, 59, tzinfo=UTC), datetime(2024, 12, 31, tzinfo=UTC)),
    ],
)
def test_get_zp_modifiziert_with_last_modified(tmp_path: Path, plpr_data: dict[str, Any], last_modified: datetime, expected_date: datetime) -> None:
    """Verify that if LAST_MODIFIED.txt is present, it's used and normalized to midnight UTC."""
    cache = Cache(base_dir=tmp_path, name="document-folder")
    cache[Key.LAST_MODIFIED] = last_modified

    dokument = PlPrDokument.model_validate(plpr_data)

    actual_date = _get_zp_modifiziert(dokument, cache)
    assert actual_date == expected_date


def test_get_zp_modifiziert_with_dat_fallback(tmp_path: Path, plpr_data: dict[str, Any]) -> None:
    """Verify that if LAST_MODIFIED.txt is missing, the document's dat field is used."""
    cache = Cache(base_dir=tmp_path, name="document-folder")

    data = {**plpr_data, "DokDat": "15.06.2024"}
    dokument = PlPrDokument.model_validate(data)
    expected_date = datetime(2024, 6, 15, tzinfo=UTC)

    actual_date = _get_zp_modifiziert(dokument, cache)
    assert actual_date == expected_date


def test_get_zp_modifiziert_raises_value_error(tmp_path: Path, plpr_data: dict[str, Any]) -> None:
    """Verify that ValueError is raised if no data source is available."""
    cache = Cache(base_dir=tmp_path, name="document-folder")

    data = {**plpr_data, "DokDat": None}
    dokument = PlPrDokument.model_validate(data)

    with pytest.raises(ValueError, match=r"Could not resolve zp_modifiziert."):
        _get_zp_modifiziert(dokument, cache)


def test_get_zp_referenz_with_dat(plpr_data: dict[str, Any]) -> None:
    """Verify that when dokument.dat is set, it is returned directly."""
    dokument = PlPrDokument.model_validate(plpr_data)

    actual_datetime = _get_zp_referenz(dokument)

    expected_date = datetime(2024, 5, 10, tzinfo=UTC)
    assert actual_datetime == expected_date


def test_get_zp_referenz_with_none_dat(base_vorgang_data: dict[str, Any], plpr_data: dict[str, Any], caplog: pytest.LogCaptureFixture) -> None:
    """Verify that when dokument.dat is None, a warning is logged and datetime.now(tz=UTC) is returned."""
    data = {**plpr_data, "DokDat": None}
    dokument = PlPrDokument.model_validate(data)

    gesetz_vorgang_data = build_gesetz_vorgang_data(
        base_vorgang_data=base_vorgang_data,
        dok_datas=[data],
        neben_eintrag_data=[],
    )
    gesetz_vorgang = GesetzVorgang.model_validate(gesetz_vorgang_data)
    dokument.set_vorgang(gesetz_vorgang)

    caplog.set_level(logging.WARNING)

    before_call = datetime.now(tz=UTC)
    actual_datetime = _get_zp_referenz(dokument)
    after_call = datetime.now(tz=UTC)

    assert before_call <= actual_datetime <= after_call
    assert "Using fallback for document timestamp zp_referenz" in caplog.text


def test_get_zeitpunkte(tmp_path: Path, plpr_data: dict[str, Any]) -> None:
    """Verify _get_zeitpunkte returns correct zp_erstellt, zp_referenz, and zp_modifiziert values."""
    cache = Cache(base_dir=tmp_path, name="document-folder")

    dokument = PlPrDokument.model_validate(plpr_data)

    expected_dt = datetime(2024, 5, 10, tzinfo=UTC)
    assert _get_zeitpunkte(dokument, cache) == (UNSET, expected_dt, expected_dt)


@pytest.mark.parametrize(
    ("fixture_name", "dokument", "urheber", "expected_autoren"),
    [
        (
            "drs_data",
            DrsDokument,
            ["Author 1", "Ausschuss für Finanzen", "Another Author"],
            [Autor(organisation="Author 1"), Autor(organisation="Ausschuss für Finanzen"), Autor(organisation="Another Author")],
        ),
        (
            "apr_data",
            APrDokument,
            ["Ausschuss für Recht", "Private Person", "Interparl. Ausschuss"],
            [Autor(organisation="Ausschuss für Recht"), Autor(organisation="Interparl. Ausschuss")],
        ),
        (
            "gvbl_data",
            GVBlDokument,
            ["Author 1", "Ausschuss für Finanzen"],
            [],
        ),
        (
            "drs_data",
            DrsDokument,
            [],
            [],
        ),
    ],
)
def test_get_autoren(request: pytest.FixtureRequest, fixture_name: str, dokument: AnyGesetzDokument, urheber: list[str], expected_autoren: list[Autor]) -> None:
    """Verify extraction and filtering of authors based on document type."""
    data = request.getfixturevalue(fixture_name)

    if dokument in (DrsDokument, APrDokument):
        data["Urheber"] = urheber

    doc = dokument.model_validate(data)
    actual_autoren = _get_autoren(doc)

    assert actual_autoren == expected_autoren


@pytest.mark.parametrize(
    ("file_exists", "expected_result", "log_level"),
    [
        (True, False, None),
        (False, True, logging.WARNING),
    ],
)
def test_check_text_file(  # noqa: PLR0913, PLR0917
    tmp_path: Path,
    base_vorgang_data: dict[str, Any],
    plpr_data: dict[str, Any],
    file_exists: bool,
    expected_result: bool,
    log_level: logging._Level | None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify that _check_text_file correctly identifies missing text files and logs warnings."""
    dokument = PlPrDokument.model_validate(plpr_data)
    cache = Cache(base_dir=tmp_path, name="document-folder")

    gesetz_vorgang_data = build_gesetz_vorgang_data(
        base_vorgang_data=base_vorgang_data,
        dok_datas=[plpr_data],
        neben_eintrag_data=[],
    )
    gesetz_vorgang = GesetzVorgang.model_validate(gesetz_vorgang_data)
    dokument.set_vorgang(gesetz_vorgang)

    if file_exists:
        cache[Key.TEXT] = "some text"

    if log_level:
        caplog.set_level(log_level)

    result = _check_text_file(dokument, cache)
    assert result == expected_result

    if not file_exists:
        assert "Text file does not exist" in caplog.text


@pytest.mark.parametrize(
    ("file_exists", "expected_result", "log_level"),
    [
        (True, False, None),
        (False, True, logging.INFO),
    ],
)
def test_check_summary_file(  # noqa: PLR0913, PLR0917
    tmp_path: Path,
    base_vorgang_data: dict[str, Any],
    plpr_data: dict[str, Any],
    file_exists: bool,
    expected_result: bool,
    log_level: logging._Level | None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify that _check_summary_file correctly identifies missing summary files and logs info."""
    dokument = PlPrDokument.model_validate(plpr_data)
    cache = Cache(base_dir=tmp_path, name="document-folder")

    gesetz_vorgang_data = build_gesetz_vorgang_data(
        base_vorgang_data=base_vorgang_data,
        dok_datas=[plpr_data],
        neben_eintrag_data=[],
    )
    gesetz_vorgang = GesetzVorgang.model_validate(gesetz_vorgang_data)
    dokument.set_vorgang(gesetz_vorgang)

    if file_exists:
        cache[Key.SUMMARY] = "some summary"

    if log_level:
        caplog.set_level(log_level)

    result = _check_summary_file(dokument, cache)
    assert result == expected_result

    if not file_exists:
        assert "Summary file does not exist" in caplog.text


def test_build_pazufa_dokument_happy_path(tmp_path: Path, plpr_data: dict[str, Any], base_vorgang_data: dict[str, Any]) -> None:
    """Verify the happy path for building a PaZuFaDokument."""
    cache = Cache(base_dir=tmp_path, name="document-folder")

    document_content = b"This is the document content as bytes."
    text_content = "This is the extracted text content."
    summary_content = "This is a short summary."

    cache[Key.DOCUMENT] = document_content
    cache[Key.TEXT] = text_content
    cache[Key.SUMMARY] = summary_content
    cache[Key.LAST_MODIFIED] = datetime(2024, 5, 10, 12, 34, 56, tzinfo=UTC)

    dokument = PlPrDokument.model_validate(plpr_data)

    gesetz_vorgang = GesetzVorgang.model_validate(base_vorgang_data)
    dokument.set_vorgang(gesetz_vorgang)

    url = HttpUrl("https://example.com/doc123")

    result = build_pazufa_dokument(dokument, cache, url)

    assert result is not None
    assert result.volltext == text_content
    assert isinstance(result.zusammenfassung, list)
    assert len(result.zusammenfassung) == 1
    assert result.zusammenfassung[0].inhalt == summary_content
    assert result.link == str(url)

    assert result.zp_modifiziert == datetime(2024, 5, 10, tzinfo=UTC)
