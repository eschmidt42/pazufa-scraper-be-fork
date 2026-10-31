import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Self

import litellm
from pazufa_corelib.api_client import AuthenticatedClient
from pazufa_corelib.llm import LLMConnector
from pydantic import HttpUrl
from scrapy.crawler import Crawler
from scrapy.statscollectors import StatsCollector

from pazufa_scraper_be.cache import Cache
from pazufa_scraper_be.constants import DOK_BASE_URL, DOK_CACHE_SUB_DIR_PATH
from pazufa_scraper_be.pardok import AnyGesetzDokument
from pazufa_scraper_be.pipelines.stats_counter import StatsCounter

logger = logging.getLogger(__name__)


def _get_wahlperiode(crawler: Crawler) -> int:
    wahlperiode = crawler.settings.getint("WAHLPERIODE")

    if wahlperiode is None:
        msg = "Missing WAHLPERIODE setting."
        raise ValueError(msg)

    return wahlperiode


class BasePipeline(ABC):
    """Provide shared crawler initialization for pipeline implementations."""

    crawler: Crawler
    wahlperiode: int

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> Self:
        """Create a pipeline instance from a Scrapy crawler."""
        return cls(crawler=crawler)

    def __init__(self: Self, crawler: Crawler) -> None:
        """Store the crawler and initialize pipeline-specific state."""
        self.crawler = crawler
        self.wahlperiode = _get_wahlperiode(crawler)

        self.init()

    @abstractmethod
    def init(self: Self) -> None:
        """Initialize state specific to the concrete pipeline."""
        ...


class StatsPipeline(BasePipeline):
    """Adds convenience method to log PaZuFa stats.

    Reference: https://docs.scrapy.org/en/latest/topics/stats.html
    """

    stats: StatsCollector

    def init(self: Self) -> None:
        """Expose the crawler's stats collector."""
        super().init()

        self.stats = self.crawler.stats

    def increment_stats(self: Self, counter: StatsCounter | str) -> None:
        """Increment a named stats counter."""
        key = counter.value if isinstance(counter, StatsCounter) else counter
        self.stats.inc_value(key)


class CachePipeline(BasePipeline):
    """Provide helpers for caching document downloads."""

    _cache_dir: Path
    _dok_cache_dir: Path

    def init(self: Self) -> None:
        """Resolve cache directories from crawler settings."""
        super().init()

        cache_dir = self.crawler.settings.get("CACHE_DIR")

        if not isinstance(cache_dir, (str, Path)):
            msg = "Missing CACHE_DIR setting."
            raise TypeError(msg)

        self._cache_dir = Path(cache_dir) / str(self.wahlperiode)
        self._dok_cache_dir = self._cache_dir / DOK_CACHE_SUB_DIR_PATH

    def get_cache(self: Self, document: AnyGesetzDokument, document_url: HttpUrl) -> Cache:
        """Build a cache for a URL associated with a document."""
        if document_url != document.lok_url and document.additional_urls and document_url not in document.additional_urls:
            msg = f"[{document.vorgang.id} - {document.id}]: Did not setup dokument cache because given URL is unknown: {document_url}"
            raise ValueError(msg)

        cache_name = Path(document.art).joinpath(*Path(str(document_url).removeprefix(f"{DOK_BASE_URL}/{self.wahlperiode}/")).with_suffix("").parts[1:])
        return Cache(base_dir=self._dok_cache_dir, name=str(cache_name))


class ApiPipeline(BasePipeline):
    """Configure API submission from crawler settings."""

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


class LLMPipeline(BasePipeline):
    """Configure document summarization from crawler settings."""

    _llm_token: Any
    llm_model_name: Any
    llm_connector: LLMConnector | None

    def init(self: Self) -> None:
        """Load and validate LLM settings and initialize the connector."""
        super().init()

        self._llm_token = self.crawler.settings.get("LLM_TOKEN", None)
        self.llm_model_name = self.crawler.settings.get("LLM_MODEL", None)
        self.llm_connector = None

        if self._llm_token is not None:
            if self.llm_model_name is None:
                msg = "If LLM_TOKEN is set, LLM_MODEL setting is required."
                raise ValueError(msg)

            logging.getLogger("LiteLLM").setLevel(logging.FATAL)
            litellm.suppress_debug_info = True

            logging.getLogger("pazufa_corelib.llm.llm_connector").setLevel(logging.FATAL)

            llm_timeout = self.crawler.settings.getint("LLM_TIMEOUT")
            if not isinstance(llm_timeout, int) or llm_timeout <= 0:
                msg = "Invalid LLM_TIMEOUT setting, must but integer greater than 0."
                raise ValueError(msg)

            self.llm_connector = LLMConnector(model=self.llm_model_name, api_key=self._llm_token, timeout_seconds=llm_timeout)

        else:
            msg = "LLM_TOKEN is not set. Skipping Document summarization."
            logger.info(msg)
