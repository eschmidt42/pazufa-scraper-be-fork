from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any, Protocol, cast
from unittest.mock import MagicMock, Mock

import pytest
from scrapy.exceptions import DropItem

from pazufa_scraper_be.tracing import trace_pipeline

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


class _TracedPipeline(Protocol):
    process_item: Callable[..., Coroutine[Any, Any, object]]


class _FakeMlflow(ModuleType):
    start_span: Mock
    set_tracking_uri: Mock
    set_experiment: Mock
    search_traces: Mock


def _install_mlflow(monkeypatch: pytest.MonkeyPatch) -> tuple[_FakeMlflow, Mock, MagicMock]:
    mlflow = _FakeMlflow("mlflow")
    span = MagicMock()
    span_context = MagicMock()
    span_context.__enter__.return_value = span
    start_span = Mock(return_value=span_context)
    mlflow.start_span = start_span
    monkeypatch.setitem(sys.modules, "mlflow", mlflow)
    return mlflow, start_span, span


async def _call_traced_pipeline(pipeline: object, *args: object) -> object:
    return await cast("_TracedPipeline", pipeline).process_item(*args)


def test_snapshot_prefers_model_dump() -> None:
    """Prefer the JSON model dump when available."""

    class Model:
        def model_dump(self, *, mode: str) -> dict[str, str]:
            return {"mode": mode}

        def to_dict(self) -> dict[str, str]:
            return {"source": "to_dict"}

    assert trace_pipeline.snapshot(Model()) == {"mode": "json"}


def test_snapshot_uses_to_dict_when_model_dump_is_unavailable() -> None:
    """Use an item's dictionary conversion method as a fallback."""

    class Item:
        def to_dict(self) -> dict[str, str]:
            return {"source": "to_dict"}

    assert trace_pipeline.snapshot(Item()) == {"source": "to_dict"}


def test_snapshot_deep_copies_other_objects() -> None:
    """Deep-copy objects without a serialization method."""
    item = {"nested": ["value"]}

    result = trace_pipeline.snapshot(item)

    assert result == item
    assert result is not item
    assert isinstance(result, dict)
    assert result["nested"] is not item["nested"]


def test_trace_pipeline_records_sync_success_and_returns_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """Trace a synchronous pipeline and preserve its return value and arguments."""
    _, start_span, span = _install_mlflow(monkeypatch)
    calls: list[tuple[object, str]] = []
    item = {"id": "item-1"}
    result = {"id": "result-1"}

    class Pipeline:
        def process_item(self, received: object, marker: str) -> dict[str, str]:
            calls.append((received, marker))
            return result

    trace_pipeline.trace_pipeline(Pipeline)

    actual = asyncio.run(_call_traced_pipeline(Pipeline(), item, "passed-through"))

    assert actual is result
    assert calls == [(item, "passed-through")]
    start_span.assert_called_once_with(name="Pipeline")
    span.set_inputs.assert_called_once_with({"item": item})
    span.set_outputs.assert_called_once_with({"item": result, "outcome": "passed"})


def test_trace_pipeline_awaits_async_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Await and trace an asynchronous pipeline result."""
    _, _, span = _install_mlflow(monkeypatch)
    calls: list[object] = []
    item = {"id": "item-1"}
    result = {"id": "result-1"}

    class Pipeline:
        async def process_item(self, received: object) -> dict[str, str]:
            calls.append(received)
            return result

    trace_pipeline.trace_pipeline(Pipeline)

    actual = asyncio.run(_call_traced_pipeline(Pipeline(), item))

    assert actual is result
    assert calls == [item]
    span.set_outputs.assert_called_once_with({"item": result, "outcome": "passed"})


@pytest.mark.parametrize(
    ("exception", "outcome", "error"),
    [
        (DropItem("filtered"), "dropped", "filtered"),
        (ValueError("broken"), "error", "ValueError('broken')"),
    ],
)
def test_trace_pipeline_records_and_reraises_errors(
    monkeypatch: pytest.MonkeyPatch,
    exception: Exception,
    outcome: str,
    error: str,
) -> None:
    """Record the appropriate failure outcome and re-raise the pipeline exception."""
    _, _, span = _install_mlflow(monkeypatch)

    class Pipeline:
        def process_item(self, _item: object) -> object:
            raise exception

    trace_pipeline.trace_pipeline(Pipeline)

    with pytest.raises(type(exception)) as caught:
        asyncio.run(_call_traced_pipeline(Pipeline(), {"id": "item-1"}))

    assert caught.value is exception
    span.set_outputs.assert_called_once_with({"error": error, "outcome": outcome})


def test_trace_pipeline_does_not_wrap_the_same_pipeline_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid duplicate spans and original method calls when wrapping repeatedly."""
    _, start_span, _ = _install_mlflow(monkeypatch)
    calls: list[object] = []

    class Pipeline:
        def process_item(self, item: object) -> object:
            calls.append(item)
            return item

    trace_pipeline.trace_pipeline(Pipeline)
    trace_pipeline.trace_pipeline(Pipeline)

    asyncio.run(_call_traced_pipeline(Pipeline(), {"id": "item-1"}))

    assert len(calls) == 1
    start_span.assert_called_once_with(name="Pipeline")


