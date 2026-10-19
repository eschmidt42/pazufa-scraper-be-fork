"""Scrapy settings for pazufa_scraper_be project.

For simplicity, this file contains only settings considered important or
commonly used. You can find more settings consulting the documentation:

    https://docs.scrapy.org/en/latest/topics/settings.html
    https://docs.scrapy.org/en/latest/topics/downloader-middleware.html
    https://docs.scrapy.org/en/latest/topics/spider-middleware.html
    https://docs.scrapy.org/en/latest/topics/autothrottle.html
"""

import os
import uuid

from pazufa_scraper_be.constants import CACHE_DIR_PATH
from pazufa_scraper_be.extensions.mattermost import MattermostNotifier
from pazufa_scraper_be.extensions.temp_error_dir import TempErrorDirectory
from pazufa_scraper_be.pipelines import (
    BuildPaZuFaVorgang,
    DownloadAndCacheDocuments,
    ExtractTextFromPDF,
    FixAndAddUrls,
    ReportAndDropErrors,
    SubmitVorgang,
    SummarizeExtractedPDFText,
)

# Arguments
LOG_LEVEL = "INFO"

WAHLPERIODE = 19

API_TOKEN = os.environ.get("PAZUFA_API_TOKEN")
API_URL = os.environ.get("PAZUFA_API_URL", "http://localhost:8080")

LLM_TOKEN = os.environ.get("PAZUFA_LLM_TOKEN")
LLM_MODEL = os.environ.get("PAZUFA_LLM_MODEL", "openrouter/openai/gpt-5-nano")
LLM_TIMEOUT = os.environ.get("PAZUFA_LLM_TIMEOUT", None) or 5 * 60

MATTERMOST_URL = os.environ.get("PAZUFA_MATTERMOST_URL", "https://chat.pazufa.de/hooks")
MATTERMOST_TOKEN = os.environ.get("PAZUFA_MATTERMOST_TOKEN")

# Custom Settings
SCRAPER_UUID = uuid.UUID("05dc56fc-24e1-442b-9f97-91d596d50471")
CACHE_DIR = CACHE_DIR_PATH

# Scrapy Settings
BOT_NAME = "PaZuFa_Berlin_Scraper"

SPIDER_MODULES = ["pazufa_scraper_be.spiders"]
NEWSPIDER_MODULE = "pazufa_scraper_be.spiders"

ADDONS = {}

# Crawl responsibly by identifying yourself (and your website) on the user-agent
USER_AGENT = "Parlamentszusammenfasser (PaZuFa) Berlin Scraper (+https://pazufa.de/)"

# Obey robots.txt rules
ROBOTSTXT_OBEY = False  # NOTE: this is not nice

# Concurrency and throttling settings
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 1
CONCURRENT_ITEMS = 1

# Disable Telnet Console (enabled by default)
TELNETCONSOLE_ENABLED = False

# Configure item pipelines
ITEM_PIPELINES = {
    # NOTE: Pipelines with <100 get proper items or dicts, which contain data an error.
    ReportAndDropErrors: 99,
    # NOTE: Pipelines with >= 100 only get properly parsed items.
    FixAndAddUrls: 100,
    DownloadAndCacheDocuments: 110,
    ExtractTextFromPDF: 120,
    SummarizeExtractedPDFText: 130,
    BuildPaZuFaVorgang: 999,
    SubmitVorgang: 1000,
}

EXTENSIONS = {
    MattermostNotifier: 500,
    TempErrorDirectory: 600,
}

# Enable and configure HTTP caching (disabled by default)
# See https://docs.scrapy.org/en/latest/topics/downloader-middleware.html#httpcache-middleware-settings
HTTPCACHE_ENABLED = True
HTTPCACHE_EXPIRATION_SECS = 60 * 60 * 24
HTTPCACHE_DIR = "httpcache"
HTTPCACHE_IGNORE_HTTP_CODES = []
HTTPCACHE_STORAGE = "scrapy.extensions.httpcache.FilesystemCacheStorage"

# Set settings whose default value is deprecated to a future-proof value
FEED_EXPORT_ENCODING = "utf-8"
