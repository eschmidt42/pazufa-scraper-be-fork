from typing import Literal, NotRequired, TypedDict

import pytest

pytest.importorskip("ipywidgest", reason="trace viewer tests require local_dev dependencies")
pytest.importorskip("mlflow", reason="render_pipeline imports MLflow types")

from ipywidgets import HTML, Dropdown, HBox, VBox

from pazufa_scraper_be.tracing.render_pipeline import _two_trace_value_viewer


class _PassedStep(TypedDict):
    stage: str
    ms: float
    before: object
    outcome: Literal["passed"]
    after: object


class _FailedStep(TypedDict):
    stage: str
    ms: float
    before: object
    outcome: Literal["dropped", "error"]
    error: NotRequired[str]


def _passed_step(stage: str, before: object, after: object) -> _PassedStep:
    return {
        "stage": stage,
        "ms": 1.0,
        "before": before,
        "outcome": "passed",
        "after": after,
    }


def _failed_step(stage: str, before: object, error: str) -> _FailedStep:
    return {
        "stage": stage,
        "ms": 1.0,
        "before": before,
        "outcome": "error",
        "error": error,
    }


def _parts(viewer: VBox) -> tuple[Dropdown, HTML, HTML, HTML]:
    controls = viewer.children[0]
    panels = viewer.children[2]
    assert isinstance(controls, HBox)
    assert isinstance(panels, HBox)
    picker = controls.children[1]
    reference_view, test_run_view, diff_view = panels.children
    assert isinstance(picker, Dropdown)
    assert isinstance(reference_view, HTML)
    assert isinstance(test_run_view, HTML)
    assert isinstance(diff_view, HTML)
    return picker, reference_view, test_run_view, diff_view


def test_two_trace_value_viewer_renders_values_and_highlights_reference_to_test_diff() -> None:
    """Render the selected value from each trace with a highlighted direct diff."""
    reference_steps = [_passed_step("Build", {"value": "reference-input"}, {"value": "reference-output"})]
    test_run_steps = [_passed_step("Build", {"value": "test-input"}, {"value": "test-output"})]

    input_viewer = _two_trace_value_viewer(
        reference_steps,
        test_run_steps,
        compared_value="input",
        reference_label="Reference",
        test_run_label="Test run",
    )
    output_viewer = _two_trace_value_viewer(
        reference_steps,
        test_run_steps,
        compared_value="output",
        reference_label="Reference",
        test_run_label="Test run",
    )

    input_picker, reference_input, test_run_input, input_diff = _parts(input_viewer)
    output_picker, reference_output, test_run_output, output_diff = _parts(output_viewer)
    assert len(input_picker.options) == 1
    assert len(output_picker.options) == 1
    assert "reference-input" in reference_input.value
    assert "test-input" in test_run_input.value
    assert "reference-input" in input_diff.value
    assert "test-input" in input_diff.value
    assert "background:#fee" in input_diff.value
    assert "background:#e7f6e7" in input_diff.value
    assert "reference-output" in reference_output.value
    assert "test-output" in test_run_output.value
    assert "reference-output" in output_diff.value
    assert "test-output" in output_diff.value


def test_output_viewer_explains_missing_output() -> None:
    """Show the failure reason when a pipeline stage did not produce an output."""
    viewer = _two_trace_value_viewer(
        [_passed_step("Build", {"value": "input"}, {"value": "result"})],
        [_failed_step("Build", {"value": "input"}, "pipeline failed")],
        compared_value="output",
        reference_label="Reference",
        test_run_label="Test run",
    )

    _, _, test_run_output, diff = _parts(viewer)

    assert "No output (error)." in test_run_output.value
    assert "pipeline failed" in test_run_output.value
    assert "No output (error)." in diff.value


def test_input_and_output_viewers_align_stages_and_navigate_independently() -> None:
    """Keep unmatched stages explicit and selectors independent between viewers."""
    reference_steps = [
        _passed_step("Prepare", {"value": "before"}, {"value": "prepared"}),
        _passed_step("Extract", {"value": "prepared"}, {"value": "extracted"}),
    ]
    test_run_steps = [_passed_step("Prepare", {"value": "before"}, {"value": "prepared"})]
    input_viewer = _two_trace_value_viewer(
        reference_steps,
        test_run_steps,
        compared_value="input",
        reference_label="Reference",
        test_run_label="Test run",
    )
    output_viewer = _two_trace_value_viewer(
        reference_steps,
        test_run_steps,
        compared_value="output",
        reference_label="Reference",
        test_run_label="Test run",
    )
    input_picker, _, test_run_input, _ = _parts(input_viewer)
    output_picker, _, _, _ = _parts(output_viewer)
    assert len(input_picker.options) == 2
    assert len(output_picker.options) == 2

    input_picker.value = 1

    assert output_picker.value == 0
    assert "not present in this trace" in test_run_input.value
