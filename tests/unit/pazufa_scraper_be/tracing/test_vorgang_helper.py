from pathlib import Path
from typing import Any

from pydantic import ValidationError

from pazufa_scraper_be.pardok.vorgang import GesetzVorgang
from pazufa_scraper_be.tracing.vorgang_helper import feed_to_gesetz_vorgang_dicts, validate_vorgang


def test_feed_to_gesetz_vorgang_dicts_selects_only_gesetz_entries(tmp_path: Path) -> None:
    """Convert only Gesetz entries from the XML feed."""
    feed = tmp_path / "feed.xml"
    feed.write_text(
        """\
<Export>
  <Vorgang><VTyp>Gesetz</VTyp><VID>gesetz-1</VID></Vorgang>
  <Vorgang><VTyp>Anfrage</VTyp><VID>anfrage-1</VID></Vorgang>
  <Vorgang><VTyp>Gesetz</VTyp><VID>gesetz-2</VID></Vorgang>
</Export>
""",
        encoding="utf-8",
    )

    assert feed_to_gesetz_vorgang_dicts(feed) == [
        {"VTyp": "Gesetz", "VID": "gesetz-1"},
        {"VTyp": "Gesetz", "VID": "gesetz-2"},
    ]


def test_validate_vorgang_returns_model(base_vorgang_data: dict[str, Any]) -> None:
    """Return a GesetzVorgang when the input is valid."""
    result = validate_vorgang(base_vorgang_data)

    assert isinstance(result, GesetzVorgang)
    assert result.id == "vorg123"


def test_validate_vorgang_returns_input_and_error_for_invalid_data(base_vorgang_data: dict[str, Any]) -> None:
    """Return the input and validation error when the input is invalid."""
    invalid_data = {**base_vorgang_data, "ReihNr": 1}

    result = validate_vorgang(invalid_data)

    assert isinstance(result, dict)
    assert result["dict"] == invalid_data
    assert isinstance(result["error"], ValidationError)
