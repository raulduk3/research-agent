"""Automated-output framing shared by every rendered digest and report (IN-28)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from markupsafe import escape

from research_agent.contracts.primitives import (
    validate_probability,
    validate_utc_instant,
)

AUTOMATED_OUTPUT_NOTICE: Final[str] = (
    "Automated output. Not a scientific claim authored by any person."
)


class MissingOutputLabelError(ValueError):
    """Raised when a digest or report would publish without its automated-output notice."""


def validate_output_label(notice: object) -> str:
    """Refuse to publish or store output that lacks the fixed automated-output notice.

    Comparing against the one exact, fixed string, rather than checking for
    "some" notice, closes the gap a renderer would open by letting
    model-produced text substitute its own wording and quietly drop the
    disclosure IN-28 requires.
    """
    if notice != AUTOMATED_OUTPUT_NOTICE:
        raise MissingOutputLabelError("output is missing the automated-output notice")
    return AUTOMATED_OUTPUT_NOTICE


def format_dated_prediction(
    *, target: str, sealed_at: object, probability: object
) -> str:
    """Word a forecast as a dated, probabilistic prediction, never a finding."""
    sealed = validate_utc_instant(sealed_at)
    value = validate_probability(probability)
    return f"{target}: {value:.4f} probability, predicted {sealed}"


class FieldRewriteError(ValueError):
    """Raised when a projected field's value is not the record it is pointed at."""


class ReadingWithheldError(ValueError):
    """Raised when a summarizer reading lacks its input hashes or output label."""


@dataclass(frozen=True, slots=True)
class RecordedField:
    """One field a run recorded to the ledger, named by its own record pointer.

    ``value`` is what a caller asks to display; ``stored_value`` is read
    straight from the record ``record_id``/``field_name`` point at. The two
    are compared before rendering so a display layer that drafts or rewrites
    prose for a field, instead of showing the record, is refused (SR-26).
    """

    record_id: str
    field_name: str
    value: str
    stored_value: str


@dataclass(frozen=True, slots=True)
class SummarizerReading:
    """The one model-written field a rater may see: a labeled, sourced reading."""

    record_id: str
    text: str
    input_hashes: tuple[str, ...]
    label: str


class RecordedFieldRenderer:
    """Render recorded ledger fields verbatim, with Jinja-style autoescaping.

    No Markdown execution and no generated prose: a field is either the
    exact recorded value, HTML-escaped for safe display, or it is refused.
    """

    def render_field(self, field: RecordedField) -> str:
        if field.value != field.stored_value:
            raise FieldRewriteError(
                f"{field.field_name} does not match its referenced record value"
            )
        return str(escape(field.value))

    def render_reading(self, reading: SummarizerReading) -> str:
        if not reading.input_hashes:
            raise ReadingWithheldError("reading lacks its input hashes")
        validate_output_label(reading.label)
        return str(escape(reading.text))
