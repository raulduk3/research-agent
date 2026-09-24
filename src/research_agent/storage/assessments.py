"""PostgreSQL owners for the Jev work store and the assessment pointers (#258).

`JevWorkRepository` implements the storage operations `ingest.jev.JevWorker`
reaches through `JevWorkStore` (TDD-4.1.58): a lease per work key, attempt
reservations counted against the UTC day's cap and spend sublimit, and the
attempt manifest commit. `AskRepository` holds the ask tool's side of the
same record (decision 0031): the daily ask pool reserved beside the card
attempts, and each run's answered asks. `AssessmentPointerRepository` implements the
reader's `AssessmentPointers` (TDD-4.1.59): the compare-and-swap current
pointer for a paper version and the pin a sealed snapshot keeps.

Every check-and-change is one statement or one transaction that PostgreSQL
serializes on a row, so a second connection cannot take a held lease, spend
past a cap or move a pointer from a stale value.
"""

from __future__ import annotations

import base64
import binascii
import threading
from datetime import date
from typing import Any, cast
from uuid import uuid4

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.contracts.canonical import (
    CanonicalJsonError,
    canonical_loads,
    sha256_hex,
)
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_negative_int,
    validate_positive_int,
    validate_sha256,
    validate_uuid4,
)
from research_agent.storage.commands import (
    CommandIdentity,
    CommandTransaction,
    DomainEvents,
)
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict, UnavailableInput
from research_agent.storage.idempotency import StoredResponse
from research_agent.storage.trace import install_payload

#: A worker's two 30-second attempts, the 2-second retry pause and the
#: manifest commit fit well inside it; a crashed worker frees its key by expiry.
LEASE_SECONDS = 300
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_ASK_ANSWER_BYTES = 64 * 1024
#: The most bytes of one ask's Jev request or response storage keeps; the
#: route carries them base64-encoded inside a 1 MiB command.
ASK_PAYLOAD_BOUND = 256 * 1024
BILLING_STATES = frozenset(
    {"no_attempt", "known_rejected", "known_completed", "uncertain"}
)
_ASK_FIELDS = {
    "reserve": frozenset(
        {
            "run_id",
            "work_key",
            "day",
            "worst_case_micros",
            "daily_attempt_cap",
            "daily_limit_micros",
            "ask_pool_micros",
            "request_payload",
        }
    ),
    "settle": frozenset(
        {"run_id", "reservation_id", "billing_state", "response_payload"}
    ),
    "record": frozenset({"run_id", "work_key", "answer"}),
}
_ASK_ROUTES = {
    "reserve": "/v1/runs/{id}/asks/reservations",
    "settle": "/v1/runs/{id}/asks/settlements",
    "record": "/v1/runs/{id}/asks/answers",
}


