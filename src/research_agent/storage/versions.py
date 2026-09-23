"""Retained supersession lineage (SDD-SR-19).

A versioned configuration or decision is an immutable record; replacement
appends a supersession edge from the old hash to the new one with a reason,
a decision id and an effective time, and current choices resolve through
that edge while the old artifact stays addressable for replay. Nothing here
deletes or edits a superseded record in place; `SupersessionChain` refuses a
cycle or a dangling replacement outright.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_sha256,
    validate_utc_instant,
)


@dataclass(frozen=True, slots=True)
class SupersessionRecord:
    """One immutable edge from a superseded hash to the choice that replaced it."""

    old_hash: str
    new_hash: str
    reason: str
    decision_id: str
    effective_at: str

    def __post_init__(self) -> None:
        validate_sha256(self.old_hash)
        validate_sha256(self.new_hash)
        if self.old_hash == self.new_hash:
            raise ContractValidationError("a choice cannot supersede itself")
        validate_non_empty_string(self.reason)
        validate_non_empty_string(self.decision_id)
        validate_utc_instant(self.effective_at)


@dataclass(slots=True)
class SupersessionChain:
    """The retained lineage of every replacement; nothing is ever removed."""

    _edges: dict[str, SupersessionRecord] = field(default_factory=dict)

    def add(self, record: SupersessionRecord) -> None:
        if record.old_hash in self._edges:
            raise ContractValidationError(f"'{record.old_hash}' is already superseded")
        # Walk the new hash forward through existing edges; if that walk ever
        # reaches back to old_hash, this edge would close a cycle rather than
        # extend a lineage.
        cursor = record.new_hash
        seen: set[str] = set()
        while cursor in self._edges:
            if cursor == record.old_hash or cursor in seen:
                raise ContractValidationError("supersession edge would create a cycle")
            seen.add(cursor)
            cursor = self._edges[cursor].new_hash
        if cursor == record.old_hash:
            raise ContractValidationError("supersession edge would create a cycle")
        self._edges[record.old_hash] = record

    def is_superseded(self, choice_hash: str) -> bool:
        return choice_hash in self._edges

    def resolve_current(self, choice_hash: str) -> str:
        """Walk supersession edges to the current, unsuperseded terminal hash."""

        cursor = choice_hash
        seen: set[str] = set()
        while cursor in self._edges:
            if cursor in seen:
                raise ContractValidationError("supersession chain contains a cycle")
            seen.add(cursor)
            cursor = self._edges[cursor].new_hash
        return cursor

    def history_of(self, choice_hash: str) -> tuple[SupersessionRecord, ...]:
        """Every superseding edge starting from *choice_hash*, oldest first."""

        history: list[SupersessionRecord] = []
        cursor = choice_hash
        seen: set[str] = set()
        while cursor in self._edges:
            if cursor in seen:
                raise ContractValidationError("supersession chain contains a cycle")
            seen.add(cursor)
            record = self._edges[cursor]
            history.append(record)
            cursor = record.new_hash
        return tuple(history)
