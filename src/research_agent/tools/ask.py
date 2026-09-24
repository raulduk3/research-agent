"""``ask``: one small Jev question at run time, budgeted (decision 0031, #300).

What Jev reads is resolved here, from the run's own snapshot (PL-21), never
copied in by the agent: a passage by its id, found among the pinned
passages of a paper the snapshot holds, or the title and abstract or
overview of a paper's pinned card. Anything else is ``not_in_snapshot``.
The ``self`` slot is the agent's own bounded words.

Two budgets bound what asks can spend. The run's: a run already answered
``ASK_CALLS_LIMIT`` asks is refused ``ask_budget_exhausted`` before Jev is
reached. The day's: each ask reserves its worst case in the Jev work
record's per-day spend, against the ask pool and the whole Jev sublimit
together, and is refused ``daily_ask_budget_exhausted`` when the pool is
spent. The request and response are stored as artifacts and the answer is
kept once per run and request, so a replayed call is served the kept
answer and never asks Jev again. The Jev credential lives only in the
transport this handler is given; the run never reaches Jev itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

from ..agents.budgets import ASK_CALLS_LIMIT
from ..artifacts.store import ArtifactStore
from ..assessments.ask import (
    ask_question,
    ask_request_body,
    ask_sentence,
    ask_work_key,
    ask_worst_case_micros,
    parse_ask_response,
)
from ..assessments.schemas import InvalidResponse
from ..contracts.canonical import canonical_json, canonical_loads, sha256_hex
from ..ingest.jev import (
    DAILY_ATTEMPT_CAP,
    MAX_ARTIFACT_BYTES,
    TIMEOUT_SECONDS,
    AmbiguousTimeout,
    ConnectionFailed,
    JevProviderConfig,
    SystemOneTransport,
)
from ..reader.chunk import SectionTokenizer
from .answers import CallContext, ToolAnswer, ToolError
from .query_cards import CardReads, pinned_family
from .snapshots import SnapshotIndex
from .text import PinnedTexts

__all__ = ["ASK_POOL_MICROS", "AskHandler", "AskStore"]

#: Decision 0031: asks draw from USD 0.50 a day inside the Jev sublimit.
ASK_POOL_MICROS = 500_000


class AskStore(Protocol):
    """The Jev work record's ask operations (``storage.assessments``)."""

    def reserve_ask(
        self,
        *,
        work_key: str,
        day: str,
        worst_case_micros: int,
        daily_attempt_cap: int,
        daily_limit_micros: int,
        ask_pool_micros: int,
    ) -> str | None: ...

    def settle_attempt(self, reservation_id: str, billing_state: str) -> None: ...

    def recorded_ask(self, run_id: str, work_key: str) -> bytes | None: ...

    def answered_asks(self, run_id: str) -> int: ...

    def record_ask(self, run_id: str, work_key: str, answer: bytes) -> None: ...


