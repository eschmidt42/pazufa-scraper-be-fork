import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Self

from pydantic import HttpUrl
from scrapy.crawler import Crawler
from scrapy.statscollectors import StatsCollector, StatsT

from pazufa_scraper_be.cache import Cache
from pazufa_scraper_be.constants import DOK_BASE_URL, DOK_CACHE_SUB_DIR_PATH
from pazufa_scraper_be.pardok import AnyGesetzDokument
from pazufa_scraper_be.pipelines.stats_counter import StatsCounter

logger = logging.getLogger(__name__)


class StatsReporter:
    """Provide convenience methods for reading and updating Scrapy stats."""

    _stats: StatsCollector

    def __init__(self, stats: StatsCollector) -> None:
        """Initialize the reporter with a Scrapy stats collector."""
        self._stats = stats

    def increment(self, counter: StatsCounter | str) -> None:
        """Increment a named counter."""
        key = counter.value if isinstance(counter, StatsCounter) else counter
        self._stats.inc_value(key)

    def get_value(
        self,
        key: str,
        default: int | None = None,
    ) -> object:
        """Return the value of the *key* stat, or *default* if it is not set."""
        return self._stats.get_value(key, default)

    def get_stats(self) -> StatsT:
        """Return all stats as a dict."""
        return self._stats.get_stats()


def get_wahlperiode(crawler: Crawler) -> int:
    """Get Wahlperiode ^^."""
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
        self.wahlperiode = get_wahlperiode(crawler)

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


def get_cache_dir(crawler: Crawler) -> Path:
    """Return the configured cache directory for a crawler."""
    cache_dir = crawler.settings.get("CACHE_DIR")

    if not isinstance(cache_dir, (str, Path)):
        msg = "Missing CACHE_DIR setting."
        raise TypeError(msg)

    return Path(cache_dir)


class DocumentCacheFactory:
    """Create document caches rooted in the cache directory for one election period."""

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "DocumentCacheFactory":
        """Create a factory using the cache directory and election period from the crawler."""
        cache_dir = get_cache_dir(crawler)

        wahlperiode = get_wahlperiode(crawler)

        return cls(cache_dir=cache_dir, wahlperiode=wahlperiode)

    def __init__(self, *, cache_dir: Path, wahlperiode: int) -> None:
        """Initialize the factory for the given cache directory and election period."""
        self._wahlperiode = wahlperiode
        self._dok_cache_dir = cache_dir / str(wahlperiode) / DOK_CACHE_SUB_DIR_PATH

    def for_document(self, document: AnyGesetzDokument, url: HttpUrl) -> Cache:
        """Return a cache for a document URL."""
        if url != document.lok_url and document.additional_urls and url not in document.additional_urls:
            msg = f"[{document.vorgang.id} - {document.id}]: Did not setup dokument cache because given URL is unknown: {url}"
            raise ValueError(msg)

        relative_path = Path(str(url).removeprefix(f"{DOK_BASE_URL}/{self._wahlperiode}/")).with_suffix("")
        cache_name = Path(document.art).joinpath(*relative_path.parts[1:])

        return Cache(base_dir=self._dok_cache_dir, name=str(cache_name))
