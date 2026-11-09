import difflib
import json
from collections.abc import Sequence
from html import escape
from typing import Literal, NotRequired, TypedDict

import ipywidgets as widgets
from mlflow.entities import Trace

from pazufa_scraper_be.tracing.trace_pipeline import OutcomesEnum, convert_trace_to_events


class _TraceBase(TypedDict):
    stage: str
    ms: float
    before: object


class _PassedTrace(_TraceBase):
    outcome: Literal["passed"]
    after: object


class _FailedTrace(_TraceBase):
    outcome: Literal["dropped", "error"]
    error: NotRequired[str]


type _TraceStep = _PassedTrace | _FailedTrace


class _NoPipelineTraceStepsError(ValueError):
    """Raised when the viewer receives an empty trace."""

    def __init__(self) -> None:
        """Set the message retained by the public ValueError behavior."""
        super().__init__("No pipeline trace steps to display.")


def _as_text(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, default=str)


def _panel(title: str, text: str) -> str:
    return (
        '<div style="border:1px solid #ccc; padding:8px; width:100%;">'
        f"<b>{escape(title)}</b>"
        '<pre style="overflow:auto; max-height:360px; white-space:pre;">'
        f"{escape(text)}</pre></div>"
    )


def _render_diff(before: str, after: str, *, fromfile: str = "before", tofile: str = "after") -> str:
    lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=fromfile,
            tofile=tofile,
            n=2,
            lineterm="",
        )
    )
    if not lines:
        return "<i>No differences.</i>"

    rendered = []
    for line in lines:
        if line.startswith(("---", "+++")):
            style = "color:#666; font-weight:bold;"
        elif line.startswith("-"):
            style = "color:#a11; background:#fee;"
        elif line.startswith("+"):
            style = "color:#174; background:#e7f6e7;"
        elif line.startswith("@@"):
            style = "color:#555; background:#eee;"
        else:
            style = ""
        rendered.append(f'<span style="{style}">{escape(line)}</span>')

    return '<pre style="overflow:auto; max-height:320px; white-space:pre;">' + "\n".join(rendered) + "</pre>"


def _render_step(
    step: _TraceStep,
    index: int,
    count: int,
    views: tuple[widgets.HTML, widgets.HTML, widgets.HTML, widgets.HTML],
) -> None:
    heading, before_view, after_view, diff_view = views
    before = _as_text(step["before"])
    heading.value = f"<b>Step {index + 1}/{count}: {escape(step['stage'])}</b> &nbsp; {escape(step['outcome'])} &nbsp; {step['ms']} ms"
    before_view.value = _panel("Before", before)

    if "after" in step:
        after = _as_text(step["after"])
        after_view.value = _panel("After", after)
        diff_view.value = "<b>Changes</b>" + _render_diff(before, after)
    else:
        message = step.get("error", f"No item returned ({step['outcome']}).")
        after_view.value = _panel("After — no item returned", message)
        diff_view.value = "<i>No after snapshot for this dropped/errored item.</i>"


def pipeline_trace_viewer(steps: Sequence[_TraceStep]) -> widgets.VBox:
    """Create an interactive viewer for the before/after snapshots in a pipeline trace."""
    if not steps:
        raise _NoPipelineTraceStepsError

    picker = widgets.Dropdown(
        options=[(f"{i + 1}. {step['stage']} — {step['outcome']} ({step['ms']} ms)", i) for i, step in enumerate(steps)],
        description="Stage",
        layout=widgets.Layout(width="85%"),
    )
    previous = widgets.Button(description="◀ Previous")
    next_ = widgets.Button(description="Next ▶")
    heading = widgets.HTML()
    before_view = widgets.HTML(layout=widgets.Layout(width="50%"))
    after_view = widgets.HTML(layout=widgets.Layout(width="50%"))
    diff_view = widgets.HTML()

    def render(_change: dict[str, object] | None = None) -> None:
        index = picker.value
        step = steps[index]
        _render_step(step, index, len(steps), (heading, before_view, after_view, diff_view))

        previous.disabled = index == 0
        next_.disabled = index == len(steps) - 1

    previous.on_click(lambda _: setattr(picker, "value", max(0, picker.value - 1)))
    next_.on_click(lambda _: setattr(picker, "value", min(len(steps) - 1, picker.value + 1)))
    picker.observe(render, names="value")

    ui = widgets.VBox(
        [
            widgets.HBox([previous, picker, next_]),
            heading,
            widgets.HBox([before_view, after_view]),
            diff_view,
        ]
    )
    render()
    return ui


type _StageKey = tuple[str, int]
type _ComparedValue = Literal["input", "output"]


def _stage_keys(steps: Sequence[_TraceStep]) -> list[_StageKey]:
    occurrences: dict[str, int] = {}
    keys = []
    for step in steps:
        occurrence = occurrences.get(step["stage"], 0)
        keys.append((step["stage"], occurrence))
        occurrences[step["stage"]] = occurrence + 1
    return keys


