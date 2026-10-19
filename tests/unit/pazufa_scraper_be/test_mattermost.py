import asyncio
import datetime as dt
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from scrapy import signals
from scrapy.statscollectors import StatsCollector

from pazufa_scraper_be.extensions.mattermost import MattermostNotifier, _build_payload

VALID_BACKENDS = ["http://localhost:8080", "https://staging.api.pazufa.de", "https://api.pazufa.de"]
INVALID_BACKENDS = ["localhost:8080", "staging.api.pazufa.de", "api.pazufa.de", ""]


@pytest.fixture
def make_crawler() -> Callable[..., MagicMock]:
    """Create Mock Crawler."""

    def _make(settings: dict) -> MagicMock:
        crawler = MagicMock()
        crawler.settings.get.side_effect = lambda key, default=None: settings.get(key, default)
        return crawler

    return _make


@pytest.fixture
def valid_crawler(make_crawler: Callable[..., MagicMock]) -> dict[str, str]:
    """Create a valid Mock Crawler."""
    return make_crawler(
        {
            "MATTERMOST_TOKEN": "token123",
            "MATTERMOST_URL": "https://mattermost.example.com",
            "API_URL": "https://api.pazufa.de",
        }
    )


@pytest.fixture
def make_stats() -> Callable[..., Any]:
    """Create Mock Stats."""

    def _make(data: dict) -> MagicMock:
        stats = MagicMock()
        stats.get_stats.return_value = data
        stats.get_value.side_effect = lambda key, default=None: data.get(key, default)
        return stats

    return _make


@pytest.fixture
def empty_stats(make_stats: Callable[..., Any]) -> dict[str, Any]:
    """Create empty Mock Stats."""
    return make_stats({})


@pytest.fixture
def base_stats(make_stats: Callable[..., Any]) -> dict[str, Any]:
    """Create basic PaZuFa Mock Stats."""
    return make_stats(
        {
            "PaZuFa/Vorgang/total": 29,
            "PaZuFa/Dokument/cache/hit": 2907,
            "PaZuFa/Text/cache/hit": 2904,
            "PaZuFa/Text/cache/miss": 3,
            "PaZuFa/Text/extract/failed/empty_text": 3,
            "PaZuFa/Vorgang/drop/incorrect": 1,
            "PaZuFa/Vorgang/drop/no_documents": 1,
            "PaZuFa/Vorgang/drop/no_stations": 19,
        }
    )


@pytest.fixture
def full_stats_w_submit(make_stats: Callable[..., Any]) -> dict[str, Any]:
    """Create submit Mock Stats."""
    return make_stats(
        {
            "PaZuFa/Dokument/cache/hit": 2907,
            "PaZuFa/Text/cache/hit": 2904,
            "PaZuFa/Text/cache/miss": 3,
            "PaZuFa/Text/extract/failed/empty_text": 3,
            "PaZuFa/Vorgang/drop/incorrect": 1,
            "PaZuFa/Vorgang/drop/no_documents": 1,
            "PaZuFa/Vorgang/drop/no_stations": 19,
            "PaZuFa/Vorgang/submit/accepted": 272,
            "PaZuFa/Vorgang/submit/attempt": 309,
            "PaZuFa/Vorgang/submit/rejected/400": 29,
            "PaZuFa/Vorgang/submit/rejected/422": 8,
            "PaZuFa/Vorgang/total": 329,
            "downloader/request_bytes": 1835803,
            "downloader/request_count": 5853,
            "downloader/request_method_count/GET": 1,
            "downloader/request_method_count/HEAD": 5852,
            "downloader/response_bytes": 7762723,
            "downloader/response_count": 5853,
            "downloader/response_status_count/200": 4160,
            "downloader/response_status_count/404": 1693,
            "elapsed_time_seconds": 20.481048499999815,
            "finish_reason": "finished",
            "finish_time": dt.datetime(2026, 6, 4, 6, 1, 32, 591766, tzinfo=dt.UTC),
            "httpcache/hit": 5853,
            "httpcompression/response_bytes": 50733191,
            "httpcompression/response_count": 1,
            "item_dropped_count": 21,
            "item_dropped_reasons_count/DropItem": 21,
            "item_scraped_count": 309,
            "items_per_minute": 927.0,
            "log_count/INFO": 206,
            "log_count/WARNING": 65,
            "memusage/max": 242925568,
            "memusage/startup": 242925568,
            "response_received_count": 5853,
            "responses_per_minute": 17559.0,
            "scheduler/dequeued": 1,
            "scheduler/dequeued/memory": 1,
            "scheduler/enqueued": 1,
            "scheduler/enqueued/memory": 1,
            "start_time": dt.datetime(2026, 6, 4, 6, 1, 12, 110695, tzinfo=dt.UTC),
        }
    )


