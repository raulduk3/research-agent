"""Externally immutable chain-head receipts (SDD-SR-16).

Storage schedules anchoring after 100 new ledger records or 15 minutes,
whichever comes first, and sends the current sequence, record hash, profile
id and an idempotency key to a separate append-only receiver. The receiver's
authority is append/read only: it never accepts a replacement or a
decreasing sequence, and a request timeout never advances the acknowledged
watermark. Sealing refuses new seals once the unanchored backlog exceeds 30
minutes, while capture already recorded stays available.

`HttpsAnchorTransport` is the receiver transport: one append-only POST of the
ledger head, authenticated by a client certificate or a bearer token, whose
answer is accepted only if it acknowledges exactly the head that was sent.
`AnchorBindingRepository` keeps the receiver storage is bound to and the last
head it acknowledged (#325).
"""

from __future__ import annotations

import ssl
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import httpx
from psycopg import Connection

from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_non_negative_int,
    validate_sha256,
    validate_utc_instant,
)
from research_agent.storage.database import Database

RECORD_INTERVAL = 100
TIME_INTERVAL = timedelta(minutes=15)
BACKLOG_BOUND = timedelta(minutes=30)


class AnchorTimeout(RuntimeError):
    """Raised by a transport when the receiver did not answer in time."""


class AnchorRejected(RuntimeError):
    """Raised when the receiver refused the head or did not acknowledge it."""


@dataclass(frozen=True, slots=True)
class AnchorRequest:
    sequence: int
    record_hash: str
    profile_id: str
    idempotency_key: str

    def __post_init__(self) -> None:
        validate_non_negative_int(self.sequence)
        validate_sha256(self.record_hash)
        validate_non_empty_string(self.profile_id)
        validate_non_empty_string(self.idempotency_key)


@dataclass(frozen=True, slots=True)
class AnchorReceipt:
    """An immutable, receiver-authenticated proof that a sequence was anchored."""

    sequence: int
    record_hash: str
    receiver_signature: str
    accepted_at: str

    def __post_init__(self) -> None:
        validate_non_negative_int(self.sequence)
        validate_sha256(self.record_hash)
        validate_non_empty_string(self.receiver_signature)
        validate_utc_instant(self.accepted_at)


@dataclass(frozen=True, slots=True)
class AnchorWatermark:
    """The last sequence storage has an accepted receipt for."""

    last_receipted_sequence: int
    last_receipted_at: str

    def __post_init__(self) -> None:
        validate_non_negative_int(self.last_receipted_sequence)
        validate_utc_instant(self.last_receipted_at)


def record_receipt(previous: AnchorReceipt | None, new: AnchorReceipt) -> AnchorReceipt:
    """Accept a receipt only if it strictly advances the sequence; never replace."""

    if previous is not None and new.sequence <= previous.sequence:
        raise ContractValidationError(
            "receiver rejects a replacement or a decreasing sequence"
        )
    return new


def is_anchoring_due(
    watermark: AnchorWatermark, *, current_sequence: int, now: datetime
) -> bool:
    """Anchor after 100 new records or 15 minutes, whichever comes first."""

    if current_sequence - watermark.last_receipted_sequence >= RECORD_INTERVAL:
        return True
    last = datetime.strptime(
        watermark.last_receipted_at, "%Y-%m-%dT%H:%M:%S.%fZ"
    ).replace(tzinfo=timezone.utc)
    return now - last >= TIME_INTERVAL


def exceeds_backlog(watermark: AnchorWatermark, *, now: datetime) -> bool:
    """Refuse new seals once the unanchored backlog exceeds the 30-minute bound."""

    last = datetime.strptime(
        watermark.last_receipted_at, "%Y-%m-%dT%H:%M:%S.%fZ"
    ).replace(tzinfo=timezone.utc)
    return now - last > BACKLOG_BOUND


class AnchorClient:
    """Sends anchor requests through an injectable transport; never mutates on timeout."""

    def __init__(self, transport: Callable[[AnchorRequest], AnchorReceipt]) -> None:
        self._transport = transport

    def submit(self, request: AnchorRequest) -> AnchorReceipt | None:
        """Return the receiver's receipt, or None if the attempt timed out."""

        try:
            return self._transport(request)
        except AnchorTimeout:
            return None