class JevWorkRepository:
    """The durable `JevWorkStore`: leases, reservations and manifest commits."""

    def __init__(self, database: Database, *, lease_seconds: int = LEASE_SECONDS):
        validate_positive_int(lease_seconds)
        self._database = database
        self._lease_seconds = lease_seconds
        self._guard = threading.Lock()
        self._held: dict[str, str] = {}

    def committed_attempt(self, work_key: str) -> bytes | None:
        validate_sha256(work_key)

        def read(connection: Connection[tuple[object, ...]]) -> bytes | None:
            row = connection.execute(
                """SELECT manifest FROM jev_attempt_manifests
                   WHERE work_key=decode(%s,'hex') ORDER BY id DESC LIMIT 1""",
                (work_key,),
            ).fetchone()
            return None if row is None else bytes(cast(bytes, row[0]))

        return self._database.transaction(read)

    def acquire_lease(self, work_key: str) -> bool:
        """Take the key's lease unless a live holder has it; never reentrant."""

        validate_sha256(work_key)
        token = str(uuid4())

        def take(connection: Connection[tuple[object, ...]]) -> bool:
            row = connection.execute(
                """INSERT INTO jev_work_leases(work_key, holder, expires_at)
                   VALUES(decode(%s,'hex'), %s,
                          clock_timestamp() + make_interval(secs => %s))
                   ON CONFLICT (work_key) DO UPDATE
                   SET holder = EXCLUDED.holder, expires_at = EXCLUDED.expires_at
                   WHERE jev_work_leases.expires_at <= clock_timestamp()
                   RETURNING 1""",
                (work_key, token, self._lease_seconds),
            ).fetchone()
            return row is not None

        if not self._database.transaction(take):
            return False
        with self._guard:
            self._held[work_key] = token
        return True

    def release_lease(self, work_key: str) -> None:
        """Free the key if this store still holds it; an expired lease taken by
        another holder is left alone."""

        validate_sha256(work_key)
        with self._guard:
            token = self._held.pop(work_key, None)
        if token is None:
            return

        def free(connection: Connection[tuple[object, ...]]) -> None:
            connection.execute(
                """UPDATE jev_work_leases SET expires_at = clock_timestamp()
                   WHERE work_key=decode(%s,'hex') AND holder=%s""",
                (work_key, token),
            )

        self._database.transaction(free)

    def reserve_attempt(
        self,
        *,
        work_key: str,
        day: str,
        worst_case_micros: int,
        daily_attempt_cap: int,
        daily_limit_micros: int,
    ) -> str | None:
        """Count one attempt and hold its worst-case cost, or refuse at a limit."""

        validate_sha256(work_key)
        try:
            usage_day = date.fromisoformat(day)
        except ValueError as error:
            raise ContractValidationError("day must be a UTC date") from error
        validate_non_negative_int(worst_case_micros)
        validate_non_negative_int(daily_attempt_cap)
        validate_non_negative_int(daily_limit_micros)

        def reserve(connection: Connection[tuple[object, ...]]) -> str | None:
            connection.execute(
                "INSERT INTO jev_daily_usage(day) VALUES(%s) ON CONFLICT DO NOTHING",
                (usage_day,),
            )
            counted = connection.execute(
                """UPDATE jev_daily_usage
                   SET attempts = attempts + 1,
                       reserved_micros = reserved_micros + %s
                   WHERE day = %s AND attempts + 1 <= %s
                     AND reserved_micros + %s <= %s
                   RETURNING 1""",
                (
                    worst_case_micros,
                    usage_day,
                    daily_attempt_cap,
                    worst_case_micros,
                    daily_limit_micros,
                ),
            ).fetchone()
            if counted is None:
                return None
            reservation_id = str(uuid4())
            connection.execute(
                """INSERT INTO jev_attempt_reservations(
                       id, work_key, day, worst_case_micros, reserved_at
                   ) VALUES(%s, decode(%s,'hex'), %s, %s, clock_timestamp())""",
                (reservation_id, work_key, usage_day, worst_case_micros),
            )
            return reservation_id

        return self._database.transaction(reserve)

    def settle_attempt(self, reservation_id: str, billing_state: str) -> None:
        """Record how a reservation ended, once; its cost stays in the day's total."""

        validate_uuid4(reservation_id)
        if billing_state not in BILLING_STATES:
            raise ContractValidationError("billing_state is not admitted")

        def settle(connection: Connection[tuple[object, ...]]) -> None:
            settled = connection.execute(
                """UPDATE jev_attempt_reservations
                   SET billing_state=%s, settled_at=clock_timestamp()
                   WHERE id=%s AND billing_state IS NULL RETURNING 1""",
                (billing_state, reservation_id),
            ).fetchone()
            if settled is None:
                raise StateConflict("reservation is unknown or already settled")

        self._database.transaction(settle)

    def commit_attempt(self, work_key: str, manifest: bytes) -> None:
        """Make `manifest` the key's committed attempt and stamp its availability."""

        validate_sha256(work_key)
        if (
            not isinstance(manifest, bytes)
            or not 0 < len(manifest) <= MAX_MANIFEST_BYTES
        ):
            raise ContractValidationError("manifest must be 1 byte to 1 MiB")
        try:
            body = canonical_loads(manifest)
        except CanonicalJsonError as error:
            raise ContractValidationError("manifest is not canonical JSON") from error
        if not isinstance(body, dict) or body.get("work_key") != work_key:
            raise ContractValidationError("manifest names another work key")

        def commit(connection: Connection[tuple[object, ...]]) -> None:
            connection.execute(
                """INSERT INTO jev_attempt_manifests(
                       work_key, manifest_hash, manifest, committed_at
                   ) VALUES(decode(%s,'hex'), decode(%s,'hex'), %s, clock_timestamp())""",
                (work_key, sha256_hex(manifest), manifest),
            )

        self._database.transaction(commit)


