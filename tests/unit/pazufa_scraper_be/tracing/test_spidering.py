import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from scrapy.settings import Settings

from pazufa_scraper_be.pardok.vorgang import GesetzVorgang
from pazufa_scraper_be.tracing import spidering


def test_manual_input_spider_yields_configured_item() -> None:
    """Yield the item supplied when constructing the spider."""
    item = {"id": "vorg123"}
    spider = spidering.ManualInputSpider(item=item)

    async def collect_items() -> list[dict]:
        return [yielded_item async for yielded_item in spider.start()]  # ty: ignore[not-iterable]

    assert asyncio.run(collect_items()) == [item]


@pytest.mark.parametrize("as_model", [False, True])
def test_run_item_runs_spider_and_records_completed_span(
    monkeypatch: pytest.MonkeyPatch,
    base_vorgang_data: dict[str, object],
    as_model: bool,
) -> None:
    """Run the spider with the item and record its metadata in the span."""
    item = GesetzVorgang.model_validate(base_vorgang_data) if as_model else {"id": "vorg123"}
    settings = Settings()
    span = MagicMock()
    span_context = MagicMock()
    span_context.__enter__.return_value = span
    start_span = Mock(return_value=span_context)
    monkeypatch.setattr(spidering.mlflow, "start_span", start_span)

    crawler_runner = Mock()
    crawler = Mock()
    crawler.crawl = AsyncMock()
    crawler_runner.return_value = crawler
    monkeypatch.setattr(spidering, "AsyncCrawlerRunner", crawler_runner)

    asyncio.run(spidering.run_item(settings, item))

    start_span.assert_called_once_with(name="single-item crawl")
    span.set_inputs.assert_called_once_with(
        {
            "item_id": "vorg123",
            "item_type": type(item).__name__,
        }
    )
    crawler_runner.assert_called_once_with(settings=settings)
    crawler.crawl.assert_awaited_once_with(spidering.ManualInputSpider, item=item)
    span.set_outputs.assert_called_once_with({"status": "completed"})
