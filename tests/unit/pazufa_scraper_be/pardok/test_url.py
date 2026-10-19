import asyncio
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import HttpUrl
from scrapy import Request

from pazufa_scraper_be.pardok.dokument import APrDokument, ProtokollTyp
from pazufa_scraper_be.pardok.url import (
    build_ausschussprotokoll_variant_url,
    build_plenarprotokoll_url,
    resolve_document_urls,
    url_is_reachable,
)

_DOK_BASE = "https://pardok.parlament-berlin.de/starweb/adis/citat/VT"


@dataclass
class _FakeResponse:
    """Minimal Scrapy response stand-in exposing only the ``status`` attribute."""

    status: int


@dataclass
class _FakeEngine:
    """Async stand-in for ``ExecutionEngine`` mapping request URLs to canned outcomes."""

    responses: dict[str, int | Exception]
    requested: list[Request] = field(default_factory=list)

    async def download_async(self, request: Request) -> _FakeResponse:
        """Return a canned response or raise the configured exception for the URL."""
        self.requested.append(request)
        outcome = self.responses[request.url]
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeResponse(status=outcome)


def _make_apr(apr_data: dict[str, Any], lok_url: str, additional_urls: list[str] | None = None) -> APrDokument:
    """Build an ``APrDokument`` with an overridden LokURL and optional additional URLs."""
    data = apr_data.copy()
    data["LokURL"] = lok_url
    if additional_urls is not None:
        data["additional_urls"] = additional_urls
    return APrDokument.model_validate(data)


# build_plenarprotokoll_url -----------------------------------------------------


@pytest.mark.parametrize(
    ("wahlperiode", "dokument_nr", "expected"),
    [
        (19, "19/2", f"{_DOK_BASE}/19/PlenarPr/p19-002-wp.pdf"),
        (18, "18/10", f"{_DOK_BASE}/18/PlenarPr/p18-010-wp.pdf"),
        (19, "19/42", f"{_DOK_BASE}/19/PlenarPr/p19-042-wp.pdf"),
    ],
)
def test_build_plenarprotokoll_url_success(wahlperiode: int, dokument_nr: str, expected: str) -> None:
    """build_plenarprotokoll_url zero-pads the running number and uses the bp suffix."""
    result = build_plenarprotokoll_url(wahlperiode, dokument_nr)
    assert isinstance(result, HttpUrl)
    assert str(result) == expected


@pytest.mark.parametrize("dokument_nr", ["19", "19/abc", "19/", "", "abc/def"])
def test_build_plenarprotokoll_url_invalid_returns_none(dokument_nr: str) -> None:
    """build_plenarprotokoll_url returns None when DokNr lacks a numeric second segment."""
    assert build_plenarprotokoll_url(19, dokument_nr) is None


# build_ausschussprotokoll_variant_url -----------------------------------------


@pytest.mark.parametrize(
    ("url", "typ", "expected"),
    [
        (
            f"{_DOK_BASE}/19/AusschussPr/as/as19-020-wp.pdf",
            ProtokollTyp.Beschluss,
            f"{_DOK_BASE}/19/AusschussPr/as/as19-020-bp.pdf",
        ),
        (
            f"{_DOK_BASE}/19/AusschussPr/ParlKBB/ParlKBB19-001-bp.pdf",
            ProtokollTyp.Wort,
            f"{_DOK_BASE}/19/AusschussPr/ParlKBB/ParlKBB19-001-wp.pdf",
        ),
        (
            f"{_DOK_BASE}/19/AusschussPr/h/h19-003-wp.pdf",
            ProtokollTyp.Inhalt,
            f"{_DOK_BASE}/19/AusschussPr/h/h19-003-ip.pdf",
        ),
    ],
)
def test_build_ausschussprotokoll_variant_url(url: str, typ: ProtokollTyp, expected: str) -> None:
    """build_ausschussprotokoll_variant_url swaps only the trailing typ segment."""
    result = build_ausschussprotokoll_variant_url(HttpUrl(url), typ)
    assert str(result) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/abc.pdf",  # no '-' before the extension
        "https://example.com/foo",  # no extension at all
        "https://example.com/foo.txt",  # non-pdf extension
    ],
)
def test_build_ausschussprotokoll_variant_url_rejects_malformed(url: str) -> None:
    """build_ausschussprotokoll_variant_url raises ValueError for URLs it cannot split."""
    with pytest.raises(ValueError, match="Cannot derive APr variant"):
        build_ausschussprotokoll_variant_url(HttpUrl(url), ProtokollTyp.Beschluss)


def test_build_ausschussprotokoll_variant_url_rejects_url_with_none_path() -> None:
    """build_ausschussprotokoll_variant_url raises ValueError when url.path is None."""
    mock_url = MagicMock(spec=HttpUrl)
    mock_url.path = None

    with pytest.raises(ValueError, match="should contain the path to a file but lacks any path"):
        build_ausschussprotokoll_variant_url(mock_url, ProtokollTyp.Beschluss)


# Protokoll order ---------------------------------------------------------------


def test_apr_variant_order() -> None:
    """apr_variant_order declares Beschluss as primary, followed by Inhalt and Wort."""
    expected_list = [ProtokollTyp.Beschluss, ProtokollTyp.Inhalt, ProtokollTyp.Wort]
    for expected, protkoll_typ in zip(expected_list, ProtokollTyp, strict=True):
        assert expected == protkoll_typ


# url_is_reachable --------------------------------------------------------------


