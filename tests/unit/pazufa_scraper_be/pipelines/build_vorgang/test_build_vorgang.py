import datetime as dt
from typing import Any

import pytest
from pazufa_corelib.api_client.models import Doktyp
from pazufa_corelib.api_client.models import Dokument as PaZuFaDokument
from pazufa_corelib.api_client.types import UNSET

from pazufa_scraper_be.pardok import PlPrDokument
from pazufa_scraper_be.pipelines.build_vorgang.build_vorgang import _merge_schlagworte
from pazufa_scraper_be.pipelines.build_vorgang.utils import DokumentContainer


def _make_dok_container(pardok_data: dict[str, Any], pazufa_doks: list[PaZuFaDokument]) -> DokumentContainer:

    pardok = PlPrDokument.model_validate(pardok_data)
    return DokumentContainer(pardok=pardok, pazufa=pazufa_doks)


def _make_pazufa_dokument(schlagworte: list[str] | None = None) -> PaZuFaDokument:
    return PaZuFaDokument(
        typ=Doktyp.ENTWURF,
        titel="Test",
        volltext="",
        zp_modifiziert=dt.datetime(2024, 1, 1, tzinfo=dt.UTC),
        zp_referenz=dt.datetime(2024, 1, 1, tzinfo=dt.UTC),
        link="https://example.com/doc",
        hash_="abc123",
        autoren=[],
        schlagworte=schlagworte if schlagworte is not None else UNSET,
    )


@pytest.mark.parametrize(
    ("doc_schlagworte", "vorgang_schlagworte", "expected"),
    [
        ([], [], UNSET),
        (UNSET, UNSET, UNSET),
    ],
)
def test__merge_schlagworte__both_empty_or_unset_returns_unset(doc_schlagworte: list, vorgang_schlagworte: list, expected: list) -> None:
    """Test both that empty or UNSET schlagworte on both levels returns UNSET."""
    result = _merge_schlagworte(document_schlagworte=doc_schlagworte, vorgang_schlagworte=vorgang_schlagworte)
    assert result == expected


@pytest.mark.parametrize(
    ("doc_schlagworte", "vorgang_schlagworte", "expected"),
    [
        ([1], UNSET, [1]),
        ([None], UNSET, [None]),
        (["Klimaschutz"], UNSET, ["Klimaschutz"]),
        (["Klimaschutz", "Klimaschutz"], UNSET, ["Klimaschutz"]),
        (["Klimaschutz", "Verkehr"], UNSET, ["Klimaschutz", "Verkehr"]),
        (["Klimaschutz", "Verkehr", "Klimaschutz"], UNSET, ["Klimaschutz", "Verkehr"]),
    ],
)
def test__merge_schlagworte__return_deduplicated_doc_schlagworte_if_vorgang_unset(doc_schlagworte: list, vorgang_schlagworte: list, expected: list) -> None:
    """Test if Vorgang Schlagworte are not given, remove deduplicated Dokument Schlagworte."""
    result = _merge_schlagworte(document_schlagworte=doc_schlagworte, vorgang_schlagworte=vorgang_schlagworte)
    assert result == expected


@pytest.mark.parametrize(
    ("doc_schlagworte", "vorgang_schlagworte", "expected"),
    [
        (UNSET, [1], [1]),
        (UNSET, [None], [None]),
        (UNSET, ["Klimaschutz"], ["Klimaschutz"]),
        (UNSET, ["Klimaschutz", "Klimaschutz"], ["Klimaschutz"]),
        (UNSET, ["Klimaschutz", "Verkehr"], ["Klimaschutz", "Verkehr"]),
        (UNSET, ["Klimaschutz", "Verkehr", "Klimaschutz"], ["Klimaschutz", "Verkehr"]),
    ],
)
def test__merge_schlagworte__return_deduplicated_vorgang_schlagworte_if_doc_unset(doc_schlagworte: list, vorgang_schlagworte: list, expected: list) -> None:
    """Test if Dokument Schlagworte are not given, remove deduplicated Vorgang Schlagworte."""
    result = _merge_schlagworte(document_schlagworte=doc_schlagworte, vorgang_schlagworte=vorgang_schlagworte)
    assert result == expected


@pytest.mark.parametrize(
    ("doc_schlagworte", "vorgang_schlagworte", "expected"),
    [
        (["Klimaschutz"], ["Klimaschutz"], ["Klimaschutz"]),
        (["Klimaschutz"], ["Klimaschutz", "Verkehr"], ["Klimaschutz", "Verkehr"]),
        (["CO2"], ["Klimaschutz", "Verkehr"], ["CO2", "Klimaschutz", "Verkehr"]),
        (["CO2"], ["Verkehr", "Klimaschutz"], ["CO2", "Verkehr", "Klimaschutz"]),
        (["CO2", "Verkehr"], ["Klimaschutz", "Verkehr"], ["CO2", "Verkehr", "Klimaschutz"]),
        (["CO2", "Verkehr"], ["Verkehr", "Klimaschutz"], ["CO2", "Verkehr", "Klimaschutz"]),
    ],
)
def test__merge_schlagworte__return_deduplicated_and_merged(doc_schlagworte: list, vorgang_schlagworte: list, expected: list) -> None:
    """Test if both schlagworte, merge, deduplicate and keep order."""
    result = _merge_schlagworte(document_schlagworte=doc_schlagworte, vorgang_schlagworte=vorgang_schlagworte)
    assert result == expected
