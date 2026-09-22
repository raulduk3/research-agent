"""Automated-output framing shared by every rendered digest and report (IN-28)."""

from __future__ import annotations

from typing import Final

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
