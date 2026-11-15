import logging
from collections.abc import Mapping
from pathlib import Path

from mlflow.entities import Span, Trace
from scrapy.crawler import AsyncCrawlerRunner
from scrapy.settings import Settings

from pazufa_scraper_be.pipelines.build_vorgang import PaZuFaVorgang
from pazufa_scraper_be.spiders.gesetz_vorgang import GesetzVorgangSpider
from pazufa_scraper_be.tracing.trace_pipeline import OutcomesEnum

logger = logging.getLogger(__name__)

FIELDS_TO_COMPARE = ("api_id", "typ", "verfassungsaendernd", "wahlperiode", "ids", "links")


def get_item_id_for_trace(trace: Trace) -> str:
    """Return the item ID recorded in the trace's first span."""
    return trace.data.spans[0].inputs["item_id"]


def find_trace(traces: list[Trace], item_id: str) -> Trace | None:
    """Find the trace associated with an item ID, if present."""
    for trace in traces:
        if get_item_id_for_trace(trace) == item_id:
            return trace
    return None


def find_span(traces: list[Trace], *, comparison_item_id: str, comparison_span_name: str) -> tuple[str, Span, OutcomesEnum]:
    """Find a named span for an item and return it with its outcome."""
    span_located = False

    trace = find_trace(traces, comparison_item_id)

    if trace is None:
        msg = f"Failed to locate trace with {comparison_item_id=}"
        raise ValueError(msg)

    for span in trace.data.spans:
        if span.name == comparison_span_name:
            span_located = True
            break

    if not span_located:
        msg = f"Failed to locate span with name {comparison_span_name} for {comparison_item_id=}"
        raise ValueError(msg)

    if span.outputs is None:
        msg = f"span.outputs is None for span name {comparison_span_name} and {comparison_item_id=}."
        raise ValueError(msg)

    outcome = span.outputs["outcome"]

    return comparison_item_id, span, OutcomesEnum(outcome)


def shoddy_field_validation(item_id: str, vorgang: PaZuFaVorgang, expected_fields: list[str], expected_not_none_fields: list[str]) -> None:
    """Raise an error if expected fields are missing or unexpectedly None."""
    if not set(expected_not_none_fields).issubset(expected_fields):
        _unexpectedly_none_fields = [f for f in expected_not_none_fields if f not in expected_fields]
        msg = (
            "Passed expected_not_none_fields is not a subset of passed expected fields. "
            f"Additional values in expected_not_none_fields: {_unexpectedly_none_fields}"
        )
        raise ValueError(msg)

    missing_fields = [f for f in expected_fields if not hasattr(vorgang, f)]
    surprising_none_fields = [f for f in expected_not_none_fields if getattr(vorgang, f) is None]

    msg = f"Vorgang {item_id} has\n"
    if len(missing_fields) > 0:
        msg += f"- missing fields: {missing_fields}"
    if len(surprising_none_fields) > 0:
        msg += f"- fields taking on None even though they shouldn't: {surprising_none_fields}"

    if len(missing_fields) > 0 or len(surprising_none_fields) > 0:
        raise ValueError(msg)


def deterministic_projection(vorgang: PaZuFaVorgang, fields_to_compare: tuple[str, ...]) -> dict[str, object]:
    """Project a Vorgang onto selected fields for deterministic comparison."""
    data = vorgang.to_dict()
    return {field: data[field] for field in fields_to_compare}


def get_deviating_fields_between_spans(
    vorgang_new: PaZuFaVorgang, vorgang_reference: PaZuFaVorgang, fields_to_compare: tuple[str, ...] = FIELDS_TO_COMPARE
) -> tuple[str, ...]:
    """Return selected fields that differ between new and reference Vorgang data."""
    data_new = deterministic_projection(vorgang_new, fields_to_compare)
    data_reference = deterministic_projection(vorgang_reference, fields_to_compare)

    if data_new == data_reference:
        return ()

    return tuple([f for f in fields_to_compare if data_new[f] != data_reference[f]])


def flag_field_deviation(item_id: str, deviating_fields: tuple[str, ...], *, vorgang_new: PaZuFaVorgang, vorgang_reference: PaZuFaVorgang) -> None:
    """Log the values of fields that differ from the reference Vorgang."""
    if len(deviating_fields) == 0:
        return

    msg = f"Found the following fields to deviate for {item_id} (reference -> new):"
    for f in deviating_fields:
        r = getattr(vorgang_reference, f)
        n = getattr(vorgang_new, f)
        msg += f"\n- {f}: {r=} -> {n=}"

    logger.warning(msg)


async def find_feeds(settings: Settings, *, idx: int = -1, allow_download: bool = True) -> Path:
    """Return a cached XML feed, optionally crawling to download one if needed."""
    feed_dir = Path(settings.get("CACHE_DIR")) / str(settings.getint("WAHLPERIODE")) / "feeds"
    feeds = sorted(feed_dir.glob("*.xml"), key=lambda path: path.stat().st_mtime)

    if (not feeds) and allow_download:
        download_settings = settings.copy()
        download_settings.set("ITEM_PIPELINES", {}, priority="cmdline")

        runner = AsyncCrawlerRunner(settings=download_settings)
        await runner.crawl(GesetzVorgangSpider)

        feeds = sorted(feed_dir.glob("*.xml"))

    if not feeds:
        msg = f"No XML feed found or saved in {feed_dir}"
        raise FileNotFoundError(msg)

    return feeds[idx]


def convert_span_to_vorgang(span: Span) -> PaZuFaVorgang:
    """Build a Vorgang from the item data in a span's outputs."""
    if "item" not in span.outputs:
        msg = "span.outputs does not contain PaZuFaVorgang relevant information under 'item'"
        raise ValueError(msg)
    if not isinstance(span.outputs["item"], Mapping):
        msg = "span.outputs['item'] value is surprisingly not a Mapping. Should be to contain PaZuFaVorgang relevant information."
        raise TypeError(msg)
    # this instantiates the object, but does not do validation akin to pydantic's BaseModel.model_validate()
    # to be contemplated if it wouldn't be preferrable to do this kind of validation in the pipeline itself before returning the attr obejct
    return PaZuFaVorgang.from_dict(span.outputs["item"])