@pytest.fixture
def full_stats_wo_submit(make_stats: Callable[..., Any]) -> dict[str, Any]:
    """Create without submit Mock Stats."""
    return make_stats(
        {
            "PaZuFa/Dokument/cache/hit": 2907,
            "PaZuFa/Text/cache/hit": 2904,
            "PaZuFa/Text/cache/miss": 3,
            "PaZuFa/Text/extract/failed/empty_text": 3,
            "PaZuFa/Vorgang/drop/incorrect": 1,
            "PaZuFa/Vorgang/drop/no_documents": 1,
            "PaZuFa/Vorgang/drop/no_stations": 19,
            "PaZuFa/Vorgang/total": 329,
            "downloader/request_bytes": 1835803,
            "downloader/request_count": 5853,
            "downloader/request_method_count/GET": 1,
            "downloader/request_method_count/HEAD": 5852,
            "downloader/response_bytes": 7762723,
            "downloader/response_count": 5853,
            "downloader/response_status_count/200": 4160,
            "downloader/response_status_count/404": 1693,
            "elapsed_time_seconds": 9.051556291999987,
            "finish_reason": "finished",
            "finish_time": dt.datetime(2026, 6, 4, 6, 1, 18, 636056, tzinfo=dt.UTC),
            "httpcache/hit": 5853,
            "httpcompression/response_bytes": 50733191,
            "httpcompression/response_count": 1,
            "item_dropped_count": 21,
            "item_dropped_reasons_count/DropItem": 21,
            "item_scraped_count": 309,
            "items_per_minute": 2060.0,
            "log_count/INFO": 206,
            "log_count/WARNING": 28,
            "memusage/max": 248020992,
            "memusage/startup": 248020992,
            "response_received_count": 5853,
            "responses_per_minute": 39020.0,
            "scheduler/dequeued": 1,
            "scheduler/dequeued/memory": 1,
            "scheduler/enqueued": 1,
            "scheduler/enqueued/memory": 1,
            "start_time": dt.datetime(2026, 6, 4, 6, 1, 9, 584488, tzinfo=dt.UTC),
        }
    )


@pytest.mark.parametrize("fixture_name", ["empty_stats", "base_stats", "full_stats_w_submit", "full_stats_wo_submit"])
def test_payload_keys(request: pytest.FixtureRequest, fixture_name: str) -> None:
    """Payload should always have the same keys."""
    scrapy_stats = request.getfixturevalue(fixture_name)
    for backend_host in VALID_BACKENDS + INVALID_BACKENDS:
        payload = _build_payload(scrapy_stats, backend_host)
        assert {"username", "icon_emoji", "text", "attachments"} == payload.keys()


@pytest.mark.parametrize("fixture_name", ["empty_stats", "base_stats", "full_stats_w_submit", "full_stats_wo_submit"])
def test_backend_host_in_text(request: pytest.FixtureRequest, fixture_name: str) -> None:
    """Backend host should always appear in the message text."""
    scrapy_stats = request.getfixturevalue(fixture_name)
    for backend_host in VALID_BACKENDS + INVALID_BACKENDS:
        payload = _build_payload(scrapy_stats, backend_host)
        assert backend_host in payload["text"]


@pytest.mark.parametrize("fixture_name", ["empty_stats", "base_stats", "full_stats_w_submit", "full_stats_wo_submit"])
def test_attachments_is_list(request: pytest.FixtureRequest, fixture_name: str) -> None:
    """Attachment should be list."""
    scrapy_stats = request.getfixturevalue(fixture_name)
    for backend_host in VALID_BACKENDS + INVALID_BACKENDS:
        payload = _build_payload(scrapy_stats, backend_host)
        assert isinstance(payload["attachments"], list)


