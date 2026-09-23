"""Atomic sealed submissions against issued question sheets (SR-07 to SR-11).

``accept_submission`` (AG-26, TDD-3.1.57) is a second, run-scoped sealing
path beside the sheet-and-claims sealing :class:`SubmissionRepository`
otherwise implements: it validates one run's complete forecast answers and
its one nomination for the run's own paper against that run's own slot,
inside the same atomic transaction guarantees.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, cast
from uuid import uuid4

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_json, sha256_hex
from research_agent.contracts.primitives import ContractValidationError
from research_agent.contracts.submissions import (
    parse_claims,
    validate_accept_submission_payload,
    validate_submission_payload,
)
from research_agent.storage.commands import (
    CommandIdentity,
    CommandTransaction,
    DomainEvents,
)
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict, StorageError, UnavailableInput
from research_agent.storage.idempotency import StoredResponse
from research_agent.storage.verification import ArtifactVerifier


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class SubmissionRepository:
    def __init__(
        self,
        database: Database,
        store: ArtifactStore,
        *,
        producer: ProducerVersion,
        config_hash: str,
        retention_policy_hash: str,
    ) -> None:
        self._commands = CommandTransaction(database)
        self._verifier = ArtifactVerifier(store)
        self._events = DomainEvents(store, producer, config_hash, retention_policy_hash)

    def execute(
        self, operation: str, *, identity: CommandIdentity, payload: object
    ) -> StoredResponse:
        value = validate_submission_payload(operation, payload)

        def mutate(connection: Connection[tuple[object, ...]]) -> dict[str, Any]:
            return self._submit(connection, identity, value)

        return self._commands.execute(identity, "/v1/submissions", {}, value, mutate)

    def accept_submission(
        self, *, identity: CommandIdentity, payload: object
    ) -> StoredResponse:
        """Seal one run's complete forecast answers and nomination (AG-26).

        Requires answer ids to equal the run's own issued question set
        exactly and the nomination's paper id to equal the run's own paper;
        any structural or semantic failure rejects the whole attempt and
        records ``submission_rejected`` rather than sealing a partial
        forecast set. A retry with the same ``(run_id, submission_id)`` and
        identical bytes returns the original result rather than resealing;
        changed bytes conflict.
        """

        value = validate_accept_submission_payload("accept_submission", payload)

        def mutate(connection: Connection[tuple[object, ...]]) -> dict[str, Any]:
            return self._accept_submission(connection, identity, value)

        return self._commands.execute(
            identity, "/v1/runs/{id}/submit", {"id": value["run_id"]}, value, mutate
        )

    def _accept_submission(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        run_id = value["run_id"]
        run = connection.execute(
            "SELECT paper_id, issued_question_ids, batch_id FROM runs WHERE id=%s",
            (run_id,),
        ).fetchone()
        if run is None:
            raise UnavailableInput("accept_submission names an unknown run")
        paper_id = cast(str, run[0])
        issued_question_ids = frozenset(str(item) for item in cast(list[Any], run[1]))
        batch_id = cast(bytes, run[2])
        void = connection.execute(
            "SELECT 1 FROM run_terminal_states WHERE run_id=%s AND state='void'",
            (run_id,),
        ).fetchone()
        if void is not None:
            raise StateConflict("run is void and accepts no submission")

        request_hash = sha256_hex(canonical_json(value))
        existing = connection.execute(
            """SELECT submission_id, encode(request_hash,'hex'), accepted_at
               FROM run_submissions WHERE run_id=%s""",
            (run_id,),
        ).fetchone()
        if existing is not None:
            if (
                str(existing[0]) == value["submission_id"]
                and str(existing[1]) == request_hash
            ):
                return {
                    "accepted": True,
                    "run_id": run_id,
                    "submission_id": value["submission_id"],
                    "receipt": {
                        "replay": True,
                        "accepted_at": _utc(cast(datetime, existing[2])),
                    },
                }
            raise StateConflict(
                "run already has an accepted submission with different bytes"
            )

        try:
            answer_ids = frozenset(answer["question_id"] for answer in value["answers"])
            if answer_ids != issued_question_ids:
                raise ContractValidationError(
                    "answers do not exactly cover the run's issued questions"
                )
            if value["nomination"]["paper_id"] != paper_id:
                raise ContractValidationError(
                    "nomination names a paper other than the run's own"
                )
            deadline = self._deadline(connection, batch_id, issued_question_ids)
            if datetime.now(timezone.utc) > deadline:
                raise ContractValidationError("submission arrived after its deadline")
            evidence_hashes: list[str] = []
            for answer in value["answers"]:
                for evidence_id in answer["evidence_ids"]:
                    try:
                        self._verifier.verify(connection, evidence_id)
                    except StorageError as error:
                        raise ContractValidationError(
                            "answer evidence is unavailable"
                        ) from error
                    evidence_hashes.append(evidence_id)
        except ContractValidationError as error:
            return self._reject_run_submission(connection, identity, run_id, str(error))

        accepted_at = datetime.now(timezone.utc)
        # The run's one terminal row is the compare-and-set shared with
        # finish_without_submit (AG-15): whichever inserts it first wins.
        claimed = connection.execute(
            """INSERT INTO run_terminal_states(run_id, state, ended_at)
               VALUES(%s, 'submitted', %s)
               ON CONFLICT (run_id) DO NOTHING RETURNING run_id""",
            (run_id, accepted_at),
        ).fetchone()
        if claimed is None:
            raise StateConflict("run ended concurrently")
        connection.execute(
            """INSERT INTO run_submissions(run_id, submission_id, request_hash, accepted_at)
               VALUES(%s, %s, decode(%s,'hex'), %s)""",
            (run_id, value["submission_id"], request_hash, accepted_at),
        )
        for answer in value["answers"]:
            connection.execute(
                """INSERT INTO run_forecasts(run_id, question_id, probability, rationale)
                   VALUES(%s, %s, %s, %s)""",
                (
                    run_id,
                    answer["question_id"],
                    answer["probability"],
                    answer["rationale"],
                ),
            )
            for ordinal, evidence_id in enumerate(answer["evidence_ids"]):
                connection.execute(
                    """INSERT INTO run_forecast_evidence(
                           run_id, question_id, ordinal, evidence_hash)
                       VALUES(%s, %s, %s, decode(%s,'hex'))""",
                    (run_id, answer["question_id"], ordinal, evidence_id),
                )
        nomination = value["nomination"]
        connection.execute(
            """INSERT INTO run_nominations(run_id, paper_id, recommend, preference, rationale)
               VALUES(%s, %s, %s, %s, %s)""",
            (
                run_id,
                nomination["paper_id"],
                nomination["recommend"],
                nomination["preference"],
                nomination["rationale"],
            ),
        )
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="submission_accepted",
            payload={
                "schema_version": 1,
                "accepted_at": _utc(accepted_at),
                **value,
            },
            input_hashes=tuple(dict.fromkeys(evidence_hashes)),
        )
        return {
            "accepted": True,
            "run_id": run_id,
            "submission_id": value["submission_id"],
            "receipt": receipt,
        }

    def _deadline(
        self,
        connection: Connection[tuple[object, ...]],
        batch_id: bytes,
        issued_question_ids: frozenset[str],
    ) -> datetime:
        """The run's own scheduling deadline (TDD-3.1.61).

        A questionless engineering slot uses the sheet's seal time plus 24
        hours; otherwise the earliest horizon among the run's own issued
        questions.
        """

        if not issued_question_ids:
            sealed = connection.execute(
                "SELECT sealed_at FROM sheets WHERE hash=%s", (batch_id,)
            ).fetchone()
            assert sealed is not None
            return cast(datetime, sealed[0]) + timedelta(hours=24)
        horizon = connection.execute(
            """SELECT MIN(horizon) FROM sheet_questions
               WHERE sheet_hash=%s AND question_id = ANY(%s)""",
            (batch_id, list(issued_question_ids)),
        ).fetchone()
        assert horizon is not None and horizon[0] is not None
        return cast(datetime, horizon[0])

    def _reject_run_submission(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        run_id: str,
        reason: str,
    ) -> dict[str, Any]:
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="submission_rejected",
            payload={
                "schema_version": 1,
                "run_id": run_id,
                "reason": reason[:512],
            },
            input_hashes=(),
        )
        return {"accepted": False, "reason": reason[:512], "receipt": receipt}

    def _submit(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        sheet_hash, submitter_id = value["sheet_hash"], value["submitter_id"]
        try:
            claims = self._validate(
                connection, sheet_hash, submitter_id, value["claims"]
            )
        except ContractValidationError as error:
            return self._reject(
                connection, identity, sheet_hash, submitter_id, str(error)
            )

        sealed_ids: list[str] = []
        receipts: list[dict[str, Any]] = []
        for claim, horizon in claims:
            submission_id = uuid4()
            if claim["kind"] == "forecast":
                status, confidence, reason = "sealed", claim["confidence"], None
            else:
                status, confidence, reason = "void", None, claim["reason"]
            connection.execute(
                """INSERT INTO submissions(
                       id, sheet_hash, submitter_id, question_id, status,
                       confidence, horizon, reason, sealed_at
                   ) VALUES(%s, decode(%s,'hex'), %s, %s, %s, %s, %s, %s, clock_timestamp())""",
                (
                    submission_id,
                    sheet_hash,
                    submitter_id,
                    claim["question_id"],
                    status,
                    confidence,
                    horizon,
                    reason,
                ),
            )
            evidence_hashes: tuple[str, ...] = ()
            if claim["kind"] == "forecast":
                evidence_hashes = tuple(claim["evidence_hashes"])
                for ordinal, evidence_hash in enumerate(evidence_hashes):
                    connection.execute(
                        """INSERT INTO submission_evidence(submission_id, ordinal, evidence_hash)
                           VALUES(%s, %s, decode(%s,'hex'))""",
                        (submission_id, ordinal, evidence_hash),
                    )
            receipt = self._events.append(
                connection,
                command_id=identity.command_id,
                event_kind="submission_accepted",
                payload={
                    "schema_version": 1,
                    "submission_id": str(submission_id),
                    "sheet_hash": sheet_hash,
                    "submitter_id": submitter_id,
                    "sealed_at": _utc(datetime.now(timezone.utc)),
                    **claim,
                },
                input_hashes=evidence_hashes,
            )
            sealed_ids.append(str(submission_id))
            receipts.append(receipt)
        return {
            "accepted": True,
            "submission_ids": sealed_ids,
            "receipt": _merge_receipts(receipts),
        }

    def _validate(
        self,
        connection: Connection[tuple[object, ...]],
        sheet_hash: str,
        submitter_id: str,
        raw_claims: list[object],
    ) -> list[tuple[dict[str, Any], str | None]]:
        sheet = connection.execute(
            "SELECT 1 FROM sheets WHERE hash=decode(%s,'hex')", (sheet_hash,)
        ).fetchone()
        if sheet is None:
            raise ContractValidationError("sheet is not sealed")
        claims = parse_claims(raw_claims)
        question_ids = [claim["question_id"] for claim in claims]
        questions = {
            str(row[0]): _utc(cast(datetime, row[1]))
            for row in connection.execute(
                """SELECT question_id, horizon FROM sheet_questions
                   WHERE sheet_hash=decode(%s,'hex') AND question_id=ANY(%s)""",
                (sheet_hash, question_ids),
            ).fetchall()
        }
        missing = [item for item in question_ids if item not in questions]
        if missing:
            raise ContractValidationError("claim names a question not on the sheet")
        already_sealed = connection.execute(
            """SELECT question_id FROM submissions
               WHERE sheet_hash=decode(%s,'hex') AND submitter_id=%s
                 AND question_id=ANY(%s)""",
            (sheet_hash, submitter_id, question_ids),
        ).fetchall()
        if already_sealed:
            raise ContractValidationError(
                "submitter already has a sealed claim for this question"
            )
        for claim in claims:
            if claim["kind"] != "forecast":
                continue
            for evidence_hash in claim["evidence_hashes"]:
                try:
                    self._verifier.verify(connection, evidence_hash)
                except StorageError as error:
                    raise ContractValidationError(
                        "claim evidence is unavailable"
                    ) from error
        return [
            (
                claim,
                questions[claim["question_id"]]
                if claim["kind"] == "forecast"
                else None,
            )
            for claim in claims
        ]

    def _reject(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        sheet_hash: str,
        submitter_id: str,
        reason: str,
    ) -> dict[str, Any]:
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="submission_rejected",
            payload={
                "schema_version": 1,
                "sheet_hash": sheet_hash,
                "submitter_id": submitter_id,
                "reason": reason[:512],
            },
            input_hashes=(),
        )
        return {"accepted": False, "reason": reason[:512], "receipt": receipt}


def _merge_receipts(receipts: list[dict[str, Any]]) -> dict[str, Any]:
    record_ids: list[str] = []
    artifact_hashes: list[str] = []
    for receipt in receipts:
        record_ids.extend(cast(list[str], receipt["record_ids"]))
        artifact_hashes.extend(cast(list[str], receipt["artifact_hashes"]))
    sequences = [cast(int, receipt["ledger_first"]) for receipt in receipts] + [
        cast(int, receipt["ledger_last"]) for receipt in receipts
    ]
    return {
        "record_ids": record_ids,
        "artifact_hashes": artifact_hashes,
        "ledger_first": min(sequences),
        "ledger_last": max(sequences),
        "committed_at": receipts[-1]["committed_at"],
    }
