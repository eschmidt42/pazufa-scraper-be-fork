from typing import Any
from unittest.mock import MagicMock

import pytest
from scrapy import Spider
from scrapy.crawler import Crawler
from scrapy.exceptions import DropItem
from scrapy.settings import Settings

from pazufa_scraper_be.pardok import GesetzVorgang
from pazufa_scraper_be.pipeline_guards import engine_guard, vorgang_guard


def test_vorgang_guard_accepts_gesetz_vorgang(base_vorgang_data: dict[str, Any]) -> None:
    """A GesetzVorgang passes the guard."""
    vorgang = GesetzVorgang.model_validate(base_vorgang_data)

    assert vorgang_guard(vorgang) is None


def test_vorgang_guard_rejects_unexpected_type() -> None:
    """An unexpected item type is dropped with its type in the message."""
    vorgang: Any = "unexpected"

    with pytest.raises(DropItem) as exc_info:
        vorgang_guard(vorgang)

    assert str(exc_info.value) == "Expected GesetzVorgang object but got str."


def test_engine_guard_accepts_initialized_crawler() -> None:
    """A crawler with an engine passes the guard."""
    crawler = Crawler(Spider, Settings())
    crawler.engine = MagicMock()

    assert engine_guard(crawler) is None


def test_engine_guard_rejects_crawler_without_engine() -> None:
    """A crawler without an engine raises a clear error."""
    crawler: Any = MagicMock(engine=None)

    with pytest.raises(ValueError, match=r"^crawler\.engine is None\. The crawler seems improperly initialized\.$"):
        engine_guard(crawler)