def test_submission_counts_in_text(full_stats_w_submit: StatsCollector) -> None:
    """Total, attempted, accepted, rejected counts should appear in the text."""
    for backend_host in VALID_BACKENDS + INVALID_BACKENDS:
        payload = _build_payload(full_stats_w_submit, backend_host)
        assert "`329`" in payload["text"]
        assert "`309`" in payload["text"]
        assert "`272`" in payload["text"]
        assert "`37`" in payload["text"]


def test_attachments_grouped_by_prefix(full_stats_w_submit: StatsCollector) -> None:
    """Each PaZuFa/* prefix becomes its own attachment."""
    for backend_host in VALID_BACKENDS + INVALID_BACKENDS:
        payload = _build_payload(full_stats_w_submit, backend_host)
        titles = {a["title"] for a in payload["attachments"]}
        assert "Dokument Statistics" in titles
        assert "Vorgang Statistics" in titles
        assert "Text Statistics" in titles


def test_no_token_skips_signal(make_crawler: Callable[..., MagicMock]) -> None:
    """If MATTERMOST_TOKEN is not given, we skip listening to closing signal, i.e., no notifying."""
    crawler = make_crawler({"MATTERMOST_TOKEN": None, "API_URL": "https://api.pazufa.de"})
    MattermostNotifier(crawler)
    crawler.signals.connect.assert_not_called()


def test_localhost_api_url_skips_signal(make_crawler: Callable[..., MagicMock]) -> None:
    """If API_URL is local, we skip listening to closing signal, i.e., no notifying."""
    crawler = make_crawler(
        {
            "MATTERMOST_TOKEN": "token123",
            "MATTERMOST_URL": "https://mattermost.example.com",
            "API_URL": "http://localhost:8080",
        }
    )
    MattermostNotifier(crawler)
    crawler.signals.connect.assert_not_called()


def test_none_api_url_skips_signal(make_crawler: Callable[..., MagicMock]) -> None:
    """If API_URL is not given, we skip listening to closing signal, i.e., no notifying."""
    crawler = make_crawler(
        {
            "MATTERMOST_TOKEN": "token123",
            "MATTERMOST_URL": "https://mattermost.example.com",
            "API_URL": None,
        }
    )
    MattermostNotifier(crawler)
    crawler.signals.connect.assert_not_called()


def test_valid_config_connects_signal(valid_crawler: MagicMock) -> None:
    """If Settings are valid, we listen to signals, i.e., we notify."""
    MattermostNotifier(valid_crawler)
    valid_crawler.signals.connect.assert_called_once()


def test_signal_connects_to_spider_closed(valid_crawler: MagicMock) -> None:
    """If Settings are valid, check that we listen to the right signal."""
    MattermostNotifier(valid_crawler)
    _, kwargs = valid_crawler.signals.connect.call_args
    assert kwargs["signal"] == signals.spider_closed


def test_webhook_url_constructed_correctly(valid_crawler: MagicMock) -> None:
    """Test Webhook URL creation."""
    notifier = MattermostNotifier(valid_crawler)
    assert notifier._mattermost_webhook_url == "https://mattermost.example.com/token123"


def test_webhook_url_trailing_slash_stripped(make_crawler: Callable[..., MagicMock]) -> None:
    """Test Webhook URL creation."""
    crawler = make_crawler(
        {
            "MATTERMOST_TOKEN": "token123",
            "MATTERMOST_URL": "https://mattermost.example.com/",
            "API_URL": "https://api.pazufa.de",
        }
    )
    notifier = MattermostNotifier(crawler)
    assert notifier._mattermost_webhook_url == "https://mattermost.example.com/token123"


def test_token_set_but_no_url_raises(make_crawler: Callable[..., MagicMock]) -> None:
    """Test that if MATTERMOST_TOKEN is set, MATTERMOST_URL is required too."""
    crawler = make_crawler(
        {
            "MATTERMOST_TOKEN": "token123",
            "MATTERMOST_URL": None,
            "API_URL": "https://api.pazufa.de",
        }
    )
    with pytest.raises(ValueError, match=r".*MATTERMOST_TOKEN.*MATTERMOST_URL.*"):
        MattermostNotifier(crawler)


