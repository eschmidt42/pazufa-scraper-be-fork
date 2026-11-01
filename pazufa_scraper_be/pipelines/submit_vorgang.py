import json
import logging
import os
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any, Self
from uuid import UUID

from anyio import Path
from pazufa_corelib.api_client import AuthenticatedClient
from pazufa_corelib.api_client.api.vorgang import vorgang_put
from pazufa_corelib.api_client.models.vorgang import Vorgang
from pazufa_corelib.api_client.types import Response
from scrapy.crawler import Crawler
from scrapy.exceptions import DropItem

from pazufa_scraper_be.constants import SUBMISSION_ERROR_GRACE_PERIOD_DAYS
from pazufa_scraper_be.pipelines.common import StatsReporter
from pazufa_scraper_be.pipelines.stats_counter import VorgangCounter

logger = logging.getLogger(__name__)


def vorgang_guard(vorgang: Vorgang) -> None:
    """Guards against unexpected `vorgang` type passed at runtime."""
    if not isinstance(vorgang, Vorgang):
        msg = f"Expected {Vorgang.__name__} object but got {vorgang.__class__.__name__}."
        raise DropItem(msg)


def get_client(*, token: str | None, url: str) -> AuthenticatedClient | None:
    """Return an authenticated backend client when configured privded api token and url."""
    if token is not None:
        return AuthenticatedClient(base_url=url, token=token, prefix="", auth_header_name="X-API-Key")

    return None


class SubmitVorgang2:
    """Pipeline that submits a built Vorgang to the PaZuFa API."""

    _api_url: str
    _api_token: str | None
    _scraper_uuid: UUID | str
    _stats: StatsReporter

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "SubmitVorgang2":
        """Create the pipeline with dependencies initialized from the crawler."""
        scraper_uuid = crawler.settings.get("SCRAPER_UUID", None)
        api_url = crawler.settings.get("API_URL", None)
        api_token = crawler.settings.get("API_TOKEN", None)

        if scraper_uuid is None:
            msg = "Missing SCRAPER_UUID setting."
            raise ValueError(msg)

        if api_token is not None:
            if api_url is None:
                msg = "If API_TOKEN is set, API_URL setting is required."
                raise ValueError(msg)

        else:
            msg = "API_TOKEN is not set. Will not submit to backend."
            logger.info(msg)

        return cls(
            api_url=api_url,
            api_token=api_token,
            scraper_uuid=scraper_uuid,
            stats=StatsReporter(crawler.stats),
        )

    def __init__(self, api_url: str, api_token: str | None, scraper_uuid: UUID | str, stats: StatsReporter) -> None:
        """Load and validate API credentials and settings."""
        self._stats = stats
        self._api_url = api_url
        self._api_token = api_token
        self._scraper_uuid = scraper_uuid

    async def process_item(self: Self, vorgang: Vorgang) -> None:
        """Submit the Vorgang to the PaZuFa API via HTTP PUT."""
        vorgang_guard(vorgang)

        client = get_client(token=self._api_token, url=self._api_url)

        if client is None:
            return

        async with client:
            self._stats.increment(VorgangCounter.SUBMIT_ATTEMPT)

            response = await vorgang_put.asyncio_detailed(client=client, body=vorgang, x_scraper_id=str(self._scraper_uuid))

        self._handle_success(response)
        await self._handle_failure(response, vorgang)

    def _handle_success(self, response: Response[Any | str]) -> None:
        if response.status_code == HTTPStatus.CREATED:
            self._stats.increment(VorgangCounter.SUBMIT_ACCEPTED)

    async def _handle_failure(self, response: Response[Any | str], vorgang: Vorgang) -> None:

        id_ = vorgang.ids[0].id if vorgang.ids else vorgang.api_id
        url_part = f"URL: {vorgang.links[0]} " if vorgang.links else ""

        msg = f"[{id_}]: Got {response.status_code} status code when submitting to PaZuFa API. {url_part}Response: {response.content.decode('utf-8')}"

        last_update = vorgang.stationen[-1].zp_start.date()
        days_since_last_update = (datetime.now(UTC).date() - last_update).days
        if days_since_last_update < SUBMISSION_ERROR_GRACE_PERIOD_DAYS:
            self._stats.increment(VorgangCounter.SUBMIT_ERROR)
            logger.info(msg)

        else:
            self._stats.increment(VorgangCounter.submit_rejected_code(response.status_code))
            logger.warning(msg)

            # NOTE: For convenience, we save the failed submissions as JSON files into a temp dir.
            # We were asked multiple times to supply these to the backend devs, so we make this code persistent now
            temp_error_directory = self._stats.get_value("temp_error_directory")
            if not isinstance(temp_error_directory, (str, os.PathLike)):
                msg = "Expected 'temp_error_directory' to be a path"
                raise TypeError(msg)
            error_dir = Path(temp_error_directory) / f"{response.status_code}"
            await error_dir.mkdir(parents=True, exist_ok=True)

            error_file = error_dir / f"{id_}.json"
            await error_file.write_text(json.dumps(vorgang.to_dict(), indent=2))
