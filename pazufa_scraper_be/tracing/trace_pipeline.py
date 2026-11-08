import inspect
from collections.abc import Awaitable, Callable
from copy import deepcopy
from enum import StrEnum, auto
from functools import wraps
from typing import Literal, TypedDict, cast

from mlflow.entities import Trace
from scrapy.exceptions import DropItem


class OutcomesEnum(StrEnum):
    """Pipeline outcome classifications."""

    dropped = auto()
    error = auto()
    passed = auto()


class _TraceBase(TypedDict):
    stage: str
    ms: float
    before: object


class _DroppedTrace(_TraceBase):
    outcome: Literal[OutcomesEnum.dropped]
    error: str


class _ErrorTrace(_TraceBase):
    outcome: Literal[OutcomesEnum.error]
    error: str


class _PassedTrace(_TraceBase):
    outcome: Literal[OutcomesEnum.passed]
    after: object


type _TraceEvent = _DroppedTrace | _ErrorTrace | _PassedTrace
type _ProcessItem = Callable[..., object | Awaitable[object]]
type _SnapshotMethod = Callable[..., object]

trace: list[_TraceEvent] = []


def snapshot(item: object) -> object:
    """Return a copy or serialized representation of an item."""
    if hasattr(item, "model_dump"):
        model_dump = cast("_SnapshotMethod", item.model_dump)
        return model_dump(mode="json")
    if hasattr(item, "to_dict"):
        to_dict = cast("_SnapshotMethod", item.to_dict)
        return to_dict()
    return deepcopy(item)


def trace_pipeline(pipeline_cls: type[object]) -> None:
    """Wrap a pipeline's item processor and record each outcome."""
    original = cast("_ProcessItem", getattr(pipeline_cls, "process_item"))  # noqa: B009

    # Avoid wrapping the wrapper if you rerun this cell.
    if getattr(original, "_trace_wrapper", False):
        return

    import mlflow  # noqa: PLC0415

    @wraps(original)
    async def traced(self: object, item: object, *args: object, **kwargs: object) -> object:
        with mlflow.start_span(name=pipeline_cls.__name__) as span:
            span.set_inputs({"item": snapshot(item)})

            try:
                result = original(self, item, *args, **kwargs)

                if inspect.isawaitable(result):
                    result = await cast("Awaitable[object]", result)
            except DropItem as exc:
                span.set_outputs({"error": str(exc), "outcome": OutcomesEnum.dropped.value})
                raise
            except Exception as exc:
                span.set_outputs({"error": repr(exc), "outcome": OutcomesEnum.error.value})
                raise
            else:
                span.set_outputs({"item": snapshot(result), "outcome": OutcomesEnum.passed.value})
                return result

    setattr(traced, "_trace_wrapper", True)  # noqa: B010
    setattr(pipeline_cls, "process_item", traced)  # noqa: B010


def get_traces_from_mlflow_db(
    *, span_name: str = "single-item crawl", tracking_uri: str = "http://127.0.0.1:5000", experiment: str = "item-pipelines-nb", max_results: int | None = None
) -> list[Trace]:
    """Queries traches from the mlflow db."""
    import mlflow  # noqa: PLC0415

    mlflow.set_tracking_uri(tracking_uri)

    mlflow.set_experiment(experiment)

    traces = mlflow.search_traces(
        filter_string=f"span.name = '{span_name}'",
        order_by=["timestamp_ms DESC"],
        max_results=max_results,
        return_type="list",
    )

    if not traces:
        msg = f"No '{span_name}' trace found."
        raise LookupError(msg)

    return traces


def convert_trace_to_events(span_name: str, trace: Trace) -> list[_TraceEvent]:
    """Converts a trace to a list of events."""
    events: list[_TraceEvent] = []

    for span in sorted(trace.data.spans, key=lambda s: s.start_time_ns):
        if span.name == span_name:  # Skip the root crawl span.
            continue

        inputs = span.inputs or {}
        outputs = span.outputs or {}
        before = inputs["item"]

        if span.end_time_ns is None:
            msg = f"Span {span.name!r} has no end timestamp."
            raise ValueError(msg)

        ms = round((span.end_time_ns - span.start_time_ns) / 1_000_000, 1)

        if outputs.get("outcome") == "dropped":
            events.append(
                {
                    "stage": span.name,
                    "ms": ms,
                    "before": before,
                    "outcome": OutcomesEnum.dropped,
                    "error": outputs["error"],
                }
            )
        elif outputs.get("outcome") == "error":
            events.append(
                {
                    "stage": span.name,
                    "ms": ms,
                    "before": before,
                    "outcome": OutcomesEnum.error,
                    "error": outputs["error"],
                }
            )
        else:
            events.append(
                {
                    "stage": span.name,
                    "ms": ms,
                    "before": before,
                    "outcome": OutcomesEnum.passed,
                    "after": outputs["item"],
                }
            )

    return events


def get_trace_from_mlflow_db(
    *, span_name: str = "single-item crawl", tracking_uri: str = "http://127.0.0.1:5000", experiment: str = "item-pipelines-nb"
) -> list[_TraceEvent]:
    """Constructs a list of trace events using the mlflow db."""
    traces = get_traces_from_mlflow_db(span_name=span_name, tracking_uri=tracking_uri, experiment=experiment, max_results=1)
    trace = traces[0]

    return convert_trace_to_events(span_name, trace)