class AskHandler:
    """Answer ``ask`` from Jev over state the run's own snapshot holds."""

    def __init__(
        self,
        *,
        storage: CardReads,
        index: SnapshotIndex,
        texts: PinnedTexts,
        tokenizer: SectionTokenizer,
        store: AskStore,
        artifacts: ArtifactStore,
        transport: SystemOneTransport,
        config: JevProviderConfig,
        ask_pool_micros: int = ASK_POOL_MICROS,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._storage = storage
        self._index = index
        self._texts = texts
        self._tokenizer = tokenizer
        self._store = store
        self._artifacts = artifacts
        self._transport = transport
        self._config = config
        self._pool = ask_pool_micros
        self._clock = clock

    def __call__(
        self, arguments: Mapping[str, Any], context: CallContext
    ) -> ToolAnswer:
        state, source = self._state(arguments["about"], context.snapshot_hash)
        body = ask_request_body(
            self._config.configured_model, state, ask_question(arguments)
        )
        key = ask_work_key(context.run_id, body, self._config.configuration_hash)
        retrieved = () if source is None else (source,)
        kept = self._store.recorded_ask(context.run_id, key)
        if kept is not None:
            recorded = canonical_loads(kept)
            if not isinstance(recorded, dict):
                raise ToolError("internal_error", "the kept answer is not an object")
            return ToolAnswer(recorded, retrieved, ask_calls=1)
        if self._store.answered_asks(context.run_id) >= ASK_CALLS_LIMIT:
            raise ToolError(
                "ask_budget_exhausted",
                f"the run has used its {ASK_CALLS_LIMIT} asks",
            )
        returned_model, answer, request_hash, response_hash = self._ask(
            key, arguments, body
        )
        data = {
            "kind": "ask",
            "ask_kind": arguments["kind"],
            **answer,
            "sentence": ask_sentence(arguments["kind"], answer),
            "provenance": {
                "request_hash": request_hash,
                "response_hash": response_hash,
                "returned_model": returned_model,
                "configuration_hash": self._config.configuration_hash,
            },
        }
        self._store.record_ask(context.run_id, key, canonical_json(data))
        return ToolAnswer(data, retrieved, ask_calls=1)

    def _ask(
        self, key: str, arguments: Mapping[str, Any], body: bytes
    ) -> tuple[str | None, dict[str, Any], str, str]:
        reservation = self._store.reserve_ask(
            work_key=key,
            day=self._clock().astimezone(timezone.utc).date().isoformat(),
            worst_case_micros=ask_worst_case_micros(
                body, self._config.prompt_price_micros_per_million_tokens
            ),
            daily_attempt_cap=DAILY_ATTEMPT_CAP,
            daily_limit_micros=self._config.daily_limit_micros,
            ask_pool_micros=self._pool,
        )
        if reservation is None:
            raise ToolError(
                "daily_ask_budget_exhausted", "today's Jev ask budget is spent"
            )
        request_hash = self._put(body)
        try:
            status, response = self._transport.post(body, timeout=TIMEOUT_SECONDS)
        except AmbiguousTimeout as error:
            self._store.settle_attempt(reservation, "uncertain")
            raise ToolError("jev_unavailable", "Jev did not answer in time") from error
        except ConnectionFailed as error:
            self._store.settle_attempt(reservation, "known_rejected")
            raise ToolError("jev_unavailable", "Jev could not be reached") from error
        if not 200 <= status < 300:
            self._store.settle_attempt(reservation, "known_rejected")
            raise ToolError("jev_unavailable", f"Jev refused the ask ({status})")
        self._store.settle_attempt(reservation, "known_completed")
        if len(response) > MAX_ARTIFACT_BYTES:
            raise ToolError("jev_unavailable", "Jev's answer is too large")
        response_hash = self._put(response)
        try:
            returned_model, answer = parse_ask_response(arguments, response)
        except InvalidResponse as error:
            raise ToolError("jev_unavailable", str(error)) from error
        return returned_model, answer, request_hash, response_hash

    def _put(self, raw: bytes) -> str:
        digest = sha256_hex(raw)
        self._artifacts.commit(
            (raw,),
            expected_hash=digest,
            expected_length=len(raw),
            maximum_length=MAX_ARTIFACT_BYTES,
        )
        return digest

    def _state(
        self, about: Mapping[str, str], snapshot_hash: str
    ) -> tuple[str, str | None]:
        """The text Jev reads and the pinned artifact it came from."""

        if about["kind"] == "self":
            return about["text"], None
        if about["kind"] == "section":
            return self._section(snapshot_hash, about["paper_id"], about["section"])
        return self._passage(snapshot_hash, about["paper_id"], about["passage_id"])

    def _section(
        self, snapshot_hash: str, paper_id: str, section: str
    ) -> tuple[str, str]:
        member = pinned_family(self._storage, snapshot_hash, paper_id)
        cards = self._storage.snapshot_cards(
            snapshot_hash, paper_ids=(UUID(str(member["paper_version_id"])),)
        ).data["cards"]
        overview = cards[0]["overview"]
        if overview["abstract"] is not None:
            body = overview["abstract"]
        elif section == "overview":
            body = "\n\n".join(span["text"] for span in overview["spans"])
        else:
            raise ToolError(
                "section_unavailable", "the paper's card carries no abstract"
            )
        return f"{overview['title']}\n\n{body}", str(member["card_hash"])

    def _passage(
        self, snapshot_hash: str, paper_id: str, passage_id: str
    ) -> tuple[str, str]:
        handle = self._index.handle(snapshot_hash)
        member = handle.member(paper_id)
        if member is None:
            raise ToolError("not_in_snapshot", "paper family is not in this snapshot")
        candidates = handle.passage_candidates(
            member, storage=self._storage, texts=self._texts, tokenizer=self._tokenizer
        )
        if candidates is None:
            raise ToolError("text_unavailable", "the paper's passages cannot be read")
        for candidate in candidates:
            if candidate.text_hash == passage_id:
                return candidate.text, passage_id
        raise ToolError("not_in_snapshot", "the passage is not in this snapshot")
