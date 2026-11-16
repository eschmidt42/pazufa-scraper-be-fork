import asyncio
from pathlib import Path

import mlflow
import pytest
from mlflow.entities import Trace
from scrapy.settings import Settings
from scrapy.utils.project import get_project_settings

from pazufa_scraper_be.pardok.vorgang import GesetzVorgang
from pazufa_scraper_be.pipelines import (
    BuildPaZuFaVorgang,
    DownloadDocuments,
    ExtractText,
    HandleErrors,
    PrepareDocumentUrls,
    SummarizeText,
)
from pazufa_scraper_be.tracing.compare import (
    convert_span_to_vorgang,
    find_feeds,
    find_span,
    get_deviating_fields_between_spans,
    get_item_id_for_trace,
    shoddy_field_validation,
)
from pazufa_scraper_be.tracing.spidering import run_item
from pazufa_scraper_be.tracing.trace_pipeline import OutcomesEnum, get_traces_from_mlflow_db, trace_pipeline
from pazufa_scraper_be.tracing.vorgang_helper import feed_to_gesetz_vorgang_dicts, validate_vorgang

EXPERIMENT_REFERENCE = "integration reference"
EXPERIMENT_TEST_RUN = "integration test run"
SPAN_NAME = "BuildPaZuFaVorgang"
EXPECTED_FIELDS = [
    "api_id",
    "titel",
    "wahlperiode",
    "typ",
    "initiatoren",
    "stationen",
    "ids",
    "links",
    "sachgebiete",
    "ressort",
    "schlagworte",
    "verfassungsaendernd",
    "kurztitel",
    "lobbyregister",
]
EXPECTED_NOT_NONE_FIELDS = ["api_id"]

DB_DIR = Path(__file__).resolve().parent.parent
REFERENCE_DB_NAME = "integration-reference-mlflow.db"
TEST_RUN_DB_NAME = "integration-tests-mlflow.db"

LAST_MINUTES = 60


@pytest.fixture
def traces_reference() -> list[Trace]:
    """Load reference traces from the integration-reference MLflow database."""
    # collecting reference information

    reference_db_path = DB_DIR / REFERENCE_DB_NAME
    if not reference_db_path.exists():
        pytest.fail(f"Reference MLflow database is not available: {reference_db_path}")

    tracking_uri_reference = f"sqlite:///{reference_db_path}"
    return get_traces_from_mlflow_db(
        tracking_uri=tracking_uri_reference,
        experiment=EXPERIMENT_REFERENCE,
    )


@pytest.fixture
def comparison_settings() -> Settings:
    """Settings scrapy settings for the comparison run."""
    settings = get_project_settings()
    settings.set("TWISTED_REACTOR_ENABLED", False, priority="cmdline")  # noqa: FBT003
    return settings


def _get_filtered_gesetz_vorgangs_for_the_run(item_ids_in_reference: set[str], settings: Settings) -> list[GesetzVorgang]:

    feed = asyncio.run(find_feeds(settings, allow_download=False))
    gesetz_vorgang_dicts = feed_to_gesetz_vorgang_dicts(feed)

    gesetz_vorgangs_to_run = [validate_vorgang(g) for g in gesetz_vorgang_dicts]
    filtered_gesetz_vorgangs_to_run = [g for g in gesetz_vorgangs_to_run if isinstance(g, GesetzVorgang) and g.id in item_ids_in_reference]

    assert len(filtered_gesetz_vorgangs_to_run) > 0
    return filtered_gesetz_vorgangs_to_run


@pytest.fixture
def comparison_items(traces_reference: list[Trace], comparison_settings: Settings) -> list[GesetzVorgang]:
    """Collect items to do the comparison runs for."""
    item_ids_in_reference = {get_item_id_for_trace(_t) for _t in traces_reference}

    return _get_filtered_gesetz_vorgangs_for_the_run(item_ids_in_reference, comparison_settings)


@pytest.fixture
def test_run_traces(comparison_settings: Settings, comparison_items: list[GesetzVorgang]) -> list[Trace]:
    """Set up mlflow, update settings, run pipelines and retrieve traces."""
    db_path_test_run = (DB_DIR / TEST_RUN_DB_NAME).resolve()
    assert db_path_test_run is not None

    tracking_uri_test_run = f"sqlite:///{db_path_test_run}"
    mlflow.set_tracking_uri(tracking_uri_test_run)
    mlflow.set_experiment(EXPERIMENT_TEST_RUN)

    # tracing of pipelines
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

    comparison_settings["ITEM_PIPELINES"] = item_pipelines

    # running the traced pipelines
    for g in comparison_items:
        asyncio.run(run_item(comparison_settings, g))

    # collecting the new traces
    return get_traces_from_mlflow_db(span_name=SPAN_NAME, tracking_uri=tracking_uri_test_run, experiment=EXPERIMENT_TEST_RUN, last_minutes=LAST_MINUTES)


@pytest.mark.integration
def test_run_comparisons(traces_reference: list[Trace], comparison_items: list[GesetzVorgang], test_run_traces: list[Trace]) -> None:
    """Compare traced pipeline results with references for matching feed items."""
    for vorgang in comparison_items:
        item_id_reference, span_reference, outcome_reference = find_span(traces_reference, comparison_item_id=vorgang.id, comparison_span_name=SPAN_NAME)

        item_id_test_run, span_test_run, outcome_test_run = find_span(test_run_traces, comparison_item_id=vorgang.id, comparison_span_name=SPAN_NAME)

        assert item_id_reference == item_id_test_run
        assert outcome_reference == outcome_test_run

        if outcome_reference is not OutcomesEnum.passed:
            continue

        vorgang_reference = convert_span_to_vorgang(span_reference)
        shoddy_field_validation(item_id_reference, vorgang_reference, expected_fields=EXPECTED_FIELDS, expected_not_none_fields=EXPECTED_NOT_NONE_FIELDS)

        vorgang_test_run = convert_span_to_vorgang(span_test_run)
        shoddy_field_validation(item_id_reference, vorgang_test_run, expected_fields=EXPECTED_FIELDS, expected_not_none_fields=EXPECTED_NOT_NONE_FIELDS)

        deviating_fields_reference_vs_test_run = get_deviating_fields_between_spans(vorgang_new=vorgang_test_run, vorgang_reference=vorgang_reference)

        assert deviating_fields_reference_vs_test_run == ()
