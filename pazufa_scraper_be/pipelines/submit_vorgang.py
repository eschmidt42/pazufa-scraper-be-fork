import json
import logging
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any, Self

from anyio import Path
from pazufa_corelib.api_client import AuthenticatedClient
from pazufa_corelib.api_client.api.vorgang import vorgang_put
from pazufa_corelib.api_client.models.vorgang import Vorgang
from pazufa_corelib.api_client.types import Response
from scrapy.exceptions import DropItem

from pazufa_scraper_be.constants import SUBMISSION_ERROR_GRACE_PERIOD_DAYS
from pazufa_scraper_be.pipelines.common import StatsPipeline
from pazufa_scraper_be.pipelines.stats_counter import VorgangCounter

logger = logging.getLogger(__name__)


def vorgang_guard(vorgang: Vorgang) -> None:
    """Guards against unexpected `vorgang` type passed at runtime."""
    if not isinstance(vorgang, Vorgang):
        msg = f"Expected {Vorgang.__name__} object but got {vorgang.__class__.__name__}."
        raise DropItem(msg)


class SubmitVorgang(StatsPipeline):
    """Pipeline that submits a built Vorgang to the PaZuFa API."""

    _api_url: Any
    _api_token: Any
    _scraper_uuid: Any

    def init(self: Self) -> None:
        """Load and validate API credentials and settings."""
        super().init()

        self._api_url = self.crawler.settings.get("API_URL", None)
        self._api_token = self.crawler.settings.get("API_TOKEN", None)
        self._scraper_uuid = self.crawler.settings.get("SCRAPER_UUID", None)

        if self._scraper_uuid is None:
            msg = "Missing SCRAPER_UUID setting."
            raise ValueError(msg)

        if self._api_token is not None:
            if self._api_url is None:
                msg = "If API_TOKEN is set, API_URL setting is required."
                raise ValueError(msg)

        else:
            msg = "API_TOKEN is not set. Will not submit to backend."
            logger.info(msg)

    def get_client(self: Self) -> AuthenticatedClient | None:
        """Return an authenticated backend client when configured."""
        if self._api_token is not None:
            return AuthenticatedClient(base_url=self._api_url, token=self._api_token, prefix="", auth_header_name="X-API-Key")

        return None

    async def process_item(self: Self, vorgang: Vorgang) -> None:
        """Submit the Vorgang to the PaZuFa API via HTTP PUT."""
        vorgang_guard(vorgang)

        client = self.get_client()

        if client is None:
            return

        async with client:
            self.increment_stats(VorgangCounter.SUBMIT_ATTEMPT)

            response = await vorgang_put.asyncio_detailed(client=client, body=vorgang, x_scraper_id=str(self._scraper_uuid))

        self._handle_success(response)
        await self._handle_failure(response, vorgang)

    def _handle_success(self, response: Response[Any | str]) -> None:
        if response.status_code == HTTPStatus.CREATED:
            self.increment_stats(VorgangCounter.SUBMIT_ACCEPTED)

    async def _handle_failure(self, response: Response[Any | str], vorgang: Vorgang) -> None:

        id_ = vorgang.ids[0].id if vorgang.ids else vorgang.api_id
        url_part = f"URL: {vorgang.links[0]} " if vorgang.links else ""

        msg = f"[{id_}]: Got {response.status_code} status code when submitting to PaZuFa API. {url_part}Response: {response.content.decode('utf-8')}"

        last_update = vorgang.stationen[-1].zp_start.date()
        days_since_last_update = (datetime.now(UTC).date() - last_update).days
        if days_since_last_update < SUBMISSION_ERROR_GRACE_PERIOD_DAYS:
            self.increment_stats(VorgangCounter.SUBMIT_ERROR)
            logger.info(msg)

        else:
            self.increment_stats(VorgangCounter.submit_rejected_code(response.status_code))
            logger.warning(msg)

            # NOTE: For convenience, we save the failed submissions as JSON files into a temp dir.
            # We were asked multiple times to supply these to the backend devs, so we make this code persistent now
            temp_error_directory = self.crawler.stats.get_value("temp_error_directory")
            error_dir = Path(temp_error_directory) / f"{response.status_code}"
            await error_dir.mkdir(parents=True, exist_ok=True)

            error_file = error_dir / f"{id_}.json"
            await error_file.write_text(json.dumps(vorgang.to_dict(), indent=2))
