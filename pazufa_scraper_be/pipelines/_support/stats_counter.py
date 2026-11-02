from enum import StrEnum
from http import HTTPStatus

PAZUFA = "PaZuFa"

_VORGANG = PAZUFA + "/Vorgang"
_VORGANG_DROP = _VORGANG + "/drop"
_VORGANG_SUBMIT = _VORGANG + "/submit"
_VORGANG_REJECTED = _VORGANG_SUBMIT + "/rejected"


class StatsCounter(StrEnum):
    """Counters tracking the lifecycle of the entire scraping."""


class VorgangCounter(StatsCounter):
    """Counters tracking the lifecycle of a ``GesetzVorgang`` item."""

    TOTAL = _VORGANG + "/total"

    DROP_INCORRECT = _VORGANG_DROP + "/incorrect"
    DROP_OUT_OF_SCOPE = _VORGANG_DROP + "/out_of_scope"
    DROP_NO_DOCUMENTS = _VORGANG_DROP + "/no_documents"
    DROP_NO_STATIONS = _VORGANG_DROP + "/no_stations"

    SUBMIT_ATTEMPT = _VORGANG_SUBMIT + "/attempt"
    SUBMIT_ACCEPTED = _VORGANG_SUBMIT + "/accepted"
    SUBMIT_ERROR = _VORGANG_SUBMIT + "/grace_period_error"
    SUBMIT_REJECTED = _VORGANG_REJECTED

    @staticmethod
    def submit_rejected_code(error: HTTPStatus) -> str:
        """Return the counter name for a dispatch-by-document-type LLM call."""
        return f"{VorgangCounter.SUBMIT_REJECTED}/{error.value}"


_DOK = PAZUFA + "/Dokument"
_DOK_URL = _DOK + "/url"
_DOK_CACHE = _DOK + "/cache"
_DOK_DOWNLOAD = _DOK + "/download"
_DOK_DOWNLOAD_FAILED = _DOK_DOWNLOAD + "/failed"


class DokumentCounter(StatsCounter):
    """Counters for document download and cache operations."""

    MISSING_PRIMARY = _DOK_URL + "/missing_primary"
    RECOVERED_FROM_ADDITIONAL = _DOK_URL + "/recovered_primary_from_additional"
    ADDITIONAL_PRUNED = _DOK_URL + "/pruned_addtional"

    CACHE_HIT = _DOK_CACHE + "/hit"
    CACHE_RESET = _DOK_CACHE + "/reset"
    CACHE_MISS = _DOK_CACHE + "/miss"

    DOWNLOAD_DONE = _DOK_DOWNLOAD + "/done"

    DOWNLOAD_FAILED_INCORRECT_RESPONSE = _DOK_DOWNLOAD_FAILED + "/incorrect_response"
    DOWNLOAD_FAILED_INCORRECT_STATUS = _DOK_DOWNLOAD_FAILED + "/incorrect_status"


_TEXT = PAZUFA + "/Text"
_TEXT_CACHE = _TEXT + "/cache"
_TEXT_EXTRACT = _TEXT + "/extract"
_TEXT_EXTRACT_FAILED = _TEXT_EXTRACT + "/failed"


class TextCounter(StatsCounter):
    """Counters for PDF text extraction operations."""

    CACHE_HIT = _TEXT_CACHE + "/hit"
    CACHE_MISS = _TEXT_CACHE + "/miss"

    EXTRACT_DONE = _TEXT_EXTRACT + "/done"

    EXTRACT_FAILED_EMPTY_TEXT = _TEXT_EXTRACT_FAILED + "/empty_text"
    EXTRACT_FAILED_NOT_PLAIN_TEXT = _TEXT_EXTRACT_FAILED + "/not_plain_text"


_SUMMARY = PAZUFA + "/Summary"
_SUMMARY_CACHE = _SUMMARY + "/cache"


class SummaryCounter(StatsCounter):
    """Counters for LLM summary cache operations."""

    CACHE_HIT = _SUMMARY_CACHE + "/hit"
    CACHE_MISS = _SUMMARY_CACHE + "/miss"
    IGNORE = _SUMMARY + "/ignore"


_LLM = PAZUFA + "/LLM"
_LLM_SUMMARIZE = _LLM + "/summarize"
_LLM_SUMMARIZE_FAILED = _LLM_SUMMARIZE + "/failed"
_LLM_EXTRACT_RELEVANT_SECTION = _LLM + "/extract_relevant_section"


class LLMCounter(StatsCounter):
    """Counters for LLM summarization operations."""

    EXTRACT_RELEVANT_SECTION_TOTAL = _LLM_EXTRACT_RELEVANT_SECTION + "/total"
    EXTRACT_RELEVANT_SECTION_DONE = _LLM_EXTRACT_RELEVANT_SECTION + "/done"
    EXTRACT_RELEVANT_SECTION_FAILED = _LLM_EXTRACT_RELEVANT_SECTION + "/failed"

    SUMMARIZE_TOTAL = _LLM_SUMMARIZE + "/total"
    SUMMARIZE_DONE = _LLM_SUMMARIZE + "/done"

    SUMMARIZE_FAILED_PROVIDER = _LLM_SUMMARIZE_FAILED + "/provider"
    SUMMARIZE_FAILED_APPLICATION = _LLM_SUMMARIZE_FAILED + "/application"
    SUMMARIZE_FAILED_EMPTY_SUMMARY = _LLM_SUMMARIZE_FAILED + "/empty_summary"
    SUMMARIZE_FAILED_NOT_PLAIN_TEXT = _LLM_SUMMARIZE_FAILED + "/not_plain_text"

    @staticmethod
    def summarize_art(art: str) -> str:
        """Return the counter name for a dispatch-by-document-type LLM call."""
        return f"{_LLM_SUMMARIZE}/{art}"
