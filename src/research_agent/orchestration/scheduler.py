"""The island's daily coverage sample and its slot dispatch order (AG-05, TDD-3.1.41).

``draw_coverage_sample`` is the part of AG-05 decision 0022 changed: per
island per day, the papers every genome of that island reads are the
largest hash-ordered prefix the island's remaining authorized spend covers
at the measured per-run cost, with the draw's seed and the resulting
coverage recorded for audit. ``order_queue`` and ``schedule_slots`` cover
the rest of AG-05's dispatch discipline -- earliest-deadline-first
ordering and a deadline-aware run -- at the level this repository can
build today: the durable fenced leases and operator-owned container
launcher TDD-3.1.41 also describes belong to the platform layer PL-01
(worker image, #74) and PL-15/PL-16 (checkpointed leases, #65) build;
``dispatch`` here is an injected collaborator a caller backs with that
infrastructure once it exists, and ``max_concurrent`` is the policy this
module enforces on the queue it hands that collaborator, not a guarantee
about worker processes actually running in parallel.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal
from uuid import UUID

from research_agent.contracts.canonical import canonical_json
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_negative_int,
    validate_positive_int,
    validate_sha256,
    validate_utc_instant,
)
from research_agent.orchestration.slots import Slot
from research_agent.platform.resources import LeaseState, ResourcePolicy
from research_agent.storage.jobs import FOREGROUND_JOB_KINDS, HEAVY_JOB_KINDS

#: The three islands AG-36 admits.
ISLANDS = frozenset({"cs", "quant-ph", "q-bio"})

SlotOutcome = Literal["completed", "void", "missed_deadline"]


@dataclass(frozen=True, slots=True)
class CoverageSample:
    """One island's daily coverage sample and its audit trail (AG-05).

    ``sampled_family_ids`` is the identical sample every genome of the
    island reads that day; ``excluded_family_ids`` keeps their cards and
    prediction-head probabilities but receives no agent forecast.
    """

    island: str
    seed: int
    sampled_family_ids: tuple[str, ...]
    excluded_family_ids: tuple[str, ...]

    @property
    def coverage(self) -> int:
        """The reported count of papers this island's genomes read today."""

        return len(self.sampled_family_ids)


def _draw_key(batch_id: str, island: str, family_id: str, seed: int) -> str:
    payload = canonical_json(
        {"batch_id": batch_id, "island": island, "family_id": family_id, "seed": seed}
    )
    return sha256(payload).hexdigest()


def draw_coverage_sample(
    *,
    batch_id: str,
    island: str,
    family_ids: Sequence[str],
    seed: int,
    remaining_spend_micros: int,
    cost_per_run_micros: int,
) -> CoverageSample:
    """Draw one island's daily coverage sample by ascending hash order.

    Sorts ``family_ids`` by the SHA-256 of the canonical JSON object
    ``{batch_id, island, family_id, seed}`` and takes the largest leading
    prefix ``remaining_spend_micros // cost_per_run_micros`` covers. The
    draw depends on nothing genome-specific, so calling it once per island
    per day -- not once per genome -- already gives every genome of that
    island the identical sample; the result records the seed so the same
    draw can be reproduced and audited.
    """

    validate_sha256(batch_id)
    if island not in ISLANDS:
        raise ContractValidationError("island is not an admitted value")
    validate_non_negative_int(seed)
    validate_non_negative_int(remaining_spend_micros)
    validate_positive_int(cost_per_run_micros)
    if len(set(family_ids)) != len(family_ids):
        raise ContractValidationError("family_ids must be distinct")

    ordered = sorted(
        family_ids, key=lambda family_id: _draw_key(batch_id, island, family_id, seed)
    )
    covered = remaining_spend_micros // cost_per_run_micros
    sampled, excluded = tuple(ordered[:covered]), tuple(ordered[covered:])
    return CoverageSample(island, seed, sampled, excluded)


@dataclass(frozen=True, slots=True)
class QueuedSlot:
    """One slot waiting to run, with the deadline that orders its queue."""

    slot: Slot
    seal_deadline: str

    def __post_init__(self) -> None:
        if not isinstance(self.slot, Slot):
            raise ContractValidationError("slot must be a built Slot")
        validate_utc_instant(self.seal_deadline)


def _slot_sort_key(slot: Slot) -> tuple[str, str, str, int]:
    return (slot.batch_id, slot.paper_id, slot.configuration_id, slot.attempt)


def order_queue(entries: Sequence[QueuedSlot]) -> tuple[QueuedSlot, ...]:
    """Order queued slots by earliest paper seal deadline, then slot id."""

    return tuple(
        sorted(
            entries, key=lambda entry: (entry.seal_deadline, _slot_sort_key(entry.slot))
        )
    )


