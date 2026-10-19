# ruff: noqa: INP001

import difflib
import json
from collections.abc import Sequence
from html import escape
from typing import Literal, NotRequired, TypedDict

import ipywidgets as widgets


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


def _render_diff(before: str, after: str) -> str:
    lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile="before",
            tofile="after",
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