class HttpsAnchorTransport:
    """POST one ledger head to the receiver's append-only ``/v1/anchors`` route.

    The receiver's certificate must chain to ``ca_file``. The caller is
    authenticated by exactly one of a client certificate pair (mTLS) or a
    bearer token file, whichever the receiver requires. A receipt whose
    sequence or record hash differs from the request is not an
    acknowledgement and is refused; so is any status other than 200 or 201.
    """

    def __init__(
        self,
        receiver_url: str,
        *,
        ca_file: Path,
        client_certificate_file: Path | None = None,
        client_private_key_file: Path | None = None,
        bearer_token_file: Path | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not receiver_url.startswith("https://"):
            raise ContractValidationError("anchor receiver must be an https URL")
        mutual = client_certificate_file is not None
        if mutual != (client_private_key_file is not None):
            raise ContractValidationError(
                "anchor client certificate and private key are declared together"
            )
        if mutual == (bearer_token_file is not None):
            raise ContractValidationError(
                "anchor receiver takes exactly one of mTLS or a bearer token"
            )
        context = ssl.create_default_context(cafile=str(ca_file))
        headers: dict[str, str] = {}
        if client_certificate_file is not None:
            context.load_cert_chain(
                str(client_certificate_file), str(client_private_key_file)
            )
        if bearer_token_file is not None:
            token = bearer_token_file.read_text().strip()
            if not token:
                raise ContractValidationError("anchor bearer token file is empty")
            headers["Authorization"] = f"Bearer {token}"
        self.receiver_url = receiver_url
        self._endpoint = receiver_url.rstrip("/") + "/v1/anchors"
        self._context = context
        self._headers = headers
        self._timeout = timeout_seconds

    def __call__(self, request: AnchorRequest) -> AnchorReceipt:
        try:
            with httpx.Client(
                verify=self._context, timeout=self._timeout, follow_redirects=False
            ) as client:
                response = client.post(
                    self._endpoint,
                    headers={
                        **self._headers,
                        "Idempotency-Key": request.idempotency_key,
                    },
                    json={
                        "sequence": request.sequence,
                        "record_hash": request.record_hash,
                        "profile_id": request.profile_id,
                        "idempotency_key": request.idempotency_key,
                    },
                )
        except httpx.TransportError as error:
            raise AnchorTimeout("anchor receiver did not answer") from error
        if response.status_code not in (200, 201):
            raise AnchorRejected(
                f"anchor receiver answered status {response.status_code}"
            )
        try:
            body = response.json()
            receipt = AnchorReceipt(
                sequence=body["sequence"],
                record_hash=body["record_hash"],
                receiver_signature=body["receiver_signature"],
                accepted_at=body["accepted_at"],
            )
        except (ValueError, KeyError, TypeError) as error:
            raise AnchorRejected(
                "anchor receiver answered without a receipt"
            ) from error
        if (receipt.sequence, receipt.record_hash) != (
            request.sequence,
            request.record_hash,
        ):
            raise AnchorRejected("anchor receipt does not acknowledge the sent head")
        return receipt


@dataclass(frozen=True, slots=True)
class AnchorBinding:
    """The receiver storage anchors to and the last head it acknowledged."""

    receiver_url: str
    verified_at: str
    last_acknowledged_sequence: int
    last_acknowledged_hash: str
    last_acknowledged_at: str

    def __post_init__(self) -> None:
        validate_non_empty_string(self.receiver_url)
        validate_utc_instant(self.verified_at)
        validate_non_negative_int(self.last_acknowledged_sequence)
        validate_sha256(self.last_acknowledged_hash)
        validate_utc_instant(self.last_acknowledged_at)

    @property
    def watermark(self) -> AnchorWatermark:
        return AnchorWatermark(
            self.last_acknowledged_sequence, self.last_acknowledged_at
        )


_BINDING_COLUMNS = """receiver_url, verified_at, last_acknowledged_sequence,
    encode(last_acknowledged_hash, 'hex'), last_acknowledged_at"""


class AnchorBindingRepository:
    """Record a verified receiver binding and advance its acknowledged head.

    Recording again for the same receiver and head is harmless. Advancing
    refuses a receipt that does not strictly pass the stored head, here and
    again in the table's trigger.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    def ledger_head(self) -> tuple[int, str]:
        """The committed chain head: its sequence and record hash."""

        def read(connection: Connection[tuple[object, ...]]) -> tuple[int, str]:
            row = connection.execute(
                "SELECT sequence, encode(record_hash, 'hex') FROM ledger_head WHERE singleton"
            ).fetchone()
            if row is None:
                raise RuntimeError("ledger head is absent")
            return cast(int, row[0]), cast(str, row[1])

        return self._database.transaction(read)

    def current(self) -> AnchorBinding | None:
        """The most recently verified binding, or None before any bind."""

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> AnchorBinding | None:
            row = connection.execute(
                f"SELECT {_BINDING_COLUMNS} FROM anchor_bindings "
                "ORDER BY verified_at DESC, receiver_url LIMIT 1"
            ).fetchone()
            return None if row is None else _binding(row)

        return self._database.transaction(read)

    def record(
        self, receiver_url: str, receipt: AnchorReceipt, *, verified_at: datetime
    ) -> AnchorBinding:
        """Bind *receiver_url* after a verified round trip acknowledged *receipt*."""

        def write(connection: Connection[tuple[object, ...]]) -> AnchorBinding:
            row = connection.execute(
                f"""INSERT INTO anchor_bindings(receiver_url, verified_at,
                       last_acknowledged_sequence, last_acknowledged_hash,
                       last_acknowledged_at)
                   VALUES (%s, %s, %s, decode(%s, 'hex'), %s)
                   ON CONFLICT (receiver_url) DO UPDATE SET
                       verified_at = EXCLUDED.verified_at,
                       last_acknowledged_sequence = EXCLUDED.last_acknowledged_sequence,
                       last_acknowledged_hash = EXCLUDED.last_acknowledged_hash,
                       last_acknowledged_at = EXCLUDED.last_acknowledged_at
                   RETURNING {_BINDING_COLUMNS}""",
                (
                    receiver_url,
                    verified_at,
                    receipt.sequence,
                    receipt.record_hash,
                    _instant(receipt.accepted_at),
                ),
            ).fetchone()
            assert row is not None
            return _binding(row)

        return self._database.transaction(write)

    def acknowledge(self, receiver_url: str, receipt: AnchorReceipt) -> AnchorBinding:
        """Advance the bound receiver's acknowledged head to *receipt*."""

        def write(connection: Connection[tuple[object, ...]]) -> AnchorBinding:
            row = connection.execute(
                f"SELECT {_BINDING_COLUMNS} FROM anchor_bindings "
                "WHERE receiver_url = %s FOR UPDATE",
                (receiver_url,),
            ).fetchone()
            if row is None:
                raise ContractValidationError("anchor receiver is not bound")
            if receipt.sequence <= cast(int, row[2]):
                raise ContractValidationError(
                    "receiver rejects a replacement or a decreasing sequence"
                )
            updated = connection.execute(
                f"""UPDATE anchor_bindings SET
                       last_acknowledged_sequence = %s,
                       last_acknowledged_hash = decode(%s, 'hex'),
                       last_acknowledged_at = %s
                   WHERE receiver_url = %s
                   RETURNING {_BINDING_COLUMNS}""",
                (
                    receipt.sequence,
                    receipt.record_hash,
                    _instant(receipt.accepted_at),
                    receiver_url,
                ),
            ).fetchone()
            assert updated is not None
            return _binding(updated)

        return self._database.transaction(write)


def _instant(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )


def _binding(row: tuple[object, ...]) -> AnchorBinding:
    return AnchorBinding(
        receiver_url=cast(str, row[0]),
        verified_at=cast(datetime, row[1])
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        last_acknowledged_sequence=cast(int, row[2]),
        last_acknowledged_hash=cast(str, row[3]),
        last_acknowledged_at=cast(datetime, row[4])
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    )
