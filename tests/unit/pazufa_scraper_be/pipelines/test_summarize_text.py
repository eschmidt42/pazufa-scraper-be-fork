import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pazufa_corelib.cache import Value
from pazufa_corelib.llm import LLMProviderError
from scrapy import Spider
from scrapy.crawler import Crawler
from scrapy.exceptions import DropItem
from scrapy.settings import Settings
from scrapy.statscollectors import StatsCollector

from pazufa_scraper_be.cache import Cache, Key
from pazufa_scraper_be.pardok import AnyGesetzDokument, GesetzVorgang
from pazufa_scraper_be.pipelines.documents.summarize_text import SummarizeText
from pazufa_scraper_be.pipelines.stats_counter import LLMCounter, SummaryCounter


@pytest.fixture
def summarize_pipeline(tmp_path: Path) -> tuple[SummarizeText, MagicMock]:
    """Create a summarization pipeline with a mocked connector and isolated cache."""
    connector = MagicMock()
    connector.summarize_dokument = AsyncMock(return_value="summary text")
    connector.summarize_gesetzentwurf = AsyncMock(return_value="summary text")
    connector.extract_relevant_section = AsyncMock(return_value="relevant text")

    crawler = Crawler(
        Spider,
        Settings(
            {
                "WAHLPERIODE": 19,
                "CACHE_DIR": tmp_path,
                "LLM_TOKEN": "test-token",
                "LLM_MODEL": "test-model",
                "LLM_TIMEOUT": 30,
            }
        ),
    )
    crawler.stats = StatsCollector(crawler)

    with patch("pazufa_scraper_be.pipelines._base.LLMConnector", return_value=connector):
        pipeline = SummarizeText(crawler)

    return pipeline, connector


def _cache_for_document(pipeline: SummarizeText, document: AnyGesetzDokument) -> Cache:
    assert document.lok_url is not None
    return pipeline.get_cache(document=document, document_url=document.lok_url)


def test_summarize_pipeline_rejects_non_vorgang(summarize_pipeline: tuple[SummarizeText, MagicMock]) -> None:
    """Items of an unexpected type are dropped."""
    pipeline, _ = summarize_pipeline
    invalid_item: Any = object()

    with pytest.raises(DropItem, match="Expected GesetzVorgang object"):
        asyncio.run(pipeline.process_item(invalid_item))


def test_summarize_pipeline_skips_when_llm_is_disabled(
    base_vorgang_data: dict[str, Any],
    drs_data: dict[str, Any],
    summarize_pipeline: tuple[SummarizeText, MagicMock],
) -> None:
    """An item is returned unchanged when no LLM connector is configured."""
    pipeline, connector = summarize_pipeline
    pipeline.llm_connector = None
    item = GesetzVorgang.model_validate({**base_vorgang_data, "Dokument": [drs_data]})

    result = asyncio.run(pipeline.process_item(item))

    assert result is item
    connector.summarize_dokument.assert_not_awaited()
    assert pipeline.stats.get_value(SummaryCounter.CACHE_MISS.value) is None


def test_summarize_pipeline_skips_missing_text(
    base_vorgang_data: dict[str, Any],
    drs_data: dict[str, Any],
    summarize_pipeline: tuple[SummarizeText, MagicMock],
) -> None:
    """Documents without cached text are skipped without an LLM call."""
    pipeline, connector = summarize_pipeline
    item = GesetzVorgang.model_validate({**base_vorgang_data, "Dokument": [drs_data]})

    asyncio.run(pipeline.process_item(item))

    connector.summarize_dokument.assert_not_awaited()
    assert pipeline.stats.get_value(SummaryCounter.CACHE_MISS.value) is None


