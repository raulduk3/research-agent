"""Anchor receiver binding and the storage service's anchoring schedule (#325).

`bind_anchor` is the operator's `bind-anchor` step: it sends the committed
ledger head to the receiver once and records the binding only when the
receiver acknowledged that exact head. `AnchorScheduler` runs inside the
storage service: every tick it submits the head when 100 new records or 15
minutes have passed since the last acknowledgement (`is_anchoring_due`), and
a timeout or refusal leaves the acknowledged head where it was.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_agent.contracts.primitives import ContractValidationError
from research_agent.storage.anchors import (
    AnchorBinding,
    AnchorBindingRepository,
    AnchorClient,
    AnchorReceipt,
    AnchorRejected,
    AnchorRequest,
    HttpsAnchorTransport,
    is_anchoring_due,
)

#: How often the storage service asks whether anchoring is due.
TICK_SECONDS = 30.0

_log = logging.getLogger(__name__)


class AnchorBindRefused(RuntimeError):
    """The receiver did not acknowledge the verification round trip."""


@dataclass(frozen=True, slots=True)
class AnchorSettings:
    """The storage configuration's ``anchor`` section: credentials by file reference."""

    profile_id: str
    ca_file: Path
    client_certificate_file: Path | None
    client_private_key_file: Path | None
    bearer_token_file: Path | None
    timeout_seconds: float

    @classmethod
    def from_config(cls, value: dict[str, Any]) -> AnchorSettings:
        profile_id = value.get("profile_id")
        if not isinstance(profile_id, str) or not profile_id:
            raise ValueError("anchor.profile_id must be a nonempty string")
        timeout = value.get("timeout_seconds", 10.0)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("anchor.timeout_seconds must be a number")
        ca_file = _path(value, "ca_file")
        if ca_file is None:
            raise ValueError("anchor.ca_file must be a nonempty string")
        return cls(
            profile_id=profile_id,
            ca_file=ca_file,
            client_certificate_file=_path(value, "client_certificate_file"),
            client_private_key_file=_path(value, "client_private_key_file"),
            bearer_token_file=_path(value, "bearer_token_file"),
            timeout_seconds=float(timeout),
        )

    def transport(self, receiver_url: str) -> HttpsAnchorTransport:
        try:
            return HttpsAnchorTransport(
                receiver_url,
                ca_file=self.ca_file,
                client_certificate_file=self.client_certificate_file,
                client_private_key_file=self.client_private_key_file,
                bearer_token_file=self.bearer_token_file,
                timeout_seconds=self.timeout_seconds,
            )
        except ContractValidationError as error:
            raise ValueError(str(error)) from error


def anchor_request(profile_id: str, sequence: int, record_hash: str) -> AnchorRequest:
    """The request for one head; its key repeats for a retry of the same head."""

    return AnchorRequest(
        sequence=sequence,
        record_hash=record_hash,
        profile_id=profile_id,
        idempotency_key=f"anchor:{profile_id}:{sequence}:{record_hash}",
    )


def bind_anchor(
    bindings: AnchorBindingRepository,
    receiver_url: str,
    transport: Callable[[AnchorRequest], AnchorReceipt],
    *,
    profile_id: str,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> AnchorBinding:
    """Send the committed head once and record the binding on its acknowledgement.

    Nothing is recorded when the receiver times out, refuses, or answers with
    a receipt for a different head.
    """

    sequence, record_hash = bindings.ledger_head()
    try:
        receipt = AnchorClient(transport).submit(
            anchor_request(profile_id, sequence, record_hash)
        )
    except AnchorRejected as error:
        raise AnchorBindRefused(str(error)) from error
    if receipt is None:
        raise AnchorBindRefused("anchor receiver did not answer")
    return bindings.record(receiver_url, receipt, verified_at=now())


class AnchorScheduler:
    """Submit the ledger head to the bound receiver whenever anchoring is due."""

    def __init__(
        self,
        bindings: AnchorBindingRepository,
        transport: HttpsAnchorTransport,
        *,
        profile_id: str,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._bindings = bindings
        self._receiver_url = transport.receiver_url
        self._client = AnchorClient(transport)
        self._profile_id = profile_id
        self._now = now

    def tick(self) -> str:
        """Anchor once if due: ``anchored``, ``not_due`` or ``failed``."""

        binding = self._bindings.current()
        if binding is None or binding.receiver_url != self._receiver_url:
            _log.warning("anchoring failed: the receiver is not the bound one")
            return "failed"
        sequence, record_hash = self._bindings.ledger_head()
        if sequence <= binding.last_acknowledged_sequence or not is_anchoring_due(
            binding.watermark, current_sequence=sequence, now=self._now()
        ):
            return "not_due"
        try:
            receipt = self._client.submit(
                anchor_request(self._profile_id, sequence, record_hash)
            )
        except AnchorRejected as error:
            _log.warning("anchoring failed at sequence %d: %s", sequence, error)
            return "failed"
        if receipt is None:
            _log.warning("anchoring failed at sequence %d: no answer", sequence)
            return "failed"
        self._bindings.acknowledge(self._receiver_url, receipt)
        return "anchored"

    def run(self, stop: threading.Event, *, interval: float = TICK_SECONDS) -> None:
        """Tick until *stop* is set; a failed tick never stops the schedule."""

        while not stop.is_set():
            try:
                self.tick()
            except Exception:  # the storage service outlives one bad tick
                _log.exception("anchoring tick failed")
            stop.wait(interval)


def start_anchoring(
    bindings: AnchorBindingRepository, settings: AnchorSettings
) -> tuple[threading.Event, threading.Thread]:
    """Start the schedule against the bound receiver; refuse when none is bound."""

    binding = bindings.current()
    if binding is None:
        raise ValueError("anchor receiver is not bound; run bind-anchor first")
    scheduler = AnchorScheduler(
        bindings,
        settings.transport(binding.receiver_url),
        profile_id=settings.profile_id,
    )
    stop = threading.Event()
    thread = threading.Thread(
        target=scheduler.run, args=(stop,), name="anchoring", daemon=True
    )
    thread.start()
    return stop, thread


def _path(value: dict[str, Any], key: str) -> Path | None:
    result = value.get(key)
    if result is None:
        return None
    if not isinstance(result, str) or not result:
        raise ValueError(f"anchor.{key} must be a nonempty string")
    return Path(result)
