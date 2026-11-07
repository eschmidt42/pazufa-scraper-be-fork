from collections.abc import Generator

import mlflow
import scrapy
from scrapy.crawler import AsyncCrawlerRunner
from scrapy.settings import Settings

from pazufa_scraper_be.pardok.vorgang import GesetzVorgang


class ManualInputSpider(scrapy.Spider):
    """Manual spider using a static item to pass to the pipelines."""

    name = "manual-input"

    def __init__(self, item: GesetzVorgang | dict, name: str | None = None, **kwargs: object) -> None:
        """Spider for `item`, a manually constructed GesetzVorgang."""
        super().__init__(name=name, **kwargs)
        self.item = item

    async def start(self) -> Generator[GesetzVorgang | dict]:  # ty: ignore[invalid-method-override, invalid-return-type]
        """Start with fix item to pass to the pipelines."""
        yield self.item


async def run_item(settings: Settings, item: GesetzVorgang | dict) -> None:
    """Run pipelines with dummy spider."""
    item_id = item.get("id") if isinstance(item, dict) else item.id

    with mlflow.start_span(name="single-item crawl") as span:
        span.set_inputs(
            {
                "item_id": item_id,
                "item_type": type(item).__name__,
            }
        )
        runner = AsyncCrawlerRunner(settings=settings)
        await runner.crawl(ManualInputSpider, item=item)

        span.set_outputs({"status": "completed"})
