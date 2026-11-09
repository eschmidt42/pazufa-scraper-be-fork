import asyncio
from pathlib import Path

import mlflow
import tqdm
from scrapy.settings import Settings
from scrapy.utils.project import get_project_settings

from pazufa_scraper_be.pipelines import (
    BuildPaZuFaVorgang,
    DownloadDocuments,
    ExtractText,
    HandleErrors,
    PrepareDocumentUrls,
    SummarizeText,
)
from pazufa_scraper_be.tracing.compare import find_feeds
from pazufa_scraper_be.tracing.spidering import run_item
from pazufa_scraper_be.tracing.trace_pipeline import trace_pipeline
from pazufa_scraper_be.tracing.vorgang_helper import feed_to_gesetz_vorgang_dicts, validate_vorgang


async def main(settings:Settings, *,n_max_gesetz_vorgang:int = 5) -> None:
    """Run traced pipelines for up to the requested number of feed items."""
    settings.set("TWISTED_REACTOR_ENABLED", False, priority="cmdline")  # noqa: FBT003

    feed = await find_feeds(settings,allow_download=True)

    gesetz_vorgang_dicts = feed_to_gesetz_vorgang_dicts(feed)

    n_successes = 0
    # TODO(me): prettify progress bars using rich - currently two are configured but during the run only the feed records bar is visible
    with (
        tqdm.tqdm(
            total=len(gesetz_vorgang_dicts),
            desc="Feed records visited",
            position=0,
        ) as records_bar,
        tqdm.tqdm(
            total=n_max_gesetz_vorgang,
            desc="Successful runs (max)",
            position=1,
        ) as successes_bar,
    ):

        for gesetz_vorgang_dict in gesetz_vorgang_dicts:
            records_bar.update(1)

            item = validate_vorgang(gesetz_vorgang_dict)
            if isinstance(item,dict):
                continue

            await run_item(settings, item)
            n_successes += 1
            successes_bar.update(1)

            if n_successes >= n_max_gesetz_vorgang:
                break



if __name__ == "__main__":

    n_max_gesetz_vorgang = 5

    settings = get_project_settings()

    root_path = Path(__file__).parent.parent
    db_path = (root_path / "tests" / "integration-reference-mlflow.db").resolve()
    assert db_path is not None

    db_path.parent.mkdir(parents=False, exist_ok=True)

    experiment = "integration reference"
    tracking_uri = f"sqlite:///{db_path}"

    mlflow.set_tracking_uri(tracking_uri)

    mlflow.set_experiment(experiment)

    item_pipelines = {
        HandleErrors: 99,
        PrepareDocumentUrls: 100,
        DownloadDocuments: 110,
        ExtractText: 120,
        SummarizeText: 130,
        BuildPaZuFaVorgang: 999,
    }
    for pipeline_cls in item_pipelines:
        trace_pipeline(pipeline_cls)

    settings["ITEM_PIPELINES"] = item_pipelines

    asyncio.run(main(settings, n_max_gesetz_vorgang=n_max_gesetz_vorgang))
