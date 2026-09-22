import uuid
from dataclasses import replace

import pytest

from research_agent.contracts.canonical import sha256_hex
from research_agent.contracts.primitives import ContractValidationError
from research_agent.contracts.summaries import (
    GenomeReading,
    Reading,
    ReadingRefused,
    build_summarizer_input,
    validate_reading_text,
)
from research_agent.digest.summary import (
    SUMMARIZER_CONTEXT_TOKENS_LIMIT,
    SUMMARIZER_DAILY_SPEND_CAP_MICROS,
    SummarizerBudgetExhausted,
    SummarizerResponse,
    UnsealedClaims,
    write_reading,
)


def _hash(seed: str) -> str:
    return sha256_hex(seed.encode())


GENOME_A = _hash("genome-a")
GENOME_B = _hash("genome-b")
RUN_1 = str(uuid.uuid4())
DIGEST_ENTRY_ID = str(uuid.uuid4())
CREATED_AT = "2026-09-22T00:00:00.000000Z"


def _genome_readings():
    return [
        GenomeReading(
            genome_hash=GENOME_A, probability=0.7, rationale="Cites strong baselines."
        ),
        GenomeReading(
            genome_hash=GENOME_B, probability=0.4, rationale="Limited evaluation scope."
        ),
    ]


class _StubClient:
    def __init__(self, text, *, generated_tokens=20, elapsed_seconds=1.0):
        self.text = text
        self.generated_tokens = generated_tokens
        self.elapsed_seconds = elapsed_seconds
        self.calls = 0

    def complete(self, messages, *, max_generation_tokens):
        self.calls += 1
        return SummarizerResponse(
            text=self.text,
            generated_tokens=self.generated_tokens,
            elapsed_seconds=self.elapsed_seconds,
        )


def _write_reading(**overrides):
    kwargs = dict(
        digest_entry_id=DIGEST_ENTRY_ID,
        claims_sealed=True,
        card_text="A paper about deterministic digests.",
        genome_readings=_genome_readings(),
        protected_notes=["Checked the methods section.", "Compared to related work."],
        contributing_run_ids=[RUN_1],
        client=_StubClient(
            "The agents agreed the method is sound but evidence is thin."
        ),
        system_prompt="Summarize what the agents claimed about this paper.",
        model_provider="zai",
        model_id="glm-5.3-flash",
        model_revision="unpinned",
        context_tokens=100,
        already_read_this_week=False,
        daily_spend_micros_before=0,
        reserved_spend_micros=1,
        created_at=CREATED_AT,
    )
    kwargs.update(overrides)
    return write_reading(**kwargs)


def test_reading_is_stored_with_provenance_and_the_automated_output_label():
    reading = _write_reading()
    assert isinstance(reading, Reading)
    assert reading.digest_entry_id == DIGEST_ENTRY_ID
    assert reading.label == "automated_output"
    assert reading.model_provider == "zai"
    assert reading.model_id == "glm-5.3-flash"
    assert len(reading.prompt_hash) == 64
    assert len(reading.input_hashes) == 1 + len(_genome_readings()) + 2


def test_unsealed_claims_are_refused_before_any_model_call():
    client = _StubClient("anything")
    with pytest.raises(UnsealedClaims):
        _write_reading(claims_sealed=False, client=client)
    assert client.calls == 0


def test_entry_already_read_this_week_is_refused_before_any_model_call():
    client = _StubClient("anything")
    with pytest.raises(SummarizerBudgetExhausted) as excinfo:
        _write_reading(already_read_this_week=True, client=client)
    assert excinfo.value.budget == "weekly_call_limit"
    assert client.calls == 0


def test_conversation_over_the_context_ceiling_is_refused_before_any_model_call():
    client = _StubClient("anything")
    with pytest.raises(SummarizerBudgetExhausted) as excinfo:
        _write_reading(context_tokens=SUMMARIZER_CONTEXT_TOKENS_LIMIT, client=client)
    assert excinfo.value.budget == "context_tokens"
    assert client.calls == 0


