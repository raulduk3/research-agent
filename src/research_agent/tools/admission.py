"""Strict admission of an untrusted tool call against its run (SR-05, TDD-2.1.5).

Every tool call is agent output and is treated as an untrusted proposal:
before any read runs, :func:`admit_request` checks the call against the
run's own stored specification -- never against a field the call supplies
-- and either admits it with its strictly parsed arguments or refuses it
whole with a stable code. The shared tool service records either decision
in the run's external trace before it executes anything (TDD-2.1.2).

Refusal codes:

- ``tool_not_allowed``: a name outside the fixed five, one the service has
  no handler for, or one the run's own configuration narrowed away (AG-14).
- ``run_not_active``: the run already ended, submitted or void (AG-15).
- ``invalid_input``: a call naming another snapshot (AG-10), a note and
  intent envelope that is malformed, a note missing or over its bound, or
  an intent outside the fixed list (AG-39), arguments that fail their
  strict schema (AG-11), or a submit naming another paper or an uneven
  question set (AG-26).

What the model sends is the ``{note, intent, arguments}`` envelope, not bare
arguments. The envelope is checked after the snapshot gate and before the
tool's own arguments are parsed, so a call refused for its envelope has no
domain argument read.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..contracts.primitives import ContractValidationError
from ..contracts.tools import TOOL_NAMES, ToolRequest, call_envelope
from .snapshot import RunLookup, authorize_snapshot
from .submit import authorize_submit_scope

__all__ = ["Admission", "Refusal", "admit_request"]


@dataclass(frozen=True, slots=True)
class Admission:
    """An admitted call: its tool, parsed arguments and the run's snapshot."""

    tool: str
    arguments: Mapping[str, Any]
    snapshot_hash: str


@dataclass(frozen=True, slots=True)
class Refusal:
    """A call refused whole, with the code its trace entry records."""

    code: str
    message: str


def admit_request(
    *,
    tool: str,
    raw_call: object,
    run_id: str,
    requested_snapshot_id: str,
    lookup: RunLookup,
    handlers: frozenset[str],
    active: bool = True,
) -> Admission | Refusal:
    """Admit *tool* with the envelope *raw_call* for *run_id*, or refuse it.

    The tool's name is checked first, so an unknown or narrowed-away tool
    is refused without a snapshot lookup; *active* is the run's stored
    state, and a run that has ended admits nothing further.
    """

    if tool not in TOOL_NAMES or tool not in handlers:
        return Refusal("tool_not_allowed", "tool is not admitted")
    try:
        if tool not in lookup.allowed_tools_for(run_id):
            return Refusal("tool_not_allowed", "tool is not in this run's admitted set")
        if not active:
            return Refusal("run_not_active", "the run has already ended")
        snapshot_hash = authorize_snapshot(lookup, run_id, requested_snapshot_id)
        _note, _intent, raw_arguments = call_envelope(raw_call)
        request = ToolRequest.parse(tool, raw_arguments)
        if tool == "submit":
            authorize_submit_scope(
                request.arguments,
                paper_id=lookup.paper_id_for(run_id),
                issued_question_ids=lookup.issued_question_ids_for(run_id),
            )
    except ContractValidationError as error:
        return Refusal("invalid_input", str(error))
    return Admission(tool, request.arguments, snapshot_hash)
