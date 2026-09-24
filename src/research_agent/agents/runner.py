"""Execute one stored run specification end to end (AG-08, #279).

:func:`run_agent` is the one production caller of
``agents/loop.py#run_conversation``. It loads what the run drives through
storage -- the run's genome prompt, budgets, allowed tools, paper and
issued questions (``GET /v1/runs/{id}/worker``) and the description of the
snapshot it names (``GET /v1/snapshots/{id}``) -- builds the system and
first messages (AG-24, AG-25), and runs the conversation against the shared
tool service bound to that snapshot (PL-20, PL-21). Every request and
response is appended to the run's events by hash before the loop goes on
(AG-29). When the loop ends, the run's outcome is written: an accepted
submit was already sealed by the tool service's submit handler (AG-26), any
other ending voids the run with the loop's reason (AG-15), and either way
the run's one settlement records the tokens it received (#251).

A run whose snapshot storage does not hold, or which already ended, is
refused before anything is sent to the model or written.

The runner holds two storage principals: the orchestrator's, for its own
reads and writes, and the tool service's, which answers the run's tool
calls in this process. ``main`` composes both, the pinned agent model and
the tool service's collaborators; ``bin/run-agent`` runs it for one run.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from research_agent.agents.loop import (
    ModelClient,
    RunOutcome,
    run_conversation,
)
from research_agent.agents.messages import (
    SnapshotDescription,
    TokenCounter,
    assemble_system_prompt,
    build_initial_message,
)
from research_agent.agents.model_client import (
    AGENT_MODEL_ID,
    AGENT_PROVIDER,
    UNPINNED_REVISION,
    AgentDeploymentManifest,
    HttpxChatCompletionsTransport,
    InferenceOnlyClient,
    load_token_counter,
)
from research_agent.agents.transcript import RecordingFailed
from research_agent.contracts.canonical import sha256_hex
from research_agent.contracts.tools import TOOL_SCHEMAS
from research_agent.reader.chunk import SectionTokenizer
from research_agent.reader.media import PageRenderer, SubprocessPageRenderer
from research_agent.storage.client import (
    CommandResult,
    RunWorkerRecord,
    StorageClient,
    StorageClientError,
    StorageTransportError,
)
from research_agent.storage.client import (
    SnapshotDescription as StoredSnapshot,
)
from research_agent.tools.deep_read import DeepReadHandler
from research_agent.tools.graph import GraphHandler
from research_agent.tools.lookup import StorageSnapshotMembership
from research_agent.tools.neighbors import NeighborsHandler
from research_agent.tools.query_cards import QueryCardsHandler, QueryEmbedder
from research_agent.tools.service import (
    RunSpecifications,
    RunToolDispatcher,
    ToolService,
)
from research_agent.tools.snapshots import SnapshotIndex
from research_agent.tools.submit import SubmitHandler
from research_agent.tools.text import PinnedTexts
from research_agent.tools.trace import TraceWriter

__all__ = [
    "ORCHESTRATOR_SCOPES",
    "TOOL_SCOPES",
    "RunRefused",
    "StorageRunEventSink",
    "build_tool_service",
    "run_agent",
    "main",
]

#: What the runner itself reads and writes, as the orchestrator (#306).
ORCHESTRATOR_SCOPES = frozenset(
    {
        "runs:worker",
        "snapshots:read",
        "runs:append_event",
        "runs:void",
        "settlements:record",
    }
)
#: What the in-process tool service reads and writes, as ``tools`` (#287).
TOOL_SCOPES = frozenset(
    {
        "snapshots:read",
        "runs:specification",
        "runs:submit",
        "trace:request",
        "trace:terminal",
        "paper_requests:record",
    }
)


#: The attempt a run's events are appended under. It counts executions of
#: one run and starts at 1; the slot's zero-based ``attempt`` instead names
#: which run of the slot this is, and each has its own run id. A run is
#: executed once: an ended run is refused, never executed again.
EXECUTION_ATTEMPT = 1


class RunRefused(Exception):
    """The run cannot start; nothing was sent to the model or written."""


class WorkerStorage(Protocol):
    """The orchestrator-role storage calls one run makes."""

    def read_run_worker(self, run_id: UUID) -> RunWorkerRecord: ...

    def read_snapshot(self, snapshot_hash: str) -> StoredSnapshot: ...

    def append_run_event(
        self,
        *,
        run_id: UUID,
        attempt: int,
        ordinal: int,
        kind: str,
        payload_hash: str,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult: ...

    def void_run(
        self,
        *,
        run_id: UUID,
        reason: str,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult: ...

    def record_settlement(
        self,
        *,
        run_id: UUID,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        usage_source: str,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult: ...


class StorageRunEventSink:
    """Appends each exchange to the run's events, by payload hash (AG-29).

    A storage refusal or a lost connection is :class:`RecordingFailed`, which
    ends the run void rather than sending an unrecorded request.
    """

    def __init__(self, storage: WorkerStorage) -> None:
        self._storage = storage

    def append(
        self, *, run_id: str, attempt: int, ordinal: int, kind: str, payload: bytes
    ) -> None:
        try:
            self._storage.append_run_event(
                run_id=UUID(run_id),
                attempt=attempt,
                ordinal=ordinal,
                kind=kind,
                payload_hash=sha256_hex(payload),
                **_command_ids(),
            )
        except (StorageClientError, StorageTransportError) as error:
            raise RecordingFailed(str(error)) from error


def build_tool_service(
    storage: StorageClient,
    *,
    embedder: QueryEmbedder,
    tokenizer: SectionTokenizer,
    renderer: PageRenderer,
) -> ToolService:
    """The shared tool service with its five handlers over a ``tools`` client."""

    index = SnapshotIndex(storage)
    texts = PinnedTexts(storage)
    return ToolService(
        specifications=storage,
        handlers={
            "query_cards": QueryCardsHandler(
                storage=storage,
                index=index,
                embedder=embedder,
                texts=texts,
                tokenizer=tokenizer,
            ),
            "neighbors": NeighborsHandler(storage=storage, index=index),
            "graph": GraphHandler(storage=storage),
            "deep_read": DeepReadHandler(
                texts=texts, tokenizer=tokenizer, renderer=renderer
            ),
            "submit": SubmitHandler(storage=storage),
        },
        membership=StorageSnapshotMembership(storage),
        paper_requests=storage,
        trace=TraceWriter(storage),
    )


def run_agent(
    run_id: UUID,
    *,
    storage: WorkerStorage,
    specifications: RunSpecifications,
    service: ToolService,
    model_client: Callable[[str], ModelClient],
    count_tokens: TokenCounter,
    elapsed_seconds: Callable[[], float] | None = None,
) -> RunOutcome:
    """Run *run_id* once, from its stored specification to its terminal rows.

    ``model_client`` builds the pinned agent model for this run's id;
    ``specifications`` is the tool service's read of the run, used here only
    to refuse a run that already ended. Raises :class:`RunRefused` when the
    run's snapshot is not sealed in storage or the run is no longer active.
    """

    worker = storage.read_run_worker(run_id)
    try:
        stored = storage.read_snapshot(worker.snapshot_hash)
    except StorageClientError as error:
        if error.status_code != 404:
            raise
        raise RunRefused(
            f"run {run_id} names snapshot {worker.snapshot_hash}, "
            "which storage does not hold"
        ) from error
    if not specifications.read_run_specification(run_id).active:
        raise RunRefused(f"run {run_id} has already ended")

    system_message = assemble_system_prompt(worker.prompt)
    initial_message = build_initial_message(
        paper_id=worker.paper_id,
        questions=[
            {"question_id": question_id} for question_id in worker.issued_question_ids
        ],
        budgets=dict(worker.budgets),
        snapshot=SnapshotDescription(
            snapshot_hash=stored.snapshot_hash,
            sealed_at=stored.sealed_at,
            paper_count=stored.pinned_family_count,
        ),
    )

    def settle(outcome: RunOutcome) -> None:
        # An accepted submit already holds the run's terminal row (AG-26).
        if outcome.status != "submitted":
            assert outcome.reason is not None
            storage.void_run(
                run_id=run_id,
                reason=outcome.reason,
                **_command_ids(),
            )
        storage.record_settlement(
            run_id=run_id,
            provider=AGENT_PROVIDER,
            model=AGENT_MODEL_ID,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            usage_source=outcome.usage_source,
            **_command_ids(),
        )

    return run_conversation(
        run_id=str(run_id),
        attempt=EXECUTION_ATTEMPT,
        system_message=system_message,
        initial_message=initial_message,
        allowed_tools=worker.allowed_tools,
        client=model_client(str(run_id)),
        dispatcher=RunToolDispatcher(service, snapshot_id=worker.snapshot_hash),
        sink=StorageRunEventSink(storage),
        count_tokens=count_tokens,
        elapsed_seconds=elapsed_seconds,
        settle=settle,
    )


def _command_ids() -> dict[str, UUID]:
    return {"command_id": uuid4(), "request_id": uuid4(), "idempotency_key": uuid4()}


def _storage_client(
    args: argparse.Namespace, certificate: str, key: str, scopes: frozenset[str]
) -> StorageClient:
    return StorageClient(
        connect_host=args.storage_host,
        port=args.storage_port,
        server_hostname=args.storage_server_name,
        ca_file=Path(args.ca_file),
        client_cert_file=Path(certificate),
        client_key_file=Path(key),
        scopes=scopes,
    )


def _embedding_tokenizer(cache_dir: str | None) -> SectionTokenizer:
    """The pinned embedding model's tokenizer, from the local cache only."""

    from huggingface_hub import snapshot_download
    from transformers import AutoTokenizer

    from research_agent.models.batch import OffsetTokenizer
    from research_agent.models.manifest import MODEL_ID, REVISION

    snapshot = snapshot_download(
        MODEL_ID, revision=REVISION, cache_dir=cache_dir, local_files_only=True
    )
    return OffsetTokenizer(AutoTokenizer.from_pretrained(snapshot))


