import logging
from collections import defaultdict
from typing import Self
from urllib.parse import urlparse

import httpx
from scrapy import signals
from scrapy.crawler import Crawler
from scrapy.statscollectors import StatsCollector

from pazufa_scraper_be.pipelines._support.stats_counter import PAZUFA, VorgangCounter

logger = logging.getLogger(__name__)


class MattermostNotifier:
    """Sends a statistics summary to Mattermost when the spider closes."""

    def __init__(self: Self, crawler: Crawler) -> None:
        """Initialize the notifier and connect to spider_closed signal."""
        self.crawler = crawler

        mattermost_token = crawler.settings.get("MATTERMOST_TOKEN")
        mattermost_url = crawler.settings.get("MATTERMOST_URL")
        api_url = crawler.settings.get("API_URL")

        self.backend_host = urlparse(api_url, allow_fragments=False).hostname or None

        if mattermost_token is None:
            msg = "MATTERMOST_TOKEN is not set. Will not notify on Mattermost."
            logger.info(msg)
            return

        if mattermost_url is None:
            msg = "If MATTERMOST_TOKEN is set, MATTERMOST_URL setting is required."
            raise ValueError(msg)

        if self.backend_host == "localhost" or self.backend_host is None:
            msg = f"Backend host is {self.backend_host}. Will not notify on Mattermost."
            logger.info(msg)
            return

        self._mattermost_webhook_url = f"{mattermost_url.rstrip('/')}/{mattermost_token}"
        crawler.signals.connect(self._notify_mattermost, signal=signals.spider_closed)

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> Self:
        """Create a MattermostNotifier from a Scrapy crawler."""
        return cls(crawler)

    async def _notify_mattermost(self: Self) -> None:
        if self.crawler.stats is None or not self.backend_host:
            return

        payload = _build_payload(self.crawler.stats, self.backend_host)

        try:
            async with httpx.AsyncClient() as client:
                await client.post(self._mattermost_webhook_url, json=payload, timeout=10)

        except (httpx.HTTPError, httpx.TimeoutException):
            logger.exception("Failed to notify Mattermost.")


def _build_payload(scrapy_stats: StatsCollector, backend_host: str) -> dict:
    stats_dict = {k.removeprefix(f"{PAZUFA}/"): v for k, v in scrapy_stats.get_stats().items() if k.startswith(PAZUFA)}

    number_total_vorgaenge = int(scrapy_stats.get_value(VorgangCounter.TOTAL, 0))
    number_out_of_scope_vorgaenge = int(scrapy_stats.get_value(VorgangCounter.DROP_OUT_OF_SCOPE, 0))
    number_submitted_vorgaenge = int(scrapy_stats.get_value(VorgangCounter.SUBMIT_ATTEMPT, 0))
    number_grace_period_error_vorgaenge = int(scrapy_stats.get_value(VorgangCounter.SUBMIT_ERROR, 0))
    number_accepted_vorgaenge = int(scrapy_stats.get_value(VorgangCounter.SUBMIT_ACCEPTED, 0))
    rejected_codes_counts = {
        int(key.split("/")[-1]): int(count) for key, count in scrapy_stats.get_stats().items() if key.startswith(VorgangCounter.SUBMIT_REJECTED)
    }
    number_rejected_vorgaenge = sum(rejected_codes_counts.values())

    rejected_lines = [f"\t├ {code}: `{count}`" for code, count in list(rejected_codes_counts.items())[:-1]]
    rejected_lines += [f"\t└ {code}: `{count}`" for code, count in list(rejected_codes_counts.items())[-1:]]

    description_lines = [
        f"📋 `{number_total_vorgaenge}` Vorgänge found",
        f"🚫 `{number_out_of_scope_vorgaenge}` Vorgänge are out of scope",
        f"📤 `{number_submitted_vorgaenge}` submitted to the backend",
        f"├ ✅ `{number_accepted_vorgaenge}` accepted",
        f"├ ⚠️ `{number_grace_period_error_vorgaenge}` grace period errors",
        f"└ ❌ `{number_rejected_vorgaenge}` rejected with status codes",
        *rejected_lines,
        "\n ",  # Nicer formatting in Mattermost
    ]

    grouped = defaultdict(dict)
    for k, v in stats_dict.items():
        prefix, _, suffix = k.partition("/")
        grouped.setdefault(prefix, []).append({"title": suffix, "value": str(v), "short": True})

    attachments = [
        {
            "title": f"{prefix.capitalize()} Statistics",
            "fields": fields,
        }
        for prefix, fields in grouped.items()
    ]

    return {
        "username": "Scraper BE",
        "icon_emoji": ":spider:",
        "text": f"## Submitted to `{backend_host}`\n\n{'\n'.join(description_lines)}",
        "attachments": attachments,
    }