def test_reservation_past_the_daily_sublimit_is_refused_before_any_model_call():
    client = _StubClient("anything")
    with pytest.raises(SummarizerBudgetExhausted) as excinfo:
        _write_reading(
            daily_spend_micros_before=SUMMARIZER_DAILY_SPEND_CAP_MICROS,
            reserved_spend_micros=1,
            client=client,
        )
    assert excinfo.value.budget == "daily_spend_micros"
    assert client.calls == 0


def test_reply_over_the_generation_token_ceiling_yields_no_reading():
    client = _StubClient("short reply", generated_tokens=513)
    with pytest.raises(SummarizerBudgetExhausted) as excinfo:
        _write_reading(client=client)
    assert excinfo.value.budget == "generation_tokens"


def test_reply_over_the_timeout_yields_no_reading():
    client = _StubClient("short reply", elapsed_seconds=61)
    with pytest.raises(SummarizerBudgetExhausted) as excinfo:
        _write_reading(client=client)
    assert excinfo.value.budget == "timeout_seconds"


def test_reply_naming_a_genome_hash_is_refused():
    client = _StubClient(f"The genome {GENOME_A} was most confident.")
    with pytest.raises(ReadingRefused):
        _write_reading(client=client)


def test_reply_naming_a_contributing_run_id_is_refused():
    client = _StubClient(f"Run {RUN_1} retrieved the paper.")
    with pytest.raises(ReadingRefused):
        _write_reading(client=client)


@pytest.mark.parametrize("term", ["control", "service", "nomination"])
def test_reply_naming_a_forbidden_word_is_refused(term):
    client = _StubClient(f"This paper was a random {term} pick.")
    with pytest.raises(ReadingRefused):
        _write_reading(client=client)


def test_reply_over_two_hundred_words_is_refused():
    client = _StubClient(" ".join(["word"] * 201))
    with pytest.raises(ReadingRefused):
        _write_reading(client=client)


def test_reply_that_is_not_plain_text_is_refused():
    with pytest.raises(ReadingRefused):
        validate_reading_text(
            {"reading": "not a string"}, forbidden_hashes=[], forbidden_ids=[]
        )


def test_same_inputs_give_the_same_stored_record_shape_regardless_of_genome_order():
    forward = _write_reading(genome_readings=_genome_readings())
    reversed_readings = list(reversed(_genome_readings()))
    backward = _write_reading(genome_readings=reversed_readings)
    assert forward.input_hashes == backward.input_hashes
    assert forward.to_dict() == backward.to_dict()


def test_summarizer_input_excludes_nominations_and_origin_by_construction():
    summarizer_input = build_summarizer_input(
        card_text="card text",
        genome_readings=_genome_readings(),
        protected_notes=["a note"],
    )
    assert set(summarizer_input.to_dict()) == {
        "card_text",
        "genome_readings",
        "protected_notes",
    }


def test_genome_reading_rejects_a_probability_outside_zero_one():
    with pytest.raises(ContractValidationError):
        GenomeReading(genome_hash=GENOME_A, probability=1.5, rationale="text")


def test_genome_reading_rejects_an_oversized_rationale():
    with pytest.raises(ContractValidationError):
        GenomeReading(genome_hash=GENOME_A, probability=0.5, rationale="x" * 2001)


def test_summarizer_input_rejects_duplicate_genome_hashes():
    duplicate = replace(_genome_readings()[0], probability=0.1)
    with pytest.raises(ContractValidationError):
        build_summarizer_input(
            card_text="card text",
            genome_readings=[_genome_readings()[0], duplicate],
            protected_notes=[],
        )


def test_summarizer_input_rejects_an_oversized_protected_note():
    with pytest.raises(ContractValidationError):
        build_summarizer_input(
            card_text="card text",
            genome_readings=_genome_readings(),
            protected_notes=["x" * 1001],
        )


def test_reading_rejects_a_label_other_than_automated_output():
    with pytest.raises(ContractValidationError):
        Reading(
            digest_entry_id=DIGEST_ENTRY_ID,
            text="a short reading",
            label="model_output",
            model_provider="zai",
            model_id="glm-5.3-flash",
            model_revision="unpinned",
            prompt_hash=GENOME_A,
            input_hashes=(GENOME_A,),
            created_at=CREATED_AT,
        )
