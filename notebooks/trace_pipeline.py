# ruff: noqa: INP001

import inspect
from collections.abc import Awaitable, Callable
from copy import deepcopy
from functools import wraps
from time import perf_counter
from typing import Literal, TypedDict, cast

from scrapy.exceptions import DropItem


class _TraceBase(TypedDict):
    stage: str
    ms: float
    before: object


class _DroppedTrace(_TraceBase):
    outcome: Literal["dropped"]
    error: str


class _ErrorTrace(_TraceBase):
    outcome: Literal["error"]
    error: str


class _PassedTrace(_TraceBase):
    outcome: Literal["passed"]
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


def trace_pipeline(pipeline_cls: type[object], use_mlflow: bool) -> None:  # noqa: C901, FBT001
    """Wrap a pipeline's item processor and record each outcome."""
    original = cast("_ProcessItem", getattr(pipeline_cls, "process_item"))  # noqa: B009

    # Avoid wrapping the wrapper if you rerun this cell.
    if getattr(original, "_trace_wrapper", False):
        return

    if use_mlflow:
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
                    span.set_outputs({"error": str(exc), "outcome": "dropped"})
                except Exception as exc:  # noqa: BLE001
                    span.set_outputs({"error": repr(exc), "outcome": "error"})
                else:
                    span.set_outputs({"item": snapshot(result), "outcome": "passed"})
                    return result
    else:

        @wraps(original)
        async def traced(self: object, item: object, *args: object, **kwargs: object) -> object:
            before = snapshot(item)
            started = perf_counter()

            try:
                result = original(self, item, *args, **kwargs)

                if inspect.isawaitable(result):
                    result = await cast("Awaitable[object]", result)

            except DropItem as exc:
                trace.append(
                    {
                        "stage": pipeline_cls.__name__,
                        "ms": round((perf_counter() - started) * 1000, 1),
                        "outcome": "dropped",
                        "before": before,
                        "error": str(exc),
                    }
                )
                raise
            except Exception as exc:
                trace.append(
                    {
                        "stage": pipeline_cls.__name__,
                        "ms": round((perf_counter() - started) * 1000, 1),
                        "outcome": "error",
                        "before": before,
                        "error": repr(exc),
                    }
                )
                raise
            else:
                trace.append(
                    {
                        "stage": pipeline_cls.__name__,
                        "ms": round((perf_counter() - started) * 1000, 1),
                        "outcome": "passed",
                        "before": before,
                        "after": snapshot(result),
                    }
                )
                return result

    setattr(traced, "_trace_wrapper", True)  # noqa: B010
    setattr(pipeline_cls, "process_item", traced)  # noqa: B010


def get_trace_from_mlflow_db(span_name: str = "single-item crawl") -> list[_TraceEvent]:
    """Constructs a list of trace events using the mlflow db."""
    import mlflow  # noqa: PLC0415

    mlflow.set_tracking_uri("http://127.0.0.1:5000")
    mlflow.set_experiment("item-pipelines-nb")

    matches = mlflow.search_traces(
        filter_string=f"span.name = '{span_name}'",
        order_by=["timestamp_ms DESC"],
        max_results=1,
        return_type="list",
    )

    if not matches:
        msg = f"No '{span_name}' trace found."
        raise LookupError(msg)

    trace = matches[0]

    events: list[_TraceEvent] = []

    for span in sorted(trace.data.spans, key=lambda s: s.start_time_ns):
        if span.name == span_name:  # Skip the root crawl span.
            continue

        inputs = span.inputs or {}
        outputs = span.outputs or {}
        before = inputs["item"]
        ms = round((span.end_time_ns - span.start_time_ns) / 1_000_000, 1)

        if outputs.get("outcome") == "dropped":
            events.append(
                {
                    "stage": span.name,
                    "ms": ms,
                    "before": before,
                    "outcome": "dropped",
                    "error": outputs["error"],
                }
            )
        elif outputs.get("outcome") == "error":
            events.append(
                {
                    "stage": span.name,
                    "ms": ms,
                    "before": before,
                    "outcome": "error",
                    "error": outputs["error"],
                }
            )
        else:
            events.append(
                {
                    "stage": span.name,
                    "ms": ms,
                    "before": before,
                    "outcome": "passed",
                    "after": outputs["item"],
                }
            )

    return events