def test_get_trace_from_mlflow_db_maps_sorted_pipeline_spans(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sort pipeline spans and map each outcome and duration to a trace event."""
    mlflow, _, _ = _install_mlflow(monkeypatch)
    passed = SimpleNamespace(
        name="PassedPipeline",
        start_time_ns=2_000_000,
        end_time_ns=3_234_567,
        inputs={"item": {"id": "before"}},
        outputs={"item": {"id": "after"}, "outcome": "passed"},
    )
    dropped = SimpleNamespace(
        name="DroppedPipeline",
        start_time_ns=4_000_000,
        end_time_ns=4_987_654,
        inputs={"item": {"id": "dropped"}},
        outputs={"error": "filtered", "outcome": "dropped"},
    )
    errored = SimpleNamespace(
        name="ErrorPipeline",
        start_time_ns=5_000_000,
        end_time_ns=7_000_000,
        inputs={"item": {"id": "error"}},
        outputs={"error": "failed", "outcome": "error"},
    )
    root = SimpleNamespace(name="crawl", start_time_ns=0, end_time_ns=8_000_000, inputs={}, outputs={})
    set_tracking_uri = Mock()
    set_experiment = Mock()
    search_traces = Mock(return_value=[SimpleNamespace(data=SimpleNamespace(spans=[errored, root, dropped, passed]))])
    mlflow.set_tracking_uri = set_tracking_uri
    mlflow.set_experiment = set_experiment
    mlflow.search_traces = search_traces

    result = trace_pipeline.get_trace_from_mlflow_db(
        span_name="crawl",
        tracking_uri="http://tracking",
        experiment="test-experiment",
    )

    assert result == [
        {
            "stage": "PassedPipeline",
            "ms": 1.2,
            "before": {"id": "before"},
            "outcome": trace_pipeline.OutcomesEnum.passed,
            "after": {"id": "after"},
        },
        {
            "stage": "DroppedPipeline",
            "ms": 1.0,
            "before": {"id": "dropped"},
            "outcome": trace_pipeline.OutcomesEnum.dropped,
            "error": "filtered",
        },
        {
            "stage": "ErrorPipeline",
            "ms": 2.0,
            "before": {"id": "error"},
            "outcome": trace_pipeline.OutcomesEnum.error,
            "error": "failed",
        },
    ]
    set_tracking_uri.assert_called_once_with("http://tracking")
    set_experiment.assert_called_once_with("test-experiment")
    search_traces.assert_called_once_with(
        filter_string="span.name = 'crawl'",
        order_by=["timestamp_ms DESC"],
        max_results=1,
        return_type="list",
    )


def test_get_trace_from_mlflow_db_raises_when_no_matching_trace_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    """Raise a clear lookup error when MLflow returns no traces."""
    mlflow, _, _ = _install_mlflow(monkeypatch)
    set_tracking_uri = Mock()
    set_experiment = Mock()
    search_traces = Mock(return_value=[])
    mlflow.set_tracking_uri = set_tracking_uri
    mlflow.set_experiment = set_experiment
    mlflow.search_traces = search_traces

    with pytest.raises(LookupError, match="No 'crawl' trace found"):
        trace_pipeline.get_trace_from_mlflow_db(span_name="crawl")
