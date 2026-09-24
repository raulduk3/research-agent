"""Acquire, read, embed and card the papers agents requested (decision 0025).

The acquisition side of TDD-3.1.78. ``acquire_requests`` lists the open
requests under the ingest role (oldest first, ties by family) and starts
each one through storage, which refuses the row once the UTC day has started
``MAX_ACQUISITIONS_PER_UTC_DAY``. A started request is carried through the
owners that already exist, by ``RequestReader``:

1. its family id is resolved against the arXiv listing's identities;
2. the existing ``documents`` capture job fetches source and PDF under the
   arXiv request rules, on the same worker and gate as the daily batch;
3. ``reader.extract`` extracts it, through the same export the corpus
   batch uses, and the paper record is published with ``requested_by``
   naming the request, beside the extraction record itself, whose content
   hash is the card's ``extraction_hash``;
4. every paper read in this pass is embedded in one ``embed-batch`` run
   (``models.batch.run_batch``), never one call per paper, and published
   with ``retrieval.passages.publish_index``;
5. ``reader.cards.assemble_card`` builds the card, with the family's
   citation edges where the snapshot channel has them, the paper's own
   overview vector beside the overview vectors of the snapshot's pinned
   items (so the earlier neighbors and both distances are computed), and
   the bibliography entries its extraction holds as the parsed references;
   ``models.embedding_view`` builds the paper's embedding view beside it,
   stored as an artifact derived from the index entry (#298).

Only then is the request marked ``acquired``, naming its paper version; any
failure on the way marks it ``failed`` with the reason and publishes no
card. The report's acquired items are what the next snapshot seal adds
(``snapshots.compose``); the snapshot the request was made from is never
touched.

Steps 3 to 5 read from a committed ``documents`` job, not from a request:
``ingest.daily.card_day_papers`` carries the day's own papers through the
same ``read_committed``, ``embed`` and ``card``, with no ``requested_by``
and the head slots of a first-public paper on its own day.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from research_agent.assessments.rubric import Rubric
from research_agent.contracts import RecordMeta, canonical_json, canonical_loads
from research_agent.contracts.cards import (
    AvailabilityValue,
    CardBuildInput,
    CardOverview,
    HeadCardValue,
    PaperCardBody,
)
from research_agent.contracts.canonical import sha256_hex
from research_agent.contracts.papers import ExternalIdentifier, PaperVersionRecord
from research_agent.contracts.passages import SourceLocator
from research_agent.ingest.arxiv import ArxivListing
from research_agent.ingest.bibliography import parse_identified_references
from research_agent.ingest.pilot import PilotWorker, derived_uuid, utc_now
from research_agent.ingest.pilot_local import LocalStorage
from research_agent.learning.text_export import (
    PDF_EXTRACTOR_MANIFEST_HASH,
    PdfReader,
    _extract,
    _retained,
    read_pdf_pages,
)
from research_agent.models.batch import (
    PaperText,
    PlatformIdentity,
    paper_batch_path,
    paper_text_path,
    read_paper_batch,
    run_batch,
)
from research_agent.models.embedding import FrozenEmbedder
from research_agent.models.embedding_view import (
    NeighborCandidate,
    PaperIdentity,
    build_embedding_view,
    load_candidates,
)
from research_agent.models.neighbors import OverviewVector
from research_agent.outcomes.targets import definitions as target_definitions
from research_agent.reader.assessments import assessment_section
from research_agent.reader.cards import CardVectors, assemble_card
from research_agent.reader.chunk import SectionTokenizer
from research_agent.reader.rendering import render_card
from research_agent.retrieval.passages import (
    IndexEntry,
    PublishedPassage,
    build_passages,
    publish_index,
)
from research_agent.storage.client import CommandResult, PaperRequestRecord
from research_agent.storage.embedding_views import EmbeddingViewRepository
from research_agent.storage.requests import MAX_ACQUISITIONS_PER_UTC_DAY

__all__ = [
    "MAX_ACQUISITIONS_PER_UTC_DAY",
    "AcquisitionFailed",
    "AcquisitionReport",
    "CitationEdges",
    "DocumentJob",
    "LocalEmbeddingViews",
    "ReadPaper",
    "RequestLedger",
    "RequestReader",
    "acquire_requests",
    "listing_identities",
    "paper_identities",
]

#: A requested paper sits outside the drawn population, so no prediction
#: head speaks for it (decision 0025): its head slots say so.
HEAD_UNAVAILABLE_REASON = "disabled_by_profile"
#: It reached the corpus after the snapshot that asked for it.
HEAD_FORECAST_ELIGIBILITY = "late_arrival"

#: arXiv id -> (incoming, outgoing) paper family ids, where the snapshot
#: channel has the family's edges; ``None`` where it has none.
CitationEdges = Callable[[str], tuple[tuple[str, ...], tuple[str, ...]] | None]


class RequestLedger(Protocol):
    """The ingest role's paper-request routes (``StorageClient``)."""

    def list_open_paper_requests(self) -> tuple[PaperRequestRecord, ...]: ...

    def transition_paper_request(
        self,
        *,
        paper_request_id: UUID,
        status: str,
        reason: str | None,
        paper_version_id: UUID | None,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult: ...


class _Canonical(Protocol):
    def to_canonical_json(self) -> bytes: ...


def _json(record: _Canonical) -> dict[str, Any]:
    """A record as the object ``publish_spec`` stores byte for byte."""

    return cast(dict[str, Any], canonical_loads(record.to_canonical_json()))


def listing_identities(records: Iterable[ArxivListing]) -> dict[str, ArxivListing]:
    """Paper family id -> its arXiv listing record: the listing identity pass.

    A request names a family by the id every snapshot uses for it, derived
    from its canonical arXiv id; this inverts that over listed records.
    """

    return {
        str(derived_uuid("gate-paper-family", record.family_id)): record
        for record in records
        if not record.legacy_identifier
    }


def paper_identities(
    identities: Mapping[str, ArxivListing],
) -> dict[str, PaperIdentity]:
    """Paper version id -> what an embedding view names it by.

    ``identities`` is ``listing_identities``' map; each listed family's
    version is the one ``RequestReader.read_committed`` records for it.
    """

    return {
        str(derived_uuid("gate-paper-version", listing.family_id)): PaperIdentity(
            family_id, listing.title, listing.first_public_at
        )
        for family_id, listing in identities.items()
    }


class LocalEmbeddingViews:
    """Stores embedding views as artifacts and records each against its paper.

    The sink ``models.equivalence.import_batch`` takes (``EmbeddingViewSink``);
    ``RequestReader`` stores its own views through the same one.
    """

    def __init__(
        self, storage: LocalStorage, identities: Mapping[str, PaperIdentity]
    ) -> None:
        self._storage = storage
        self._identities = identities
        self._views = EmbeddingViewRepository(storage.database, storage.artifacts)

    def identities(self) -> Mapping[str, PaperIdentity]:
        return self._identities

    def store(self, view: Mapping[str, Any], input_hashes: tuple[str, ...]) -> str:
        view_hash = self._storage.publish_spec(dict(view), input_hashes)
        self._views.record(view_hash)
        return view_hash


class AcquisitionFailed(Exception):
    """One request's paper could not be carried through; ``reason`` says why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason[:512]


#: Job id, state and report manifest of one ``documents`` job.
DocumentJob = tuple[str, str, str | None]


@dataclass(frozen=True, slots=True)
class ReadPaper:
    """A paper fetched, extracted and recorded, not yet embedded."""

    listing: ArxivListing
    paper: PaperVersionRecord
    paper_hash: str
    text: PaperText


@dataclass(frozen=True, slots=True)
class AcquisitionReport:
    """One acquisition pass: snapshot items acquired, and what was not."""

    acquired: tuple[dict[str, Any], ...] = ()
    failed: tuple[tuple[str, str], ...] = ()
    refused: tuple[str, ...] = field(default=())


def _parsed_reference_count(
    paper: PaperVersionRecord, text: str, outgoing: tuple[str, ...] | None
) -> int:
    """How many references the paper's bibliography holds.

    The ``\\bibitem`` entries of the extraction's canonical text, read by the
    bibliography parser with no identity index so every entry counts once.
    A family the snapshot channel says the paper cites is a reference too,
    so the count is never below the distinct cited families: a PDF has no
    parsed entries, and its cited families still partition into those with
    a vector and those without.
    """

    entries = parse_identified_references(
        text,
        source_hash=paper.original_source_hash,
        citing_family_id=paper.family_id,
        identity_index={},
        captured_at=paper.created_at,
    ).unmatched
    return max(len(entries), 0 if outgoing is None else len(set(outgoing)))


def _move(
    ledger: RequestLedger,
    request: PaperRequestRecord,
    status: str,
    *,
    reason: str | None = None,
    paper_version_id: UUID | None = None,
) -> str:
    # One key per request and target status: a pass that dies after storage
    # committed a move replays that answer instead of moving the row twice.
    key = derived_uuid("paper-request-transition", request.request_id, status)
    answer = ledger.transition_paper_request(
        paper_request_id=request.request_id,
        status=status,
        reason=reason,
        paper_version_id=paper_version_id,
        command_id=key,
        request_id=uuid4(),
        idempotency_key=key,
    )
    return str(answer.data["status"])


def acquire_requests(ledger: RequestLedger, reader: RequestReader) -> AcquisitionReport:
    """Start, read, embed and card every open request the day's budget admits."""

    started: list[PaperRequestRecord] = []
    refused: list[str] = []
    for request in ledger.list_open_paper_requests():
        # An acquiring row is one a stopped pass already started: resume it.
        if request.status == "requested" and _move(ledger, request, "acquiring") != (
            "acquiring"
        ):
            refused.append(str(request.request_id))
            continue
        started.append(request)
    failed: list[tuple[str, str]] = []

    def fail(request: PaperRequestRecord, reason: str) -> None:
        _move(ledger, request, "failed", reason=reason)
        failed.append((str(request.request_id), reason))

    papers: list[tuple[PaperRequestRecord, ReadPaper]] = []
    for request, outcome in reader.read(started).items():
        if isinstance(outcome, AcquisitionFailed):
            fail(request, outcome.reason)
        else:
            papers.append((request, outcome))
    acquired: list[dict[str, Any]] = []
    indexes = reader.embed([paper for _, paper in papers])
    for request, paper in papers:
        try:
            indexed = indexes[paper.paper.version_id]
            if isinstance(indexed, AcquisitionFailed):
                raise indexed
            item = reader.card(paper, indexed)
        except AcquisitionFailed as failure:
            fail(request, failure.reason)
            continue
        _move(
            ledger,
            request,
            "acquired",
            paper_version_id=UUID(paper.paper.version_id),
        )
        acquired.append(item)
    return AcquisitionReport(tuple(acquired), tuple(failed), tuple(refused))


class RequestReader:
    """Carries started requests through the existing document-to-card owners.

    ``snapshot_items`` are the items pinned in the snapshot the pass reads
    against; their cards and published index entries are the candidates a
    new card's earlier neighbors and reference centroid are drawn from.
    """

    def __init__(
        self,
        storage: LocalStorage,
        worker: PilotWorker,
        *,
        identities: Mapping[str, ArxivListing],
        work_dir: Path,
        namespace_dir: Path,
        embedder: FrozenEmbedder,
        tokenizer: SectionTokenizer,
        platform: PlatformIdentity,
        citation_edges: CitationEdges = lambda _family: None,
        snapshot_items: Sequence[Mapping[str, Any]] = (),
        pdf_reader: PdfReader = read_pdf_pages,
    ) -> None:
        self._storage = storage
        self._worker = worker
        self._identities = identities
        self._work_dir = work_dir
        self._namespace_dir = namespace_dir
        self._embedder = embedder
        self._tokenizer = tokenizer
        self._platform = platform
        self._citation_edges = citation_edges
        self._snapshot_items = tuple(snapshot_items)
        self._snapshot_overviews: tuple[OverviewVector, ...] | None = None
        self._pdf_reader = pdf_reader
        self._views = LocalEmbeddingViews(storage, paper_identities(identities))
        self._candidates: dict[str, NeighborCandidate] = {}

    # --- documents and extraction ------------------------------------------

    def read(
        self, requests: Sequence[PaperRequestRecord]
    ) -> dict[PaperRequestRecord, ReadPaper | AcquisitionFailed]:
        """Fetch and extract every request's paper; one worker pass for all."""

        outcomes: dict[PaperRequestRecord, ReadPaper | AcquisitionFailed] = {}
        listings: dict[PaperRequestRecord, ArxivListing] = {}
        for request in requests:
            listing = self._identities.get(str(request.family_id))
            if listing is None:
                outcomes[request] = AcquisitionFailed("unresolved_family")
            else:
                listings[request] = listing
        jobs = self._document_jobs(requested=True)
        for request, listing in listings.items():
            if str(request.request_id) not in jobs:
                self._storage.enqueue(
                    {
                        "stage": "documents",
                        "family": {
                            "family_id": listing.family_id,
                            "license_url": listing.license_url,
                        },
                        "request_id": str(request.request_id),
                    }
                )
        if listings:
            self._worker.run()
            jobs = self._document_jobs(requested=True)
        for request, listing in listings.items():
            try:
                outcomes[request] = self.read_committed(
                    listing,
                    jobs.get(str(request.request_id)),
                    requested_by=str(request.request_id),
                )
            except AcquisitionFailed as failure:
                outcomes[request] = failure
        return outcomes

    def day_jobs(self) -> dict[str, DocumentJob]:
        """arXiv family id -> the day's own documents job for it (no request)."""

        return self._document_jobs(requested=False)

    def _document_jobs(self, *, requested: bool) -> dict[str, DocumentJob]:
        """Documents jobs keyed by request id, or by arXiv family id for the
        jobs no request enqueued."""

        rows = self._storage.database.transaction(
            lambda connection: connection.execute(
                """SELECT j.id, j.state, encode(j.input_manifest_hash,'hex'),
                          encode(o.artifact_hash,'hex')
                   FROM jobs j LEFT JOIN job_outputs o ON o.job_id=j.id
                   ORDER BY j.scheduled_at, j.id"""
            ).fetchall()
        )
        jobs: dict[str, DocumentJob] = {}
        for job_id, state, manifest, output in rows:
            spec = self._storage.report(str(manifest))
            if spec.get("stage") != "documents" or ("request_id" in spec) != requested:
                continue
            key = spec["request_id"] if requested else spec["family"]["family_id"]
            jobs[str(key)] = (
                str(job_id),
                str(state),
                None if output is None else str(output),
            )
        return jobs

    def carded(self, report_manifest: str) -> dict[str, Any] | None:
        """The snapshot item of a card already built from this documents
        report, or ``None``: a paper is carded from its job once."""

        rows = self._storage.database.transaction(
            lambda connection: connection.execute(
                """SELECT encode(paper.manifest_hash,'hex'),
                          encode(child.manifest_hash,'hex')
                   FROM artifact_production_edges paper
                   JOIN artifact_productions made
                     ON made.manifest_hash = paper.manifest_hash
                   JOIN artifact_production_edges child
                     ON child.input_hash = paper.manifest_hash
                   WHERE paper.input_hash = decode(%s,'hex')
                   ORDER BY made.created_at, paper.manifest_hash,
                            child.manifest_hash""",
                (report_manifest,),
            ).fetchall()
        )
        built: dict[str, dict[str, str]] = {}
        for paper_hash, child_hash in rows:
            body = self._storage.report(str(child_hash))
            kind = "card" if "head_predictions" in body else "index"
            built.setdefault(str(paper_hash), {})[kind] = str(child_hash)
        for children in built.values():
            if {"card", "index"} <= set(children):
                card = self._storage.report(children["card"])
                return {
                    "paper_family_id": card["paper_family_id"],
                    "paper_version_id": card["paper_version_id"],
                    "card_hash": children["card"],
                    "overview_hash": None,
                    "passage_index_hash": children["index"],
                    "graph_hash": None,
                }
        return None

    def read_committed(
        self,
        listing: ArxivListing,
        job: DocumentJob | None,
        *,
        requested_by: str | None,
    ) -> ReadPaper:
        """Extract a committed documents job's paper and publish its record.

        ``requested_by`` names the request that asked for the paper and is
        ``None`` for a paper of the day's own listing.
        """

        if job is None or job[1] != "committed" or job[2] is None:
            raise AcquisitionFailed(
                "documents job did not commit"
                if job is None
                else f"documents job {job[1]}"
            )
        job_id, _, report_manifest = job
        assert report_manifest is not None
        report = self._storage.report(report_manifest)
        if report.get("src") != "retained" and report.get("pdf") != "retained":
            raise AcquisitionFailed(
                f"fetch failed: source {report.get('src')}, pdf {report.get('pdf')}"
            )
        version_id = str(derived_uuid("gate-paper-version", listing.family_id))
        retained = _retained(self._storage, job_id, listing.family_id)
        try:
            record, text = _extract(
                self._storage, version_id, retained, self._pdf_reader
            )
        except Exception as error:  # a reader defect fails this request only
            raise AcquisitionFailed(
                f"extraction failed: {type(error).__name__}: {error}"
            ) from error
        if record.coverage == "unavailable":
            raise AcquisitionFailed(
                "extraction unavailable: " + ",".join(record.coverage_reasons)
            )
        if sha256_hex(text.encode("utf-8")) != record.text_hash:
            raise AcquisitionFailed("canonical text does not match the extraction")
        identity = self._storage.identity
        evidence = sha256_hex(
            canonical_json(
                {
                    "family_id": listing.family_id,
                    "first_public_at": listing.first_public_at,
                }
            )
        )
        paper = PaperVersionRecord(
            schema_version=1,
            input_hashes=(report_manifest,),
            producer_version=identity.producer,
            config_hash=identity.config_hash,
            created_at=utc_now(),
            family_id=str(derived_uuid("gate-paper-family", listing.family_id)),
            version_id=version_id,
            external_ids=(ExternalIdentifier("arxiv", f"{listing.family_id}v1"),),
            is_first_public_version=True,
            first_public_at=listing.first_public_at,
            first_public_interval=None,
            first_public_evidence_hashes=(evidence,),
            source_access_hashes=(report_manifest,),
            title=listing.title,
            abstract=listing.abstract,
            author_ids=(),
            primary_source_subfield=None,
            original_source_hash=record.source_hash,
            text_source_kind="pdf"
            if record.extractor_manifest_hash == PDF_EXTRACTOR_MANIFEST_HASH
            else "latex",
            source_revision="v1",
            author_count=listing.author_count,
            categories=listing.categories,
            version_count=len(listing.versions),
            requested_by=requested_by,
        )
        paper_hash = self._storage.publish_spec(_json(paper), (report_manifest,))
        # Stored byte for byte as its canonical JSON, so the artifact's content
        # hash is the ``extraction_hash`` the card records and a snapshot read
        # resolves the extraction through it (#304).
        self._storage.publish_spec(_json(record), (report_manifest,))
        return ReadPaper(
            listing,
            paper,
            paper_hash,
            PaperText(
                paper_version_id=version_id,
                title=listing.title,
                abstract=listing.abstract,
                extraction_hash=sha256_hex(record.to_canonical_json()),
                canonical_text=text,
                extraction=record,
            ),
        )

    # --- embedding ---------------------------------------------------------

    def embed(
        self, papers: Sequence[ReadPaper]
    ) -> dict[str, IndexEntry | AcquisitionFailed]:
        """Embed every paper in one ``embed-batch`` run and publish its index.

        Keyed by paper version id.
        """

        if not papers:
            return {}
        batch = sha256(
            canonical_json(sorted(paper.text.paper_version_id for paper in papers))
        ).hexdigest()
        text_dir = self._work_dir / "text" / batch
        out_dir = self._work_dir / "vectors" / batch
        text_dir.mkdir(parents=True, exist_ok=True)
        for paper in papers:
            paper_text_path(text_dir, paper.text.paper_version_id).write_bytes(
                paper.text.to_canonical_json()
            )
        manifest = run_batch(
            text_dir, out_dir, self._embedder, self._tokenizer, self._platform
        )
        indexed: dict[str, IndexEntry | AcquisitionFailed] = {}
        for paper in papers:
            version_id = paper.text.paper_version_id
            if version_id not in manifest.file_hashes:
                indexed[version_id] = AcquisitionFailed(
                    "embedding failed: "
                    + manifest.failed.get(version_id, "no vectors written")
                )
                continue
            vectors = read_paper_batch(paper_batch_path(out_dir, version_id))
            entry = IndexEntry(
                paper_version_id=version_id,
                extraction_hash=vectors.extraction_hash,
                chunk_policy=vectors.chunk_policy,
                coverage=vectors.coverage,
                coverage_reasons=vectors.coverage_reasons,
                overview_vector=vectors.overview_vector,
                passages=tuple(
                    PublishedPassage(p.passage_order, p.text_hash, p.vector)
                    for p in vectors.passages
                ),
                platform=self._platform.to_dict(),
                equivalence=None,
            )
            publish_index(self._namespace_dir, entry)
            indexed[version_id] = entry
        return indexed

    # --- card --------------------------------------------------------------

    def _tokens(self, text: str) -> int:
        return len(self._tokenizer.encode_offsets(text))

    def _snapshot_vectors(self) -> tuple[OverviewVector, ...]:
        """The pinned items' overview vectors, read once per reader.

        Each comes from the item's published index entry, named by its card
        and dated by the card's ``as_of``, which follows the entry's
        publication. An item with no index entry, or a card with no
        representation or title, has no vector to offer and is skipped.
        """

        if self._snapshot_overviews is None:
            candidates: list[OverviewVector] = []
            for item in self._snapshot_items:
                if item.get("passage_index_hash") is None:
                    continue
                card = self._storage.report(str(item["card_hash"]))
                title = card.get("overview", {}).get("title")
                if card.get("representation_hash") is None or not title:
                    continue
                index = self._storage.report(str(item["passage_index_hash"]))
                candidates.append(
                    OverviewVector(
                        paper_family_id=str(item["paper_family_id"]),
                        paper_version_id=str(item["paper_version_id"]),
                        title=str(title),
                        card_id=str(item["card_hash"]),
                        first_public_at=card["first_public_at"],
                        corpus_arrival_at=card["as_of"],
                        available_at=card["as_of"],
                        representation_hash=card["representation_hash"],
                        vector=tuple(index["overview_vector"]),
                    )
                )
            self._snapshot_overviews = tuple(candidates)
        return self._snapshot_overviews

    def card(
        self,
        paper: ReadPaper,
        index: IndexEntry,
        *,
        heads: tuple[HeadCardValue, ...] | None = None,
        head_feature_unavailable_reason: str | None = HEAD_UNAVAILABLE_REASON,
    ) -> dict[str, Any]:
        """Assemble and publish the card; return the next snapshot's item.

        ``heads`` default to a requested paper's: no head speaks for it and
        its features feed none. The day's own papers pass their own slots
        and ``head_feature_unavailable_reason=None``.
        """

        record, text = paper.paper, paper.text
        as_of = utc_now()
        if heads is None:
            meta = RecordMeta(
                1,
                (),
                record.producer_version,
                record.config_hash,
                as_of,
            )
            heads = tuple(
                HeadCardValue(
                    definition.target_id,
                    sha256_hex(definition.to_canonical_json()),
                    definition.question,
                    None,
                    "unavailable",
                    HEAD_UNAVAILABLE_REASON,
                    None,
                    None,
                    None,
                    None,
                    HEAD_FORECAST_ELIGIBILITY,
                    None,
                )
                for definition in target_definitions(meta)
            )
        passages = build_passages(
            text.extraction, text.canonical_text, text.extraction_hash, self._tokenizer
        )
        edges = self._citation_edges(paper.listing.family_id)
        outgoing = None if edges is None else edges[1]
        vectors = CardVectors(index.overview_vector, self._snapshot_vectors())
        reference_count = _parsed_reference_count(record, text.canonical_text, outgoing)
        locator_kind = "pdf" if record.text_source_kind == "pdf" else "latex"

        def build(card_token_count: int) -> PaperCardBody:
            return assemble_card(
                CardBuildInput(
                    paper_family_id=record.family_id,
                    paper_version_id=record.version_id,
                    as_of=as_of,
                    corpus_arrival_at=as_of,
                    overview=CardOverview(
                        "complete", record.title, record.abstract, ()
                    ),
                    overview_available=True,
                    first_public_at=record.first_public_at,
                    original_source=SourceLocator(
                        record.original_source_hash,
                        locator_kind,
                        None,
                        None,
                        None,
                        None,
                    ),
                    passage_coverage=index.coverage,
                    passage_count=len(index.passages),
                    extraction_hash=text.extraction_hash,
                    representation_hash=self._embedder.manifest.representation_hash,
                    head_feature_eligible=head_feature_unavailable_reason is None,
                    head_feature_unavailable_reason=head_feature_unavailable_reason,
                    head_predictions=heads,
                    neighbors=(),
                    neighbor_arrivals=(),
                    neighbor_embedding_distance=AvailabilityValue.unavailable(
                        "no_neighbors"
                    ),
                    outcome_labels=(),
                    graph_incoming_family_ids=None if edges is None else edges[0],
                    graph_outgoing_family_ids=outgoing,
                    graph_parsed_reference_count=reference_count,
                    graph_matched_reference_ids=(),
                    graph_reference_vector_count=0,
                    graph_missing_reference_vector_count=0,
                    graph_reference_centroid_distance=AvailabilityValue.unavailable(
                        "missing_vector"
                    ),
                    graph_manifest_hash=None,
                    author_ids=(),
                    author_captures=(),
                    jev=assessment_section(
                        manifest=None,
                        result=None,
                        available_at=None,
                        paper_version_id=record.version_id,
                        extraction_hash=text.extraction_hash,
                        as_of=as_of,
                        snapshot_smoke_report_hash=None,
                        rubric_hash=Rubric.launch().rubric_hash,
                    ),
                    card_token_count=card_token_count,
                    author_count=record.author_count,
                    categories=record.categories,
                    version_count=record.version_count,
                    title_tokens=self._tokens(record.title),
                    abstract_tokens=self._tokens(record.abstract),
                    code_link=False,
                    passages=passages,
                ),
                vectors=vectors,
            )

        try:
            card = build(0)
            card = build(self._tokens(render_card(card)))
        except ValueError as error:
            raise AcquisitionFailed(
                f"card assembly failed: {type(error).__name__}: {error}"
            ) from error
        try:
            view = build_embedding_view(
                identity=PaperIdentity(
                    record.family_id, record.title, record.first_public_at
                ),
                text=text,
                entry=index,
                tokenizer=self._tokenizer,
                representation_hash=self._embedder.manifest.representation_hash,
                candidates=load_candidates(
                    self._namespace_dir,
                    self._views.identities(),
                    loaded=self._candidates,
                ),
            )
        except ValueError as error:
            raise AcquisitionFailed(
                f"embedding view failed: {type(error).__name__}: {error}"
            ) from error
        inputs = (paper.paper_hash,)
        card_hash = self._storage.publish_spec(_json(card), inputs)
        index_hash = self._storage.publish_spec(_json(index), inputs)
        self._views.store(view, (index_hash,))
        return {
            "paper_family_id": record.family_id,
            "paper_version_id": record.version_id,
            "card_hash": card_hash,
            "overview_hash": None,
            "passage_index_hash": index_hash,
            "graph_hash": None,
        }