def _trace_steps(trace: Trace, span_name: str) -> list[_TraceStep]:
    steps = []
    for step in convert_trace_to_events(span_name, trace):
        if "after" in step:
            passed_step: _PassedTrace = {
                "stage": step["stage"],
                "ms": step["ms"],
                "before": step["before"],
                "outcome": "passed",
                "after": step["after"],
            }
            steps.append(passed_step)
        else:
            outcome = "dropped" if step["outcome"] is OutcomesEnum.dropped else "error"
            failed_step: _FailedTrace = {
                "stage": step["stage"],
                "ms": step["ms"],
                "before": step["before"],
                "outcome": outcome,
                "error": step["error"],
            }
            steps.append(failed_step)
    return steps


def _step_value(step: _TraceStep, compared_value: _ComparedValue) -> str:
    if compared_value == "input":
        return _as_text(step["before"])
    if "after" in step:
        return _as_text(step["after"])

    error = step.get("error")
    message = f"No output ({step['outcome']})."
    return f"{message}\n{error}" if error else message


def _two_trace_value_viewer(
    reference_steps: Sequence[_TraceStep],
    test_run_steps: Sequence[_TraceStep],
    *,
    compared_value: _ComparedValue,
    reference_label: str,
    test_run_label: str,
) -> widgets.VBox:
    reference_keys = _stage_keys(reference_steps)
    test_run_keys = _stage_keys(test_run_steps)
    aligned_keys = reference_keys + [key for key in test_run_keys if key not in reference_keys]
    if not aligned_keys:
        raise _NoPipelineTraceStepsError

    reference_by_key = {key: reference_steps[index] for index, key in enumerate(reference_keys)}
    test_run_by_key = {key: test_run_steps[index] for index, key in enumerate(test_run_keys)}
    value_label = "Input" if compared_value == "input" else "Output"

    options = []
    for index, (stage, occurrence) in enumerate(aligned_keys):
        stage_label = f"{stage} (occurrence {occurrence + 1})" if occurrence else stage
        reference_step = reference_by_key.get((stage, occurrence))
        test_run_step = test_run_by_key.get((stage, occurrence))
        reference_outcome = reference_step["outcome"] if reference_step else "missing"
        test_run_outcome = test_run_step["outcome"] if test_run_step else "missing"
        options.append((f"{index + 1}. {stage_label} — {reference_outcome} / {test_run_outcome}", index))

    picker = widgets.Dropdown(options=options, description="Stage", layout=widgets.Layout(width="85%"))
    previous = widgets.Button(description="◀ Previous")
    next_ = widgets.Button(description="Next ▶")
    stage_heading = widgets.HTML()
    reference_view = widgets.HTML(layout=widgets.Layout(width="33%"))
    test_run_view = widgets.HTML(layout=widgets.Layout(width="33%"))
    diff_view = widgets.HTML(layout=widgets.Layout(width="34%"))

    def render(_change: dict[str, object] | None = None) -> None:
        index = picker.value
        stage, occurrence = aligned_keys[index]
        stage_label = f"{stage} (occurrence {occurrence + 1})" if occurrence else stage
        stage_heading.value = f"<b>{value_label} — Stage {index + 1}/{len(aligned_keys)}: {escape(stage_label)}</b>"

        reference_step = reference_by_key.get((stage, occurrence))
        reference_text = _step_value(reference_step, compared_value) if reference_step else f"Stage {stage_label!r} is not present in this trace."
        test_run_step = test_run_by_key.get((stage, occurrence))
        test_run_text = _step_value(test_run_step, compared_value) if test_run_step else f"Stage {stage_label!r} is not present in this trace."
        reference_view.value = _panel(reference_label, reference_text)
        test_run_view.value = _panel(test_run_label, test_run_text)
        diff_view.value = f"<b>{value_label}: {escape(reference_label)} → {escape(test_run_label)}</b>" + _render_diff(
            reference_text, test_run_text, fromfile=reference_label, tofile=test_run_label
        )

        previous.disabled = index == 0
        next_.disabled = index == len(aligned_keys) - 1

    previous.on_click(lambda _: setattr(picker, "value", max(0, picker.value - 1)))
    next_.on_click(lambda _: setattr(picker, "value", min(len(aligned_keys) - 1, picker.value + 1)))
    picker.observe(render, names="value")

    ui = widgets.VBox(
        [
            widgets.HBox([previous, picker, next_]),
            stage_heading,
            widgets.HBox([reference_view, test_run_view, diff_view]),
        ]
    )
    render()
    return ui


def two_pipeline_trace_inputs_viewer(
    reference_trace: Trace,
    test_run_trace: Trace,
    *,
    span_name: str = "single-item crawl",
    reference_label: str = "Reference",
    test_run_label: str = "Test run",
) -> widgets.VBox:
    """Create a stage-aligned comparison of reference and test-run trace inputs."""
    return _two_trace_value_viewer(
        _trace_steps(reference_trace, span_name),
        _trace_steps(test_run_trace, span_name),
        compared_value="input",
        reference_label=reference_label,
        test_run_label=test_run_label,
    )


def two_pipeline_trace_outputs_viewer(
    reference_trace: Trace,
    test_run_trace: Trace,
    *,
    span_name: str = "single-item crawl",
    reference_label: str = "Reference",
    test_run_label: str = "Test run",
) -> widgets.VBox:
    """Create a stage-aligned comparison of reference and test-run trace outputs."""
    return _two_trace_value_viewer(
        _trace_steps(reference_trace, span_name),
        _trace_steps(test_run_trace, span_name),
        compared_value="output",
        reference_label=reference_label,
        test_run_label=test_run_label,
    )