def _ask_bytes(encoded: object, field: str, maximum: int) -> bytes:
    if not isinstance(encoded, str):
        raise ContractValidationError(f"ask {field} is invalid")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ContractValidationError(f"ask {field} is not base64") from error
    if not 0 < len(data) <= maximum:
        raise ContractValidationError(f"ask {field} must be 1 to {maximum} bytes")
    return data


def _usage_day(value: object) -> date:
    if not isinstance(value, str):
        raise ContractValidationError("day must be a UTC date")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ContractValidationError("day must be a UTC date") from error


def validate_ask_payload(operation: str, payload: object) -> dict[str, Any]:
    """Validate and copy the exact payload of one ask command."""

    fields = _ASK_FIELDS.get(operation)
    if fields is None:
        raise ContractValidationError("unknown ask operation")
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ContractValidationError(
            f"ask {operation} payload has unknown or missing fields"
        )
    value: dict[str, Any] = dict(payload)
    validate_uuid4(value["run_id"])
    if operation == "reserve":
        validate_sha256(value["work_key"])
        _usage_day(value["day"])
        for name in (
            "worst_case_micros",
            "daily_attempt_cap",
            "daily_limit_micros",
            "ask_pool_micros",
        ):
            validate_non_negative_int(value[name])
        _ask_bytes(value["request_payload"], "request_payload", ASK_PAYLOAD_BOUND)
    elif operation == "settle":
        validate_uuid4(value["reservation_id"])
        if value["billing_state"] not in BILLING_STATES:
            raise ContractValidationError("billing_state is not admitted")
        if value["response_payload"] is not None:
            if value["billing_state"] not in {"known_completed", "known_rejected"}:
                raise ContractValidationError("only an answered attempt has a response")
            _ask_bytes(value["response_payload"], "response_payload", ASK_PAYLOAD_BOUND)
    else:
        validate_sha256(value["work_key"])
        _ask_bytes(value["answer"], "answer", MAX_ASK_ANSWER_BYTES)
    return value


