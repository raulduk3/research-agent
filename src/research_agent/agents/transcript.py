"""Durable, ordered recording of a run's model exchanges and image deliveries (AG-29, AG-30)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.primitives import validate_sha256

EVENT_KINDS = ("request", "response")


class RecordingFailed(Exception):
    """Raised by a :class:`RunEventSink` when an exchange cannot be committed.

    The loop treats this as an infrastructure failure: it stops rather
    than sending a request whose predecessor was not durably recorded, or
    dispatching a tool call whose response was not (AG-29).
    """


class RunEventSink(Protocol):
    """Where a run's ordered request/response events are durably appended.

    A concrete sink commits ``payload`` before returning normally, or
    raises :class:`RecordingFailed`; it never appends out of order.
    """

    def append(
        self, *, run_id: str, attempt: int, ordinal: int, kind: str, payload: bytes
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ExchangeRecord:
    """The identity of one committed request or response event."""

    ordinal: int
    kind: str
    payload_hash: str


def record_exchange(
    sink: RunEventSink,
    *,
    run_id: str,
    attempt: int,
    ordinal: int,
    kind: str,
    payload: bytes,
) -> ExchangeRecord:
    """Append one request or response event, by hash and in order (AG-29).

    Called with the exact bytes sent to, or received from, the agent
    model: a request is recorded before the network send, a response
    after receipt and before any tool dispatch. Raises
    :class:`RecordingFailed` when the sink cannot commit the event, which
    the caller treats as ending the run void.
    """

    if kind not in EVENT_KINDS:
        raise ValueError(f"kind must be one of {EVENT_KINDS}")
    sink.append(
        run_id=run_id, attempt=attempt, ordinal=ordinal, kind=kind, payload=payload
    )
    return ExchangeRecord(ordinal, kind, sha256_hex(payload))


@dataclass(frozen=True, slots=True)
class ImageDelivery:
    """One image's ordered delivery-manifest entry (AG-30, TDD-3.1.63)."""

    tool_call_id: str
    paper_id: str
    figure_id: str
    rendered_artifact_hash: str

    def __post_init__(self) -> None:
        if not self.tool_call_id or not self.paper_id or not self.figure_id:
            raise ValueError("tool_call_id, paper_id and figure_id must be nonempty")
        validate_sha256(self.rendered_artifact_hash)

    def to_dict(self) -> dict[str, str]:
        return {
            "tool_call_id": self.tool_call_id,
            "paper_id": self.paper_id,
            "figure_id": self.figure_id,
            "rendered_artifact_hash": self.rendered_artifact_hash,
        }


class ImageManifestSink(Protocol):
    """Where a run's image-delivery manifests are durably committed.

    Distinct from :class:`RunEventSink`: an image manifest is not a model
    request or response, it names the images one tool response carries.
    """

    def commit(self, *, run_id: str, tool_call_id: str, payload: bytes) -> None: ...


def record_images(
    sink: ImageManifestSink,
    *,
    run_id: str,
    tool_call_id: str,
    deliveries: Sequence[ImageDelivery],
) -> str:
    """Commit the ordered image-delivery manifest before attaching image blocks.

    The run's record names every image a deep_read response carries, in
    the order sent (AG-30). Raises :class:`RecordingFailed` when the sink
    cannot commit the manifest; the caller withholds the images from the
    response it returns to the agent model rather than sending unaccounted
    pixels. Returns the manifest's content hash.
    """

    if not deliveries:
        raise ValueError("record_images requires at least one delivery")
    payload = canonical_json([delivery.to_dict() for delivery in deliveries])
    sink.commit(run_id=run_id, tool_call_id=tool_call_id, payload=payload)
    return sha256_hex(payload)