def test_summarize_pipeline_skips_ignored_document(
    base_vorgang_data: dict[str, Any],
    drs_data: dict[str, Any],
    summarize_pipeline: tuple[SummarizeText, MagicMock],
) -> None:
    """Documents marked to ignore are counted and skipped."""
    pipeline, connector = summarize_pipeline
    item = GesetzVorgang.model_validate({**base_vorgang_data, "Dokument": [drs_data]})
    cache = _cache_for_document(pipeline, item.dokumente[0])
    cache[Key.SUMMARY_IGNORE] = "already ignored"

    asyncio.run(pipeline.process_item(item))

    connector.summarize_dokument.assert_not_awaited()
    assert pipeline.stats.get_value(SummaryCounter.IGNORE.value) == 1


def test_summarize_pipeline_links_cached_model_summary(
    base_vorgang_data: dict[str, Any],
    drs_data: dict[str, Any],
    summarize_pipeline: tuple[SummarizeText, MagicMock],
) -> None:
    """An existing model-specific summary is linked without another LLM call."""
    pipeline, connector = summarize_pipeline
    item = GesetzVorgang.model_validate({**base_vorgang_data, "Dokument": [drs_data]})
    cache = _cache_for_document(pipeline, item.dokumente[0])
    cache[Key.TEXT] = "cached document text"
    cache.set_model_specific_summary("test-model", "cached summary")

    result = asyncio.run(pipeline.process_item(item))

    summary_file = cache.backend.get_file_path(key=Key.SUMMARY, value_type=Value.TEXT)
    assert result is item
    assert summary_file.is_symlink()
    assert summary_file.read_text() == "cached summary"
    connector.summarize_dokument.assert_not_awaited()
    assert pipeline.stats.get_value(SummaryCounter.CACHE_HIT.value) == 1


@pytest.mark.parametrize(
    "scenario",
    [
        ("drs_data", "summarize_dokument"),
        ("gvbl_data", "summarize_gesetzentwurf"),
    ],
)
def test_summarize_pipeline_dispatches_and_caches_document_summary(
    request: pytest.FixtureRequest,
    base_vorgang_data: dict[str, Any],
    summarize_pipeline: tuple[SummarizeText, MagicMock],
    scenario: tuple[str, str],
) -> None:
    """Drucksachen and GVBl documents use their expected LLM method and cache its result."""
    pipeline, connector = summarize_pipeline
    document_fixture, method_name = scenario
    document_data = request.getfixturevalue(document_fixture)
    item = GesetzVorgang.model_validate({**base_vorgang_data, "Dokument": [document_data]})
    document = item.dokumente[0]
    cache = _cache_for_document(pipeline, document)
    cache[Key.TEXT] = "document text"

    result = asyncio.run(pipeline.process_item(item))

    method = getattr(connector, method_name)
    method.assert_awaited_once_with(titel=getattr(document, "titel", ""), text="document text")
    summary_file = cache.backend.get_file_path(key=Key.SUMMARY, value_type=Value.TEXT)
    assert result is item
    assert summary_file.is_symlink()
    assert summary_file.read_text() == "summary text"
    assert pipeline.stats.get_value(SummaryCounter.CACHE_MISS.value) == 1
    assert pipeline.stats.get_value(LLMCounter.SUMMARIZE_DONE.value) == 1
    assert pipeline.stats.get_value(LLMCounter.summarize_art(document.art_l.lower())) == 1


def test_summarize_pipeline_extracts_protocol_section_before_summarizing(
    base_vorgang_data: dict[str, Any],
    plpr_data: dict[str, Any],
    summarize_pipeline: tuple[SummarizeText, MagicMock],
) -> None:
    """Protocol text is summarized only after a relevant section is extracted."""
    pipeline, connector = summarize_pipeline
    item = GesetzVorgang.model_validate({**base_vorgang_data, "Dokument": [plpr_data]})
    cache = _cache_for_document(pipeline, item.dokumente[0])
    cache[Key.TEXT] = "full protocol text"

    asyncio.run(pipeline.process_item(item))

    connector.extract_relevant_section.assert_awaited_once_with(
        text="full protocol text",
        vorgang_titel="",
        vorgang_vnr="123/2024",
    )
    connector.summarize_dokument.assert_awaited_once_with(titel="", text="relevant text")
    assert pipeline.stats.get_value(LLMCounter.EXTRACT_RELEVANT_SECTION_DONE.value) == 1
    assert pipeline.stats.get_value(LLMCounter.summarize_art(item.dokumente[0].art_l.lower())) == 1