def test_url_is_reachable_ok() -> None:
    """url_is_reachable returns True for HTTP 200 and issues a HEAD request."""
    url = "https://example.com/x.pdf"
    engine = _FakeEngine(responses={url: HTTPStatus.OK})
    result = asyncio.run(url_is_reachable(engine, HttpUrl(url)))  # ty: ignore[invalid-argument-type]
    assert result is True
    assert engine.requested[0].method == "HEAD"
    assert engine.requested[0].url == url


def test_url_is_reachable_non_ok() -> None:
    """url_is_reachable returns False for non-200 statuses."""
    url = "https://example.com/x.pdf"
    engine = _FakeEngine(responses={url: HTTPStatus.NOT_FOUND})
    result = asyncio.run(url_is_reachable(engine, HttpUrl(url)))  # ty: ignore[invalid-argument-type]
    assert result is False


def test_url_is_reachable_swallows_exceptions() -> None:
    """url_is_reachable returns False when the download raises."""
    url = "https://example.com/x.pdf"
    engine = _FakeEngine(responses={url: ConnectionError("boom")})
    result = asyncio.run(url_is_reachable(engine, HttpUrl(url)))  # ty: ignore[invalid-argument-type]
    assert result is False


# resolve_dokument_urls ---------------------------------------------------------


def test_resolve_keeps_all_when_primary_and_additionals_reachable(apr_data: dict[str, Any]) -> None:
    """The primary stays unchanged and all reachable additional URLs are returned."""
    primary = "https://example.com/primary.pdf"
    additional = ["https://example.com/a.pdf", "https://example.com/b.pdf"]
    dokument = _make_apr(apr_data, primary, additional)
    engine = _FakeEngine(responses={primary: HTTPStatus.OK, additional[0]: HTTPStatus.OK, additional[1]: HTTPStatus.OK})
    resolved_additional_urls, res = asyncio.run(resolve_document_urls(dokument, engine))  # ty: ignore[invalid-argument-type]

    assert res.primary_was_reachable is True
    assert res.recovered_from is None
    assert res.pruned == []
    assert res.missing_primary is False
    assert str(dokument.lok_url) == primary
    assert [str(u) for u in (resolved_additional_urls or [])] == additional


def test_resolve_prunes_unreachable_additionals(apr_data: dict[str, Any]) -> None:
    """Unreachable additional URLs are pruned; the reachable ones are retained."""
    primary = "https://example.com/primary.pdf"
    additional = ["https://example.com/a.pdf", "https://example.com/b.pdf"]
    dokument = _make_apr(apr_data, primary, additional)
    engine = _FakeEngine(responses={primary: HTTPStatus.OK, additional[0]: HTTPStatus.NOT_FOUND, additional[1]: HTTPStatus.OK})
    resolved_additional_urls, res = asyncio.run(resolve_document_urls(dokument, engine))  # ty: ignore[invalid-argument-type]

    assert res.primary_was_reachable is True
    assert res.recovered_from is None
    assert res.missing_primary is False
    assert [str(u) for u in res.pruned] == [additional[0]]
    assert [str(u) for u in (resolved_additional_urls or [])] == [additional[1]]


def test_resolve_recovers_primary_from_first_reachable_additional(apr_data: dict[str, Any]) -> None:
    """A broken primary is replaced by the first reachable additional URL."""
    primary = "https://example.com/primary.pdf"
    additional = ["https://example.com/a.pdf", "https://example.com/b.pdf"]
    dokument = _make_apr(apr_data, primary, additional)
    engine = _FakeEngine(responses={primary: HTTPStatus.NOT_FOUND, additional[0]: HTTPStatus.OK, additional[1]: HTTPStatus.OK})
    resolved_additional_urls, res = asyncio.run(resolve_document_urls(dokument, engine))  # ty: ignore[invalid-argument-type]

    assert res.primary_was_reachable is False
    assert str(res.recovered_from) == additional[0]
    assert res.missing_primary is False
    assert res.pruned == []
    assert str(dokument.lok_url) == additional[0]
    assert [str(u) for u in (resolved_additional_urls or [])] == [additional[1]]


def test_resolve_marks_missing_primary_without_additionals(apr_data: dict[str, Any]) -> None:
    """A broken primary with no additionals is reported as missing."""
    primary = "https://example.com/primary.pdf"
    dokument = _make_apr(apr_data, primary)
    engine = _FakeEngine(responses={primary: HTTPStatus.NOT_FOUND})
    resolved_additional_urls, res = asyncio.run(resolve_document_urls(dokument, engine))  # ty: ignore[invalid-argument-type]

    assert res.primary_was_reachable is False
    assert res.recovered_from is None
    assert res.pruned == []
    assert res.missing_primary is True
    assert resolved_additional_urls is None


def test_resolve_marks_missing_primary_when_all_additionals_unreachable(apr_data: dict[str, Any]) -> None:
    """A broken primary with only unreachable additionals is reported as missing."""
    primary = "https://example.com/primary.pdf"
    additional = ["https://example.com/a.pdf", "https://example.com/b.pdf"]
    dokument = _make_apr(apr_data, primary, additional)
    engine = _FakeEngine(responses={primary: HTTPStatus.NOT_FOUND, additional[0]: HTTPStatus.INTERNAL_SERVER_ERROR, additional[1]: HTTPStatus.NOT_FOUND})
    resolved_additional_urls, res = asyncio.run(resolve_document_urls(dokument, engine))  # ty: ignore[invalid-argument-type]

    assert res.primary_was_reachable is False
    assert res.recovered_from is None
    assert res.missing_primary is True
    assert [str(u) for u in res.pruned] == additional
    assert resolved_additional_urls is None
