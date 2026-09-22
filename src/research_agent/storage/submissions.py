"""Atomic sealed submissions against issued question sheets (SR-07 to SR-11)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast
from uuid import uuid4

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.contracts.primitives import ContractValidationError
from research_agent.contracts.submissions import (
    parse_claims,
    validate_submission_payload,
)
from research_agent.storage.commands import (
    CommandIdentity,
    CommandTransaction,
    DomainEvents,
)
from research_agent.storage.database import Database
from research_agent.storage.errors import StorageError
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
