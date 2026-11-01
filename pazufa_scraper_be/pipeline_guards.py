import logging
from uuid import UUID

from pazufa_corelib.api_client.models.vorgang import Vorgang
from scrapy.core.engine import ExecutionEngine
from scrapy.crawler import Crawler
from scrapy.exceptions import DropItem

from pazufa_scraper_be.pardok import GesetzVorgang

logger = logging.getLogger(__name__)


def gesetzvorgang_guard(vorgang: GesetzVorgang) -> None:
    """Guards against unexpected `vorgang` type passed at runtime."""
    if not isinstance(vorgang, GesetzVorgang):
        msg = f"Expected {GesetzVorgang.__name__} object but got {vorgang.__class__.__name__}."
        raise DropItem(msg)


def engine_guard(crawler: Crawler) -> None:
    """Guards against missing crawler engine."""
    if crawler.engine is None:
        msg = "crawler.engine is None. The crawler seems improperly initialized."
        raise ValueError(msg)


def engine_guard2(engine: ExecutionEngine) -> None:
    """Guards against missing crawler engine."""
    if engine is None:
        msg = "crawler.engine is None. The crawler seems improperly initialized."
        raise ValueError(msg)


def api_config_guard(api_url: str | None, api_token: str | None) -> None:
    """Guards against improper api config."""
    if api_token is not None and api_url is None:
        msg = "If API_TOKEN is set, API_URL setting is required."
        raise ValueError(msg)

    msg = "API_TOKEN is not set. Will not submit to backend."
    logger.info(msg)


def uuid_guard(scraper_uuid: UUID | None) -> None:
    """Guards against missing uui value."""
    if scraper_uuid is None:
        msg = "Missing SCRAPER_UUID setting."
        raise ValueError(msg)


def vorgang_guard(vorgang: Vorgang) -> None:
    """Guards against unexpected `vorgang` type passed at runtime."""
    if not isinstance(vorgang, Vorgang):
        msg = f"Expected {Vorgang.__name__} object but got {vorgang.__class__.__name__}."
        raise DropItem(msg)