def test_summarize_pipeline_ignores_protocol_without_relevant_section(
    base_vorgang_data: dict[str, Any],
    plpr_data: dict[str, Any],
    summarize_pipeline: tuple[SummarizeText, MagicMock],
) -> None:
    """A protocol without a relevant section is marked ignored and not summarized."""
    pipeline, connector = summarize_pipeline
    connector.extract_relevant_section.return_value = None
    item = GesetzVorgang.model_validate({**base_vorgang_data, "Dokument": [plpr_data]})
    cache = _cache_for_document(pipeline, item.dokumente[0])
    cache[Key.TEXT] = "full protocol text"

    asyncio.run(pipeline.process_item(item))

    assert cache[Key.SUMMARY_IGNORE] == "Ignoring because no relevant section was found."
    connector.summarize_dokument.assert_not_awaited()
    assert pipeline.stats.get_value(LLMCounter.EXTRACT_RELEVANT_SECTION_FAILED.value) == 1
    assert pipeline.stats.get_value(LLMCounter.SUMMARIZE_FAILED_APPLICATION.value) == 1


@pytest.mark.parametrize(
    "scenario",
    [
        (None, LLMCounter.SUMMARIZE_FAILED_APPLICATION, "LLM summarization failed due to application problem."),
        ("", LLMCounter.SUMMARIZE_FAILED_EMPTY_SUMMARY, "Summary is empty."),
    ],
)
def test_summarize_pipeline_does_not_cache_failed_summary(
    base_vorgang_data: dict[str, Any],
    drs_data: dict[str, Any],
    summarize_pipeline: tuple[SummarizeText, MagicMock],
    caplog: pytest.LogCaptureFixture,
    scenario: tuple[str | None, LLMCounter, str],
) -> None:
    """Application failures and empty summaries are logged and not cached."""
    pipeline, connector = summarize_pipeline
    summary, counter, message = scenario
    connector.summarize_dokument.return_value = summary
    item = GesetzVorgang.model_validate({**base_vorgang_data, "Dokument": [drs_data]})
    cache = _cache_for_document(pipeline, item.dokumente[0])
    cache[Key.TEXT] = "document text"

    asyncio.run(pipeline.process_item(item))

    assert Key.SUMMARY not in cache
    assert pipeline.stats.get_value(counter.value) == 1
    assert f"[{item.id} - {item.dokumente[0].id}]" in caplog.text
    assert message in caplog.text


def test_summarize_pipeline_marks_provider_failure_ignored(
    base_vorgang_data: dict[str, Any],
    drs_data: dict[str, Any],
    summarize_pipeline: tuple[SummarizeText, MagicMock],
) -> None:
    """Provider errors mark a document ignored and increment the provider-failure counter."""
    pipeline, connector = summarize_pipeline
    connector.summarize_dokument.side_effect = LLMProviderError("provider unavailable")
    item = GesetzVorgang.model_validate({**base_vorgang_data, "Dokument": [drs_data]})
    cache = _cache_for_document(pipeline, item.dokumente[0])
    cache[Key.TEXT] = "document text"

    asyncio.run(pipeline.process_item(item))

    assert cache[Key.SUMMARY_IGNORE] == "LLMProviderError('provider unavailable')"
    assert Key.SUMMARY not in cache
    assert pipeline.stats.get_value(LLMCounter.SUMMARIZE_FAILED_PROVIDER.value) == 1