def test_from_crawler_creates_instance(valid_crawler: MagicMock) -> None:
    """Test that from_crawler classmethod creates a MattermostNotifier instance."""
    notifier = MattermostNotifier.from_crawler(valid_crawler)
    assert isinstance(notifier, MattermostNotifier)
    assert notifier.crawler is valid_crawler


def test_notify_mattermost_success(valid_crawler: MagicMock, full_stats_w_submit: StatsCollector) -> None:
    """Test that _notify_mattermost successfully sends a POST request with correct payload."""

    async def _test() -> None:
        notifier = MattermostNotifier(valid_crawler)
        valid_crawler.stats = full_stats_w_submit

        with patch("pazufa_scraper_be.extensions.mattermost.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            await notifier._notify_mattermost()

            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert call_args[0][0] == "https://mattermost.example.com/token123"
            expected_timeout = 10
            assert call_args[1]["timeout"] == expected_timeout
            assert call_args[1]["json"]["username"] == "Scraper BE"
            assert "api.pazufa.de" in call_args[1]["json"]["text"]

    asyncio.run(_test())


def test_notify_mattermost_http_error(valid_crawler: MagicMock, full_stats_w_submit: StatsCollector) -> None:
    """Test that _notify_mattermost catches httpx.HTTPError and logs it."""

    async def _test() -> None:
        notifier = MattermostNotifier(valid_crawler)
        valid_crawler.stats = full_stats_w_submit

        with patch("pazufa_scraper_be.extensions.mattermost.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post.side_effect = httpx.HTTPError("Network error")
            mock_client_class.return_value = mock_client

            with patch("pazufa_scraper_be.extensions.mattermost.logger") as mock_logger:
                await notifier._notify_mattermost()
                mock_logger.exception.assert_called_once_with("Failed to notify Mattermost.")

    asyncio.run(_test())


def test_notify_mattermost_timeout_error(valid_crawler: MagicMock, full_stats_w_submit: StatsCollector) -> None:
    """Test that _notify_mattermost catches httpx.TimeoutException and logs it."""

    async def _test() -> None:
        notifier = MattermostNotifier(valid_crawler)
        valid_crawler.stats = full_stats_w_submit

        with patch("pazufa_scraper_be.extensions.mattermost.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post.side_effect = httpx.TimeoutException("Request timeout")
            mock_client_class.return_value = mock_client

            with patch("pazufa_scraper_be.extensions.mattermost.logger") as mock_logger:
                await notifier._notify_mattermost()
                mock_logger.exception.assert_called_once_with("Failed to notify Mattermost.")

    asyncio.run(_test())


def test_notify_mattermost_skips_when_stats_none(valid_crawler: MagicMock) -> None:
    """Test that _notify_mattermost returns early when crawler.stats is None."""

    async def _test() -> None:
        notifier = MattermostNotifier(valid_crawler)
        valid_crawler.stats = None

        with patch("pazufa_scraper_be.extensions.mattermost.httpx.AsyncClient") as mock_client_class:
            await notifier._notify_mattermost()
            mock_client_class.assert_not_called()

    asyncio.run(_test())


def test_notify_mattermost_skips_when_backend_host_none(make_crawler: Callable[..., MagicMock], full_stats_w_submit: StatsCollector) -> None:
    """Test that _notify_mattermost returns early when backend_host is None."""

    async def _test() -> None:
        crawler = make_crawler(
            {
                "MATTERMOST_TOKEN": "token123",
                "MATTERMOST_URL": "https://mattermost.example.com",
                "API_URL": None,
            }
        )
        notifier = MattermostNotifier(crawler)
        crawler.stats = full_stats_w_submit

        with patch("pazufa_scraper_be.extensions.mattermost.httpx.AsyncClient") as mock_client_class:
            await notifier._notify_mattermost()
            mock_client_class.assert_not_called()

    asyncio.run(_test())
