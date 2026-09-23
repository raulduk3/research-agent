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
   naming the request;
4. every paper read in this pass is embedded in one ``embed-batch`` run
   (``models.batch.run_batch``), never one call per paper, and published
   with ``retrieval.passages.publish_index``;
5. ``reader.cards.assemble_card`` builds the card, with the family's
   citation edges where the snapshot channel has them, the paper's own
   overview vector beside the overview vectors of the snapshot's pinned
   items (so the earlier neighbors and both distances are computed), and
   the bibliography entries its extraction holds as the parsed references.

Only then is the request marked ``acquired``, naming its paper version; any
failure on the way marks it ``failed`` with the reason and publishes no
card. The report's acquired items are what the next snapshot seal adds
(``snapshots.compose``); the snapshot the request was made from is never
touched.
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
from research_agent.models.neighbors import OverviewVector
from research_agent.outcomes.targets import definitions as target_definitions
from research_agent.reader.assessments import assessment_section
from research_agent.reader.cards import CardVectors, assemble_card
from research_agent.reader.chunk import SectionTokenizer
from research_agent.reader.rendering import render_card
from research_agent.retrieval.passages import (
    IndexEntry,
    PublishedPassage,
    publish_index,
)
from research_agent.storage.client import CommandResult, PaperRequestRecord
from research_agent.storage.requests import MAX_ACQUISITIONS_PER_UTC_DAY

__all__ = [
    "MAX_ACQUISITIONS_PER_UTC_DAY",
    "AcquisitionReport",
    "CitationEdges",
    "ReadPaper",
    "RequestLedger",
    "RequestReader",
    "acquire_requests",
    "listing_identities",
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


class AcquisitionFailed(Exception):
    """One request's paper could not be carried through; ``reason`` says why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason[:512]


@dataclass(frozen=True, slots=True)
class ReadPaper:
    """A requested paper fetched, extracted and recorded, not yet embedded."""

    request: PaperRequestRecord
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

    papers: list[ReadPaper] = []
    for request, outcome in reader.read(started).items():
        if isinstance(outcome, AcquisitionFailed):
            fail(request, outcome.reason)
        else:
            papers.append(outcome)
    acquired: list[dict[str, Any]] = []
    indexes = reader.embed(papers)
    for paper in papers:
        try:
            indexed = indexes[paper.paper.version_id]
            if isinstance(indexed, AcquisitionFailed):
                raise indexed
            item = reader.card(paper, indexed)
        except AcquisitionFailed as failure:
            fail(paper.request, failure.reason)
            continue
        _move(
            ledger,
            paper.request,
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
        self._candidates: tuple[OverviewVector, ...] | None = None
        self._pdf_reader = pdf_reader

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
        jobs = self._document_jobs()
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
            jobs = self._document_jobs()
        for request, listing in listings.items():
            try:
                outcomes[request] = self._read_one(
                    request, listing, jobs.get(str(request.request_id))
                )
            except AcquisitionFailed as failure:
                outcomes[request] = failure
        return outcomes

    def _document_jobs(self) -> dict[str, tuple[str, str, str | None]]:
        """Request id -> (job id, state, report manifest) of its documents job."""

        rows = self._storage.database.transaction(
            lambda connection: connection.execute(
                """SELECT j.id, j.state, encode(j.input_manifest_hash,'hex'),
                          encode(o.artifact_hash,'hex')
                   FROM jobs j LEFT JOIN job_outputs o ON o.job_id=j.id
                   ORDER BY j.scheduled_at, j.id"""
            ).fetchall()
        )
        jobs: dict[str, tuple[str, str, str | None]] = {}
        for job_id, state, manifest, output in rows:
            spec = self._storage.report(str(manifest))
            if spec.get("stage") == "documents" and "request_id" in spec:
                jobs[str(spec["request_id"])] = (
                    str(job_id),
                    str(state),
                    None if output is None else str(output),
                )
        return jobs

    def _read_one(
        self,
        request: PaperRequestRecord,
        listing: ArxivListing,
        job: tuple[str, str, str | None] | None,
    ) -> ReadPaper:
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
            family_id=str(request.family_id),
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
            requested_by=str(request.request_id),
        )
        paper_hash = self._storage.publish_spec(_json(paper), (report_manifest,))
        return ReadPaper(
            request,
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

        if self._candidates is None:
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
            self._candidates = tuple(candidates)
        return self._candidates

    def card(self, paper: ReadPaper, index: IndexEntry) -> dict[str, Any]:
        """Assemble and publish the card; return the next snapshot's item."""

        record, text = paper.paper, paper.text
        as_of = utc_now()
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
                    head_feature_eligible=False,
                    head_feature_unavailable_reason=HEAD_UNAVAILABLE_REASON,
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
        inputs = (paper.paper_hash,)
        card_hash = self._storage.publish_spec(_json(card), inputs)
        index_hash = self._storage.publish_spec(_json(index), inputs)
        return {
            "paper_family_id": record.family_id,
            "paper_version_id": record.version_id,
            "card_hash": card_hash,
            "overview_hash": None,
            "passage_index_hash": index_hash,
            "graph_hash": None,
        }
