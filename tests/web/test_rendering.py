from __future__ import annotations

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.web.rendering import (
    AUTOMATED_OUTPUT_NOTICE,
    MissingOutputLabelError,
    format_dated_prediction,
    validate_output_label,
)


def test_the_fixed_notice_validates() -> None:
    assert validate_output_label(AUTOMATED_OUTPUT_NOTICE) == AUTOMATED_OUTPUT_NOTICE


def test_a_missing_notice_is_rejected_at_the_publication_boundary() -> None:
    with pytest.raises(MissingOutputLabelError):
        validate_output_label(None)


def test_escaped_model_text_cannot_override_the_notice() -> None:
    forged = AUTOMATED_OUTPUT_NOTICE + "<script>alert(1)</script>"
    with pytest.raises(MissingOutputLabelError):
        validate_output_label(forged)

    authored_override = "This is a finding I am confident in."
    with pytest.raises(MissingOutputLabelError):
        validate_output_label(authored_override)


def test_predictions_are_worded_as_dated_probabilities_not_findings() -> None:
    rendered = format_dated_prediction(
        target="citation_reach_365d",
        sealed_at="2026-01-01T00:00:00.000000Z",
        probability=0.5,
    )
    assert "0.5000" in rendered
    assert "2026-01-01T00:00:00.000000Z" in rendered
    assert "citation_reach_365d" in rendered


def test_predictions_reject_a_probability_outside_zero_to_one() -> None:
    with pytest.raises(ContractValidationError):
        format_dated_prediction(
            target="citation_reach_365d",
            sealed_at="2026-01-01T00:00:00.000000Z",
            probability=1.5,
        )