@dataclass(frozen=True, slots=True)
class SlotResult:
    slot: Slot
    outcome: SlotOutcome


DispatchWorker = Callable[[QueuedSlot], SlotOutcome]
Clock = Callable[[], datetime]


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def schedule_slots(
    entries: Sequence[QueuedSlot],
    *,
    dispatch: DispatchWorker,
    max_concurrent: int = 2,
    clock: Clock = _default_clock,
) -> tuple[SlotResult, ...]:
    """Run every queued slot to a terminal outcome, in deadline order.

    Orders the queue (:func:`order_queue`), then for each entry compares
    the current time against its own seal deadline before ever calling
    *dispatch*: a slot whose deadline has already passed is recorded
    ``missed_deadline`` without dispatching it, exactly as a restarted
    scheduler must not create a retry slot after an ambiguous or expired
    attempt. Every scheduled slot ends with a completion, void or
    missed-deadline record; none is silently dropped. ``max_concurrent``
    bounds how many entries a caller may hand to *dispatch* without
    waiting on an earlier one -- this function itself dispatches strictly
    one at a time, so a caller wiring a real concurrent launcher must
    itself respect the bound this validates.
    """

    if max_concurrent < 1:
        raise ContractValidationError("max_concurrent must be a positive integer")
    results: list[SlotResult] = []
    for entry in order_queue(entries):
        now = clock().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        if now > entry.seal_deadline:
            results.append(SlotResult(entry.slot, "missed_deadline"))
            continue
        results.append(SlotResult(entry.slot, dispatch(entry)))
    return tuple(results)


Lane = Literal["foreground", "heavy"]
Admission = Literal["admitted", "lane_full", "paused"]

_LANE_ROLE = {"foreground": "worker", "heavy": "batch"}


class WorkScheduler:
    """Separate foreground and heavy-job concurrency lanes (PL-12, TDD-2.1.41).

    Foreground job kinds only ever hold a ``worker`` lease and heavy kinds
    only a ``batch`` lease, so a heavy job cannot take a foreground lane and
    each lane's ceiling is the :class:`ResourcePolicy` limit. A pause signal,
    raised when measured foreground memory passes the policy's pause
    threshold and cleared below its resume threshold, stops heavy admission
    only; foreground admission never reads it. The scheduler tracks the leases
    its caller reports; the durable lease itself stays with the job repository.
    """

    def __init__(self, policy: ResourcePolicy | None = None) -> None:
        self._policy = policy or ResourcePolicy()
        self._active: dict[Lane, frozenset[UUID]] = {
            "foreground": frozenset(),
            "heavy": frozenset(),
        }
        self._paused = False

    @staticmethod
    def lane_of(kind: str) -> Lane:
        if kind in FOREGROUND_JOB_KINDS:
            return "foreground"
        if kind in HEAVY_JOB_KINDS:
            return "heavy"
        raise ContractValidationError("job kind is not an admitted value")

    @property
    def heavy_paused(self) -> bool:
        return self._paused

    def observe_foreground_memory(self, resident_gib: float) -> bool:
        """Record measured foreground memory; return whether heavy work is paused."""

        if self._paused:
            self._paused = not self._policy.batch_should_resume(resident_gib)
        else:
            self._paused = self._policy.batch_should_pause(resident_gib)
        return self._paused

    def _state(self) -> LeaseState:
        return LeaseState(
            active_worker_ids=frozenset(map(str, self._active["foreground"])),
            active_batch_ids=frozenset(map(str, self._active["heavy"])),
        )

    def _decide(self, lane: Lane) -> Admission:
        if lane == "heavy" and self._paused:
            return "paused"
        if not self._policy.can_lease(self._state(), _LANE_ROLE[lane]):
            return "lane_full"
        return "admitted"

    def claimable_kinds(self) -> tuple[str, ...]:
        """The job kinds a claim may request now: every kind whose lane is open."""

        kinds: set[str] = set()
        if self._decide("foreground") == "admitted":
            kinds |= FOREGROUND_JOB_KINDS
        if self._decide("heavy") == "admitted":
            kinds |= HEAVY_JOB_KINDS
        return tuple(sorted(kinds))

    def admit(self, job_id: UUID, kind: str) -> Admission:
        """Take a slot in *kind*'s lane for a job the caller has leased."""

        lane = self.lane_of(kind)
        if any(job_id in ids for ids in self._active.values()):
            raise ContractValidationError("job is already admitted")
        decision = self._decide(lane)
        if decision == "admitted":
            self._active[lane] |= {job_id}
        return decision

    def release(self, job_id: UUID) -> None:
        """Free the lane slot of a job that completed, failed or lost its lease."""

        for lane, ids in self._active.items():
            if job_id in ids:
                self._active[lane] = ids - {job_id}
                return
        raise ContractValidationError("job is not admitted")