class AskRepository:
    """The ask tool's side of the Jev work record (decision 0031).

    The tool service reaches it through its own storage routes. ``reserve``
    counts one ask against the UTC day's attempt cap, the whole Jev
    sublimit and the ask pool in one update, so an ask never spends what
    the sublimit leaves the cards; ``settle`` records how an ask's
    reservation ended and cannot settle a card attempt; ``record`` keeps a
    run's answered ask once. The Jev request and response bytes travel with
    ``reserve`` and ``settle`` and are stored as ``tool_request`` and
    ``provider_response`` artifacts in the same transaction as their row.
    """

    def __init__(
        self,
        database: Database,
        store: ArtifactStore,
        *,
        producer: ProducerVersion,
        config_hash: str,
        retention_policy_hash: str,
    ) -> None:
        self._database = database
        self._commands = CommandTransaction(database)
        self._events = DomainEvents(store, producer, config_hash, retention_policy_hash)

    def execute(
        self, operation: str, *, identity: CommandIdentity, payload: object
    ) -> StoredResponse:
        value = validate_ask_payload(operation, payload)
        mutate = {
            "reserve": self._reserve,
            "settle": self._settle,
            "record": self._record,
        }[operation]
        return self._commands.execute(
            identity,
            _ASK_ROUTES[operation],
            {"id": value["run_id"]},
            value,
            lambda connection: mutate(connection, value),
        )

    def recorded(self, run_id: str, work_key: str) -> bytes | None:
        """The answer kept for this run's ask under *work_key*, if any."""

        validate_uuid4(run_id)
        validate_sha256(work_key)

        def read(connection: Connection[tuple[object, ...]]) -> bytes | None:
            row = connection.execute(
                """SELECT answer FROM jev_ask_answers
                   WHERE run_id=%s AND work_key=decode(%s,'hex')""",
                (run_id, work_key),
            ).fetchone()
            return None if row is None else bytes(cast(bytes, row[0]))

        return self._database.transaction(read)

    def answered(self, run_id: str) -> int:
        """How many distinct asks this run has been answered."""

        validate_uuid4(run_id)

        def count(connection: Connection[tuple[object, ...]]) -> int:
            row = connection.execute(
                "SELECT count(*) FROM jev_ask_answers WHERE run_id=%s", (run_id,)
            ).fetchone()
            return 0 if row is None else cast(int, row[0])

        return self._database.transaction(count)

    def _reserve(
        self, connection: Connection[tuple[object, ...]], value: dict[str, Any]
    ) -> dict[str, Any]:
        run = connection.execute(
            "SELECT allowed_tools FROM runs WHERE id=%s", (value["run_id"],)
        ).fetchone()
        if run is None:
            raise UnavailableInput("the ask names an unknown run")
        if "ask" not in cast(list[str], run[0]):
            raise StateConflict("the run does not allow ask")
        day = _usage_day(value["day"])
        connection.execute(
            "INSERT INTO jev_daily_usage(day) VALUES(%s) ON CONFLICT DO NOTHING",
            (day,),
        )
        counted = connection.execute(
            """UPDATE jev_daily_usage
               SET attempts = attempts + 1,
                   reserved_micros = reserved_micros + %(cost)s,
                   ask_reserved_micros = ask_reserved_micros + %(cost)s
               WHERE day = %(day)s AND attempts + 1 <= %(cap)s
                 AND reserved_micros + %(cost)s <= %(limit)s
                 AND ask_reserved_micros + %(cost)s <= %(pool)s
               RETURNING 1""",
            {
                "cost": value["worst_case_micros"],
                "day": day,
                "cap": value["daily_attempt_cap"],
                "limit": value["daily_limit_micros"],
                "pool": value["ask_pool_micros"],
            },
        ).fetchone()
        if counted is None:
            return {"reservation_id": None, "request_hash": None}
        reservation_id = str(uuid4())
        connection.execute(
            """INSERT INTO jev_attempt_reservations(
                   id, work_key, day, worst_case_micros, reserved_at, purpose
               ) VALUES(%s, decode(%s,'hex'), %s, %s, clock_timestamp(), 'ask')""",
            (reservation_id, value["work_key"], day, value["worst_case_micros"]),
        )
        request_hash = install_payload(
            connection,
            self._events,
            base64.b64decode(value["request_payload"]),
            kind="tool_request",
            maximum_length=ASK_PAYLOAD_BOUND,
        )
        return {"reservation_id": reservation_id, "request_hash": request_hash}

    def _settle(
        self, connection: Connection[tuple[object, ...]], value: dict[str, Any]
    ) -> dict[str, Any]:
        settled = connection.execute(
            """UPDATE jev_attempt_reservations
               SET billing_state=%s, settled_at=clock_timestamp()
               WHERE id=%s AND purpose='ask' AND billing_state IS NULL
               RETURNING 1""",
            (value["billing_state"], value["reservation_id"]),
        ).fetchone()
        if settled is None:
            raise StateConflict("ask reservation is unknown or already settled")
        response_hash = None
        if value["response_payload"] is not None:
            response_hash = install_payload(
                connection,
                self._events,
                base64.b64decode(value["response_payload"]),
                kind="provider_response",
                maximum_length=ASK_PAYLOAD_BOUND,
            )
        return {
            "reservation_id": value["reservation_id"],
            "response_hash": response_hash,
        }

    def _record(
        self, connection: Connection[tuple[object, ...]], value: dict[str, Any]
    ) -> dict[str, Any]:
        run = connection.execute(
            "SELECT 1 FROM runs WHERE id=%s", (value["run_id"],)
        ).fetchone()
        if run is None:
            raise UnavailableInput("the ask names an unknown run")
        kept = connection.execute(
            """INSERT INTO jev_ask_answers(run_id, work_key, answer, answered_at)
               VALUES(%s, decode(%s,'hex'), %s, clock_timestamp())
               ON CONFLICT DO NOTHING RETURNING 1""",
            (value["run_id"], value["work_key"], base64.b64decode(value["answer"])),
        ).fetchone()
        if kept is None:
            raise StateConflict("the run's ask already has a kept answer")
        return {"run_id": value["run_id"], "work_key": value["work_key"]}


