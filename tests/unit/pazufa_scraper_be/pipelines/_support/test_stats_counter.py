import pytest

from pazufa_scraper_be.pipelines._support.stats_counter import LLMCounter


@pytest.mark.parametrize(
    ("art", "expected"),
    [
        ("plpr", "PaZuFa/LLM/summarize/plpr"),
        ("drs", "PaZuFa/LLM/summarize/drs"),
        ("gvbl", "PaZuFa/LLM/summarize/gvbl"),
        ("", "PaZuFa/LLM/summarize/"),
    ],
)
def test_llm_counter_summarize_art(art: str, expected: str) -> None:
    """summarize_art returns the correct counter name for the given document art."""
    assert LLMCounter.summarize_art(art) == expected
