"""Build a corpus release's frozen candidate list from a pilot's committed stages.

``bin/release-candidates`` reads a pilot schema's committed selection, in
rank order, and each selected family's citation observation from the
committed snapshot labels passes. It publishes what the release job reads
into the corpus schema the release is built in: one ``PaperVersionRecord``
per family, built from the selection's listing entry, and each observation
with every citation family record it names. It writes the candidates file
``bin/build-corpus --candidates`` takes, with its hash.

The paper and observation carry the ids ``ingest.pilot.gate_identity``
derives, the same the pilot's observations and ``bin/export-text``'s paper
versions use, so labels resolve and embedded vectors join without a mapping.
A family no labels pass observed is still a candidate, with no observation:
its row's labels are unknown. Nothing is invented for it.

A release lives in its own schema, never the pilot's: the release job reads
its inputs by manifest from the store it runs in.
"""

from __future__ import annotations

import argparse
import json
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import canonical_json, sha256_hex
from research_agent.contracts.learning import CitationFamilyRecord, CitationObservation
from research_agent.contracts.papers import ExternalIdentifier, PaperVersionRecord
from research_agent.contracts.primitives import validate_utc_instant
from research_agent.ingest.pilot import gate_identity
from research_agent.ingest.pilot_local import LocalStorage
from research_agent.ingest.pilot_run import SNAPSHOT_LABELS, _by_stage
from research_agent.learning.corpus import publication_week, split_weeks
from research_agent.learning.release import Identity, local_identity
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.database import Database
from research_agent.storage.migrate import migrate

_SPEC_LIMIT = 16 * 1024 * 1024
PILOT_PURPOSE = "acquisition_pilot"


@dataclass(frozen=True, slots=True)
class PilotSource:
    """What a candidate list reads from one pilot schema."""

    selection: dict[str, Any]
    # family id -> manifest of the observation its labels pass committed
    observations: dict[str, str]
    read_manifest: Callable[[str], dict[str, Any]]
    read_content: Callable[[str], bytes]


def pilot_source(storage: LocalStorage) -> PilotSource:
    """The committed selection and snapshot observations of one pilot."""
    by_stage = _by_stage(storage)
    selection = next(
        (j for j in by_stage.get("select", []) if j["state"] == "committed"), None
    )
    if selection is None:
        raise RuntimeError("this pilot has no committed selection")
    observations: dict[str, str] = {}
    # One labels pass per snapshot release; a later pass wins for a family.
    for job in by_stage.get(SNAPSHOT_LABELS, []):
        if job["state"] == "committed":
            for family_id, entry in job["report"]["families"].items():
                observations[family_id] = entry["observation"]

    def read_content(artifact_hash: str) -> bytes:
        (_, _), stream = storage.artifacts.read(artifact_hash)
        with stream:
            return stream.read()

    return PilotSource(selection["report"], observations, storage.report, read_content)


class CorpusStore:
    """The corpus schema a release is built in, published into by content.

    A payload already published there is not published again: its first
    manifest is reused, so rebuilding the same list writes the same file.
    """

    def __init__(self, database: Database, artifacts: ArtifactRepository) -> None:
        self._database = database
        self._artifacts = artifacts

    def _manifest(self, artifact_hash: str) -> str | None:
        row = self._database.transaction(
            lambda connection: connection.execute(
                "SELECT encode(manifest_hash,'hex') FROM artifact_productions "
                "WHERE artifact_hash=decode(%s,'hex') "
                "ORDER BY created_at, manifest_hash LIMIT 1",
                (artifact_hash,),
            ).fetchone()
        )
        return None if row is None else str(row[0])

    def publish(self, payload: bytes, identity: Identity) -> str:
        digest = sha256_hex(payload)
        existing = self._manifest(digest)
        if existing is not None:
            return existing
        return self._artifacts.publish(
            [payload],
            expected_hash=digest,
            byte_length=len(payload),
            maximum_length=_SPEC_LIMIT,
            media_type="application/json",
            kind="manifest",
            input_hashes=(),
            producer_version=identity.producer,
            config_hash=identity.config_hash,
            retention_policy_hash=identity.retention_policy_hash,
            command_id=uuid4(),
        ).manifest_hash


def paper_record(
    entry: dict[str, Any], *, frozen_at: str, identity: Identity
) -> PaperVersionRecord:
    """A selected family's original version, as its listing entry records it."""
    family_id = str(entry["family_id"])
    paper_family_id, original_version_id, _ = gate_identity(family_id)
    evidence = sha256_hex(canonical_json(entry))
    return PaperVersionRecord(
        schema_version=1,
        input_hashes=(),
        producer_version=identity.producer,
        config_hash=identity.config_hash,
        created_at=frozen_at,
        family_id=paper_family_id,
        version_id=original_version_id,
        external_ids=(ExternalIdentifier("arxiv", f"{family_id}v1"),),
        is_first_public_version=True,
        first_public_at=entry["first_public_at"],
        first_public_interval=None,
        first_public_evidence_hashes=(evidence,),
        source_access_hashes=(evidence,),
        title=unicodedata.normalize("NFC", str(entry["title"])),
        abstract=unicodedata.normalize("NFC", str(entry["abstract"])),
        author_ids=(),
        primary_source_subfield=None,
        original_source_hash=evidence,
        text_source_kind="metadata",
        source_revision="v1",
        author_count=int(entry["author_count"]),
        categories=tuple(entry["categories"]),
        version_count=int(entry["version_count"]),
    )


