from typing import Any

import pytest


@pytest.fixture
def base_dok_data() -> dict[str, Any]:
    """Return data shared by all BaseGesetzDokument derived documents."""
    return {
        "DokArt": "PlPr",
        "DokArtL": "Plenumsprotokoll",
        "DHerk": "Pardok",
        "DHerkL": "Pardok-System",
        "DokTyp": "Behandlung im Plenum",
        "DokTypL": "Behandlung im Plenum Typ",
        "DBID": "doc123",
        "Wp": 19,
        "ReihNr": 1,
        "DokNr": "123/2024",
        "DokDat": "10.05.2024",
        "Abstract": "This is a test abstract",
        "LokURL": "https://example.com/doc123",
    }


@pytest.fixture
def base_vorgang_data() -> dict[str, Any]:
    """Return base fixture data for a GesetzVorgang."""
    return {
        "VTyp": "Gesetz",
        "VTypL": "Gesetz-Typ",
        "VID": "vorg123",
        "ReihNr": 0,
        "VNr": "V123/2024",
        "VIR": "IR123",
        "VSys": ["1000"],
        "VSysL": ["System 1"],
    }


@pytest.fixture
def gvbl_data(base_dok_data: dict[str, Any]) -> dict[str, Any]:
    """Return fixture data for a GVBlDokument."""
    return {
        **base_dok_data,
        "DokArt": "GVBl",
        "VkDat": "11.05.2024",
        "Jg": "2024",
        "HNr": "12345",
        "DokNr": "678",
        "Desk": "Desk GVBl",
        "Titel": "Title GVBl",
        "Sb": "S. 123",
    }


@pytest.fixture
def drs_data(base_dok_data: dict[str, Any]) -> dict[str, Any]:
    """Return fixture data for a DrsDokument."""
    return {
        **base_dok_data,
        "DokArt": "Drs",
        "Urheber": ["Author B"],
        "Desk": "Desk Drs",
        "Titel": "Title Drs",
        "Sb": "S. 456",
    }


@pytest.fixture
def plpr_data(base_dok_data: dict[str, Any]) -> dict[str, Any]:
    """Return fixture data for a PlPrDokument."""
    return {
        **base_dok_data,
        "DokArt": "PlPr",
        "Sb": "Seite 1",
        "Redner": ["Speaker A", "Speaker B"],
    }


@pytest.fixture
def apr_data(base_dok_data: dict[str, Any]) -> dict[str, Any]:
    """Return fixture data for an APrDokument."""
    return {
        **base_dok_data,
        "DokArt": "APr",
        "Urheber": ["Author A"],
        "LokURL": "https://example.com/doc123-wp.pdf",
    }
