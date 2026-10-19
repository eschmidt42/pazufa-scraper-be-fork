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


def trace_pipeline(pipeline_cls: type[object]) -> None:
    """Wrap a pipeline's item processor and record each outcome."""
    original = cast("_ProcessItem", getattr(pipeline_cls, "process_item"))  # noqa: B009

    # Avoid wrapping the wrapper if you rerun this cell.
    if getattr(original, "_trace_wrapper", False):
        return

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