def main(argv: list[str] | None = None) -> int:
    from research_agent.models.client import ModelServiceClient
    from research_agent.platform.profile import LaunchProfile

    parser = argparse.ArgumentParser(description="Execute one stored run.")
    parser.add_argument("--run-id", required=True, type=UUID)
    parser.add_argument("--profile", required=True, help="launch profile JSON")
    parser.add_argument("--endpoint", required=True, help="agent chat-completions URL")
    parser.add_argument("--revision", default=UNPINNED_REVISION)
    parser.add_argument("--api-key-env", default="ZAI_API_KEY")
    parser.add_argument(
        "--processor-dir", required=True, help="the agent model's tokenizer"
    )
    parser.add_argument("--cache-dir", default=None, help="embedding model cache")
    parser.add_argument("--storage-host", required=True)
    parser.add_argument("--storage-port", required=True, type=int)
    parser.add_argument("--storage-server-name", required=True)
    parser.add_argument("--model-service-host", required=True)
    parser.add_argument("--model-service-port", required=True, type=int)
    parser.add_argument("--model-service-server-name", required=True)
    parser.add_argument("--ca-file", required=True)
    parser.add_argument("--orchestrator-cert", required=True)
    parser.add_argument("--orchestrator-key", required=True)
    parser.add_argument("--tools-cert", required=True)
    parser.add_argument("--tools-key", required=True)
    args = parser.parse_args(argv)

    api_key = os.environ.get(args.api_key_env, "")
    if not api_key:
        parser.error(f"set {args.api_key_env} in the environment")
    profile = LaunchProfile.from_json(Path(args.profile).read_bytes())
    manifest = AgentDeploymentManifest(
        provider=profile.model.agent_provider,
        model_id=profile.model.agent_model_id,
        endpoint=args.endpoint,
        revision=args.revision,
        qualified=profile.model.agent_qualification_passed,
    )
    transport = HttpxChatCompletionsTransport(endpoint=args.endpoint, api_key=api_key)
    tools = _storage_client(args, args.tools_cert, args.tools_key, TOOL_SCOPES)
    service = build_tool_service(
        tools,
        embedder=ModelServiceClient(
            connect_host=args.model_service_host,
            port=args.model_service_port,
            server_hostname=args.model_service_server_name,
            ca_file=Path(args.ca_file),
            client_cert_file=Path(args.tools_cert),
            client_key_file=Path(args.tools_key),
        ),
        tokenizer=_embedding_tokenizer(args.cache_dir),
        renderer=SubprocessPageRenderer(),
    )

    def model_client(run_id: str) -> ModelClient:
        return InferenceOnlyClient(
            run_id=run_id,
            manifest=manifest,
            transport=transport,
            api_key=api_key,
            tool_schemas=TOOL_SCHEMAS,
        )

    try:
        outcome = run_agent(
            args.run_id,
            storage=_storage_client(
                args,
                args.orchestrator_cert,
                args.orchestrator_key,
                ORCHESTRATOR_SCOPES,
            ),
            specifications=tools,
            service=service,
            model_client=model_client,
            count_tokens=load_token_counter(Path(args.processor_dir)),
        )
    except RunRefused as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return 2
    finally:
        transport.close()
    summary: Mapping[str, Any] = {
        "run_id": str(args.run_id),
        "status": outcome.status,
        "reason": outcome.reason,
        "exchanges": outcome.exchange_count,
        "input_tokens": outcome.input_tokens,
        "output_tokens": outcome.output_tokens,
        "usage_source": outcome.usage_source,
    }
    print(" ".join(f"{key}={value}" for key, value in summary.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
