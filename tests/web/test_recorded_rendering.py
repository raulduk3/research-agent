from __future__ import annotations

import pytest

from research_agent.web.rendering import (
    AUTOMATED_OUTPUT_NOTICE,
    FieldRewriteError,
    MissingOutputLabelError,
    ReadingWithheldError,
    RecordedField,
    RecordedFieldRenderer,
    SummarizerReading,
)


def test_recorded_field_renders_hostile_html_and_unicode_verbatim_escaped() -> None:
    renderer = RecordedFieldRenderer()
    hostile = "<script>alert(1)</script> — “résumé” 実験"
    field = RecordedField(
        record_id="a" * 64,
        field_name="rationale",
        value=hostile,
        stored_value=hostile,
    )
    rendered = renderer.render_field(field)
    assert "<script>" not in rendered
    assert "résumé" in rendered
    assert "実験" in rendered


def test_recorded_field_rejects_a_value_that_is_not_the_record_value() -> None:
    renderer = RecordedFieldRenderer()
    field = RecordedField(
        record_id="a" * 64,
        field_name="rationale",
        value="a rewritten finding",
        stored_value="the original recorded text",
    )
    with pytest.raises(FieldRewriteError):
        renderer.render_field(field)


def test_summarizer_reading_renders_when_labeled_and_sourced() -> None:
    renderer = RecordedFieldRenderer()
    reading = SummarizerReading(
        record_id="b" * 64,
        text="a sourced summary",
        input_hashes=("c" * 64,),
        label=AUTOMATED_OUTPUT_NOTICE,
    )
    assert renderer.render_reading(reading) == "a sourced summary"


def test_summarizer_reading_is_withheld_without_input_hashes() -> None:
    renderer = RecordedFieldRenderer()
    reading = SummarizerReading(
        record_id="b" * 64,
        text="a sourced summary",
        input_hashes=(),
        label=AUTOMATED_OUTPUT_NOTICE,
    )
    with pytest.raises(ReadingWithheldError):
        renderer.render_reading(reading)


def test_summarizer_reading_is_withheld_without_the_output_label() -> None:
    renderer = RecordedFieldRenderer()
    reading = SummarizerReading(
        record_id="b" * 64,
        text="a sourced summary",
        input_hashes=("c" * 64,),
        label="not the fixed notice",
    )
    with pytest.raises(MissingOutputLabelError):
        renderer.render_reading(reading)
