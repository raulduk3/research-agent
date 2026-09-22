"""submit's own envelope: one optional rationale per claim (AG-40).

A rationale is carried beside a claim, never inside it, so the shared claim
schema :func:`research_agent.contracts.submissions.parse_claims` validates
stays the one schema AG-11 already defines (no second schema). This
rationale is recorded for a person to read and is never sealed to a
forecast or read by the scorer (IN-02); it is distinct from the sealed
forecast rationale of SR-24, which the sealing step records once a claim
is actually sealed under AG-26.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts.primitives import ContractValidationError
from ..contracts.tools import ToolCall, bounded_word_text

__all__ = ["SubmitCall", "parse_submit_call"]

_RATIONALE_MAXIMUM_WORDS = 120


def _rationale(value: object) -> str | None:
    if value is None:
        return None
    return bounded_word_text(value, _RATIONALE_MAXIMUM_WORDS, "rationale")


@dataclass(frozen=True, slots=True)
class SubmitCall:
    """A submit call's envelope with one rationale slot per claim, in the
    same order as ``call.arguments["claims"]``; an absent rationale is
    ``None``, never an empty string."""

    call: ToolCall
    rationales: tuple[str | None, ...]


def parse_submit_call(raw_call: object) -> SubmitCall:
    """Validate *raw_call* as a submit call's ``{note, intent, arguments,
    rationales}`` envelope, or raise ``ContractValidationError``.

    ``rationales`` is stripped before the rest of the envelope reaches
    :meth:`ToolCall.parse`, so the shared claim schema never sees it.
    Requires exactly one rationale slot per claim, in claim order; a slot
    count that does not match the claim count, or a rationale over its
    bound, refuses the whole call and seals nothing.
    """

    if not isinstance(raw_call, dict) or "rationales" not in raw_call:
        raise ContractValidationError("submit call has unknown or missing fields")
    envelope = {key: value for key, value in raw_call.items() if key != "rationales"}
    call = ToolCall.parse("submit", envelope)
    claims = call.arguments["claims"]
    rationales_raw = raw_call["rationales"]
    if not isinstance(rationales_raw, list) or len(rationales_raw) != len(claims):
        raise ContractValidationError(
            "rationales must have exactly one entry per claim"
        )
    rationales = tuple(_rationale(item) for item in rationales_raw)
    return SubmitCall(call=call, rationales=rationales)
