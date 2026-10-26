import asyncio
import json
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pazufa_corelib.api_client.models import (
    Gremium,
    Parlament,
    Station,
    Stationstyp,
    VgIdent,
    Vorgang,
    Vorgangstyp,
)
from scrapy import Spider
from scrapy.crawler import Crawler
from scrapy.exceptions import DropItem
from scrapy.settings import Settings
from scrapy.statscollectors import StatsCollector

from pazufa_scraper_be.constants import SUBMISSION_ERROR_GRACE_PERIOD_DAYS
from pazufa_scraper_be.pipelines.stats_counter import VorgangCounter
from pazufa_scraper_be.pipelines.submit_vorgang import SubmitVorgang


@pytest.fixture
def submit_vorgang() -> Vorgang:
    """Create a minimal API Vorgang with an identifier and station timestamp."""
    return Vorgang(
        api_id=uuid4(),
        initiatoren=[],
        stationen=[
            Station(
                dokumente=[],
                gremium=Gremium(name="Test", parlament=Parlament.BE, wahlperiode=19),
                typ=Stationstyp.SONSTIG,
                zp_start=datetime.now(UTC) - timedelta(days=SUBMISSION_ERROR_GRACE_PERIOD_DAYS),
            )
        ],
        titel="Test Vorgang",
        typ=Vorgangstyp.GG_LAND_PARL,
        verfassungsaendernd=False,
        wahlperiode=19,
        ids=[VgIdent(id="vorg123", typ="PARDOK")],
        links=["https://example.com/vorg123"],
    )


@pytest.fixture
def submit_pipeline(tmp_path: Path) -> SubmitVorgang:
    """Create a SubmitVorgang pipeline configured for API submission."""
    crawler = Crawler(
        Spider,
        Settings(
            {
                "WAHLPERIODE": 19,
                "API_URL": "https://api.example.com",
                "API_TOKEN": "test-token",
                "SCRAPER_UUID": "12345678-1234-5678-1234-567812345678",
            }
        ),
    )
    crawler.stats = StatsCollector(crawler)
    crawler.stats.set_value("temp_error_directory", str(tmp_path))
    return SubmitVorgang(crawler)


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def test_submit_vorgang_rejects_unexpected_item(submit_pipeline: SubmitVorgang) -> None:
    """Items that are not API Vorgang objects are dropped."""
    with pytest.raises(DropItem, match="Expected Vorgang object but got object"):
        asyncio.run(submit_pipeline.process_item(object()))  # ty: ignore[invalid-argument-type]


def test_submit_vorgang_skips_when_api_token_is_missing(submit_vorgang: Vorgang) -> None:
    """Submission without an API token is skipped without changing stats."""
    crawler = Crawler(Spider, Settings({"WAHLPERIODE": 19, "SCRAPER_UUID": "12345678-1234-5678-1234-567812345678"}))
    crawler.stats = StatsCollector(crawler)
    pipeline = SubmitVorgang(crawler)

    asyncio.run(pipeline.process_item(submit_vorgang))

    assert pipeline.stats.get_stats() == {}


def test_submit_vorgang_counts_created_response(
    submit_vorgang: Vorgang,
    submit_pipeline: SubmitVorgang,
) -> None:
    """A 201 response is counted as an accepted submission."""
    client = _mock_client()
    with (
        patch.object(submit_pipeline, "get_client", return_value=client),
        patch(
            "pazufa_scraper_be.pipelines.submit_vorgang.vorgang_put.asyncio_detailed",
            new_callable=AsyncMock,
            return_value=MagicMock(status_code=HTTPStatus.CREATED),
        ) as submit,
    ):
        asyncio.run(submit_pipeline.process_item(submit_vorgang))

    submit.assert_awaited_once_with(
        client=client,
        body=submit_vorgang,
        x_scraper_id="12345678-1234-5678-1234-567812345678",
    )
    assert submit_pipeline.stats.get_value(VorgangCounter.SUBMIT_ATTEMPT.value) == 1
    assert submit_pipeline.stats.get_value(VorgangCounter.SUBMIT_ACCEPTED.value) == 1


def test_submit_vorgang_counts_recent_api_error_as_grace_period_error(
    submit_vorgang: Vorgang,
    submit_pipeline: SubmitVorgang,
) -> None:
    """A failed submission within the grace period is logged as an error, not rejected."""
    submit_vorgang.stationen[-1].zp_start = datetime.now(UTC) - timedelta(days=SUBMISSION_ERROR_GRACE_PERIOD_DAYS - 1)
    client = _mock_client()
    response = MagicMock(status_code=HTTPStatus.BAD_REQUEST, content=b"temporary error")

    with (
        patch.object(submit_pipeline, "get_client", return_value=client),
        patch(
            "pazufa_scraper_be.pipelines.submit_vorgang.vorgang_put.asyncio_detailed",
            new_callable=AsyncMock,
            return_value=response,
        ),
    ):
        asyncio.run(submit_pipeline.process_item(submit_vorgang))

    assert submit_pipeline.stats.get_value(VorgangCounter.SUBMIT_ATTEMPT.value) == 1
    assert submit_pipeline.stats.get_value(VorgangCounter.SUBMIT_ERROR.value) == 1
    assert submit_pipeline.stats.get_value(VorgangCounter.submit_rejected_code(HTTPStatus.BAD_REQUEST)) is None


def test_submit_vorgang_saves_old_rejection(
    submit_vorgang: Vorgang,
    submit_pipeline: SubmitVorgang,
    tmp_path: Path,
) -> None:
    """A failed submission older than the grace period is counted and persisted as JSON."""
    client = _mock_client()
    response = MagicMock(status_code=HTTPStatus.BAD_REQUEST, content=b"rejected")

    with (
        patch.object(submit_pipeline, "get_client", return_value=client),
        patch(
            "pazufa_scraper_be.pipelines.submit_vorgang.vorgang_put.asyncio_detailed",
            new_callable=AsyncMock,
            return_value=response,
        ),
    ):
        asyncio.run(submit_pipeline.process_item(submit_vorgang))

    assert submit_pipeline.stats.get_value(VorgangCounter.SUBMIT_ATTEMPT.value) == 1
    assert submit_pipeline.stats.get_value(VorgangCounter.submit_rejected_code(HTTPStatus.BAD_REQUEST)) == 1
    assert submit_pipeline.stats.get_value(VorgangCounter.SUBMIT_ERROR.value) is None
    error_file = tmp_path / str(HTTPStatus.BAD_REQUEST.value) / "vorg123.json"
    assert json.loads(error_file.read_text()) == submit_vorgang.to_dict()