class AssessmentPointerRepository:
    """The durable `AssessmentPointers`: current section and snapshot pins."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def current(self, paper_version_id: str) -> str | None:
        validate_uuid4(paper_version_id)

        def read(connection: Connection[tuple[object, ...]]) -> str | None:
            row = connection.execute(
                """SELECT encode(section_hash,'hex') FROM assessment_pointers
                   WHERE paper_version_id=%s""",
                (paper_version_id,),
            ).fetchone()
            return None if row is None else cast(str, row[0])

        return self._database.transaction(read)

    def compare_and_swap(
        self, paper_version_id: str, expected: str | None, new: str
    ) -> bool:
        """Move the pointer only from `expected` (`None` means no pointer yet)."""

        validate_uuid4(paper_version_id)
        validate_sha256(new)
        if expected is not None:
            validate_sha256(expected)

        def swap(connection: Connection[tuple[object, ...]]) -> bool:
            if expected is None:
                row = connection.execute(
                    """INSERT INTO assessment_pointers(
                           paper_version_id, section_hash, updated_at
                       ) VALUES(%s, decode(%s,'hex'), clock_timestamp())
                       ON CONFLICT DO NOTHING RETURNING 1""",
                    (paper_version_id, new),
                ).fetchone()
            else:
                row = connection.execute(
                    """UPDATE assessment_pointers
                       SET section_hash=decode(%s,'hex'), updated_at=clock_timestamp()
                       WHERE paper_version_id=%s
                         AND section_hash=decode(%s,'hex') RETURNING 1""",
                    (new, paper_version_id, expected),
                ).fetchone()
            return row is not None

        return self._database.transaction(swap)

    def pin_snapshot(self, snapshot_id: str, paper_version_id: str) -> str | None:
        """Pin the current section for a sealed snapshot's paper, once.

        Returns the pinned hash, or `None` when the paper has no current
        section. A pin already written is returned unchanged, so a later
        pointer move never reaches a snapshot. The paper must be one of the
        snapshot's items.
        """

        validate_sha256(snapshot_id)
        validate_uuid4(paper_version_id)

        def pin(connection: Connection[tuple[object, ...]]) -> str | None:
            connection.execute(
                """INSERT INTO assessment_snapshot_pins(
                       snapshot_hash, paper_version_id, section_hash, pinned_at
                   ) SELECT decode(%s,'hex'), paper_version_id, section_hash,
                            clock_timestamp()
                     FROM assessment_pointers WHERE paper_version_id=%s
                   ON CONFLICT DO NOTHING""",
                (snapshot_id, paper_version_id),
            )
            return self._pin(connection, snapshot_id, paper_version_id)

        return self._database.transaction(pin)

    def snapshot_pin(self, snapshot_id: str, paper_version_id: str) -> str | None:
        validate_sha256(snapshot_id)
        validate_uuid4(paper_version_id)
        return self._database.transaction(
            lambda connection: self._pin(connection, snapshot_id, paper_version_id)
        )

    @staticmethod
    def _pin(
        connection: Connection[tuple[object, ...]],
        snapshot_id: str,
        paper_version_id: str,
    ) -> str | None:
        row = connection.execute(
            """SELECT encode(section_hash,'hex') FROM assessment_snapshot_pins
               WHERE snapshot_hash=decode(%s,'hex') AND paper_version_id=%s""",
            (snapshot_id, paper_version_id),
        ).fetchone()
        return None if row is None else cast(str, row[0])

    def read(
        self, paper_version_id: str, snapshot_hash: str | None
    ) -> dict[str, str | None]:
        """What the reader's route serves: the current pointer and, when a
        snapshot is named, that snapshot's pin."""

        return {
            "paper_version_id": paper_version_id,
            "current": self.current(paper_version_id),
            "pinned": (
                None
                if snapshot_hash is None
                else self.snapshot_pin(snapshot_hash, paper_version_id)
            ),
        }