def candidates_hash(document: dict[str, Any]) -> str:
    """The hash of a candidates file over every field but the hash itself."""
    return sha256_hex(
        canonical_json({k: v for k, v in document.items() if k != "candidates_hash"})
    )


def build_candidates(
    source: PilotSource,
    corpus: CorpusStore,
    *,
    purpose: str,
    identity: Identity,
    fitting_cutoff: str | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    """The candidates file and its counts, publishing each record it names.

    The fitting cutoff defaults to the selection's freeze instant, which
    only admits families from mature months. A purpose other than the
    acquisition pilot splits the candidates' own publication weeks
    chronologically.
    """
    selection = source.selection
    frozen_at = str(selection["frozen_at"])
    candidates: list[dict[str, Any]] = []
    observed = 0
    for rank, entry in enumerate(selection["selected"]):
        family_id = str(entry["family_id"])
        paper = paper_record(entry, frozen_at=frozen_at, identity=identity)
        candidate: dict[str, Any] = {
            "paper_family_id": paper.family_id,
            "original_version_id": paper.version_id,
            "selection_rank": rank,
            "t0": paper.first_public_at,
            "paper_artifact_hash": corpus.publish(paper.to_canonical_json(), identity),
        }
        manifest = source.observations.get(family_id)
        if manifest is not None:
            observation = CitationObservation.from_json(
                canonical_json(source.read_manifest(manifest))
            )
            if (observation.paper_family_id, observation.original_version_id) != (
                paper.family_id,
                paper.version_id,
            ):
                raise ValueError(f"observation of {family_id} names another paper")
            for family_hash in observation.citation_family_hashes:
                body = source.read_content(family_hash)
                if sha256_hex(body) != family_hash:
                    raise ValueError("citation family record differs from its hash")
                corpus.publish(
                    CitationFamilyRecord.from_json(body).to_canonical_json(), identity
                )
            candidate["observation_artifact_hash"] = corpus.publish(
                observation.to_canonical_json(), identity
            )
            observed += 1
        candidates.append(candidate)
    document: dict[str, Any] = {
        "purpose": purpose,
        "selection_seed": int(selection["seed"]),
        "selection_frozen_at": frozen_at,
        "fitting_cutoff": fitting_cutoff or frozen_at,
        "intended_population_count": int(selection["intended_count"]),
        "enumerated_population_hash": str(selection["population_hash"]),
        "candidates": candidates,
    }
    if purpose != PILOT_PURPOSE:
        weeks = sorted({publication_week(c["t0"]) for c in candidates})
        split = split_weeks(tuple(weeks))
        document["fit_weeks"] = list(split.fit)
        document["development_weeks"] = list(split.development)
        document["calibration_weeks"] = list(split.calibration)
        document["locked_evaluation_weeks"] = list(split.locked_evaluation)
    document["candidates_hash"] = candidates_hash(document)
    counts = {
        "candidates": len(candidates),
        "observed": observed,
        "unobserved": len(candidates) - observed,
    }
    return document, counts


def main(argv: list[str] | None = None) -> int:
    from research_agent.learning.text_export import pilot_storage

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True, help="the pilot state")
    parser.add_argument("--dsn", required=True, help="DSN selecting the pilot schema")
    parser.add_argument(
        "--corpus-state",
        type=Path,
        required=True,
        help="the state directory bin/build-corpus --state is given",
    )
    parser.add_argument(
        "--corpus-dsn",
        required=True,
        help="DSN selecting the corpus schema bin/build-corpus --dsn is given",
    )
    parser.add_argument("--purpose", default=PILOT_PURPOSE)
    parser.add_argument(
        "--fitting-cutoff", help="UTC instant; defaults to the selection's freeze"
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.corpus_dsn == args.dsn:
        parser.error("a release is built in its own schema, not the pilot's")
    if args.fitting_cutoff is not None:
        try:
            validate_utc_instant(args.fitting_cutoff)
        except ValueError as error:
            parser.error(f"--fitting-cutoff: {error}")
    identity = local_identity({"stage": "release-candidates", "purpose": args.purpose})
    corpus_state: Path = args.corpus_state
    corpus_state.mkdir(parents=True, exist_ok=True)
    migrate(Database(args.corpus_dsn))
    database = Database(args.corpus_dsn)
    corpus = CorpusStore(
        database,
        ArtifactRepository(database, ArtifactStore(corpus_state / "artifacts")),
    )
    with pilot_storage(args.state, args.dsn) as storage:
        try:
            document, counts = build_candidates(
                pilot_source(storage),
                corpus,
                purpose=args.purpose,
                identity=identity,
                fitting_cutoff=args.fitting_cutoff,
            )
        except ValueError as error:
            parser.error(str(error))
    out: Path = args.out
    out.write_bytes(canonical_json(document))
    print(json.dumps({**counts, "candidates_hash": document["candidates_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
