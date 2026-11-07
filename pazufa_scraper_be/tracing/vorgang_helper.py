from pathlib import Path

from pydantic import ValidationError
from scrapy.http import XmlResponse

from pazufa_scraper_be.pardok.vorgang import GesetzVorgang
from pazufa_scraper_be.spiders.utils import convert_element_to_dict


def feed_to_gesetz_vorgang_dicts(feed: Path) -> list[dict]:
    """Turn feed into wine, I mean dicts."""
    response = XmlResponse(url=feed.resolve().as_uri(), body=feed.read_bytes(), encoding="utf-8")

    return [convert_element_to_dict(x) for x in response.selector.xpath("/Export/Vorgang[./VTyp[text() = 'Gesetz']]")]


def validate_vorgang(gesetz_vorgang_dict: dict) -> GesetzVorgang | dict:
    """Produce object for an actual Vorgang entry or fail trying."""
    try:
        g = GesetzVorgang.model_validate(gesetz_vorgang_dict)
    except ValidationError as error:
        g = {"dict": gesetz_vorgang_dict, "error": error}

    return g
