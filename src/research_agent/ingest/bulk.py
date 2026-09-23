"""Bulk acquisition of arXiv source and PDF bundles from S3 (#146).

A second acquisition path for corpus releases, alongside the daily API path
(`ingest/pilot.py`). Given a selected population, it reads arXiv's monthly
source and PDF bundles from the requester-pays S3 archive confirmed by #145
(`docs/evidence/source-pilot/arxiv-bulk.md`), extracts text for each
family's source member with the same extractor #111 already ships
(`reader/extract.py`), and publishes the same provenance and extraction
contracts the corpus release job (#114) already consumes from the API path:
`SourceAccess`, `PaperVersionRecord`, `ExtractionRecord`. Bundle originals
stay in the archive; only extracted text, hashes and a manifest come home.

This module does not run TeX or OCR (SDD-MD-10, same constraint #111
observes): a source member with no LaTeX text is recorded `unavailable` with
reason `unsupported_source`, never invented. It does not select the
population (`learning/corpus.py`) or assemble a chunked `PassageRecord` set
(`reader/chunk.py` needs a pinned tokenizer this job does not wire); see
"Known limits" in `docs/implementation/bulk-acquisition.md`.

The job refuses to start unless `docs/evidence/source-pilot/arxiv-bulk.md`'s
own `## Status` section still confirms `arxiv_bulk_s3` is allowed research
use (`require_permission`), and refuses to reach S3 without
`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` in the environment
(`credentials_from_environment`) — never a file.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import hmac
import http.client
import json
import os
import resource
import shutil
import ssl
import subprocess
import sys
import tarfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4

from research_agent.contracts import (
    ProducerVersion,
    RecordMeta,
    canonical_json,
    canonical_loads,
    sha256_hex,
)
from research_agent.contracts.jobs import JobCheckpoint
from research_agent.contracts.papers import (
    ExternalIdentifier,
    PaperVersionRecord,
    SourceAccess,
)
from research_agent.contracts.passages import ExtractionRecord, ResourceDemand
from research_agent.ingest.fetch import BoundedResponse
from research_agent.ingest.pilot import Identity, derived_uuid, utc_now, work_key
from research_agent.ingest.pilot_local import (
    LocalStorage,
    local_storage,
    worker_principal,
)
from research_agent.learning.corpus import PilotCandidate
from research_agent.reader.extract import extract_latex, extract_unsupported, measure
from research_agent.storage.client import StorageClient
from research_agent.storage.database import Database
from research_agent.storage.migrate import migrate

_ROOT = Path(__file__).resolve().parents[3]
_EVIDENCE_PATH = _ROOT / "docs" / "evidence" / "source-pilot" / "arxiv-bulk.md"
_RETENTION = (
    b"Bulk originals stay in the arXiv S3 archive, re-readable by hash; "
    b"extracted text, provenance records and hashes are retained privately "
    b"for this research and are not redistributed (arxiv-bulk.md)."
)

DEFAULT_BUCKET = "arxiv"
BULK_ADAPTER = "arxiv-bulk-s3-v1"
# No production caller of reader/extract.py exists yet to copy a real
# extractor identity from (see docs/implementation/bulk-acquisition.md); this
# names the extractor's identity so a future API-path caller can adopt the
# same constant instead of minting its own.
EXTRACTOR_MANIFEST_HASH = sha256(b"reader.extract-latex-v1").hexdigest()
SRC_MANIFEST_KEY = "src/arXiv_src_manifest.xml"
PDF_MANIFEST_KEY = "pdf/arXiv_pdf_manifest.xml"
# S3 GET requests are billed per request, not per byte, for an in-region read
# (no data-transfer-out charge applies within the bucket's own region, per
# arxiv-bulk.md's own cost-model reasoning). The exact current rate is not
# yet observed (arxiv-bulk.md "## Status": recorded at first access); this
# names AWS S3 Standard's published general-purpose GET pricing at the time
# of writing ($0.0004 per 1,000 GET requests) as an explicit, documented
# placeholder, not a claim of measured precision.
ESTIMATED_USD_PER_GET_REQUEST = 0.0004 / 1000


class PermissionRefused(Exception):
    """The bulk evidence record does not confirm `arxiv_bulk_s3` is allowed."""


class CredentialsUnavailable(Exception):
    """AWS credentials are not present in the environment."""


class RegionUnverified(Exception):
    """S3 did not confirm the bucket's region before a transfer was attempted."""


class ManifestFormatError(ValueError):
    """An arXiv bulk manifest XML document could not be parsed."""


class BundleFetchFailed(Exception):
    """A whole-bundle or manifest GET failed; the job is not marked failed.

    Left uncaught, this propagates out of `BulkWorker.run` the same way a
    killed process would: the job's lease simply expires and a later run
    reclaims it, resuming from its last checkpointed bundle (#146's
    "resumable per bundle" requirement extends to a transient S3 failure,
    not only to an operator-killed process).
    """


# --- permission gate --------------------------------------------------------


def require_permission(evidence_path: Path = _EVIDENCE_PATH) -> str:
    """Read the #145 evidence file and refuse unless its own Status section
    still confirms `arxiv_bulk_s3` is allowed research use.

    Returns the sha256 hex digest of the evidence file's exact bytes, the
    same value `Identity.permission_evidence_hash` carries, so a corrupted
    or replaced evidence file changes the identity every publication is
    checked against, not only this one gate.
    """
    try:
        raw = evidence_path.read_bytes()
    except OSError as error:
        raise PermissionRefused(
            f"bulk permission evidence is unreadable at {evidence_path}: {error}"
        ) from error
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PermissionRefused(
            "bulk permission evidence is not valid UTF-8 text"
        ) from error
    parts = text.split("## Status", 1)
    if len(parts) != 2:
        raise PermissionRefused(
            "bulk permission evidence has no ## Status section to verify"
        )
    status = parts[1]
    if "arxiv_bulk_s3" not in status or "allowed" not in status:
        raise PermissionRefused(
            "the bulk evidence Status section no longer confirms arxiv_bulk_s3 "
            "is allowed; refusing to start"
        )
    return sha256(raw).hexdigest()


# --- AWS credentials, never from a file -------------------------------------


def credentials_from_environment() -> tuple[str, str, str | None]:
    """`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN` only.

    Never reads a credential from a file (PL-11 to PL-16: "no credential in
    any file"); refuses to start without the two required variables.
    """
    access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    if not access_key or not secret_key:
        raise CredentialsUnavailable(
            "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set in the "
            "environment; bulk acquisition never reads a credential from a file"
        )
    return access_key, secret_key, os.environ.get("AWS_SESSION_TOKEN") or None


# --- hand-rolled SigV4 HTTPS S3 client --------------------------------------
#
# No AWS SDK exists in this repository's dependencies and none is added for
# this change (CONTRIBUTING.md: no speculative abstractions, no dependency
# not already pinned). This signs and issues a plain HTTPS GET/HEAD using
# only the standard library, reviewed against the AWS Signature Version 4
# specification since it cannot be exercised against real AWS in CI.


def _sigv4_headers(
    *,
    method: str,
    host: str,
    path: str,
    region: str,
    access_key: str,
    secret_key: str,
    session_token: str | None,
    payload_hash: str,
    now: datetime,
) -> dict[str, str]:
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    headers = {
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
        "x-amz-request-payer": "requester",
    }
    if session_token:
        headers["x-amz-security-token"] = session_token
    signed_names = sorted(headers)
    canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in signed_names)
    signed_headers = ";".join(signed_names)
    canonical_request = "\n".join(
        [method, path, "", canonical_headers, signed_headers, payload_hash]
    )
    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = f"{date_stamp}/{region}/s3/aws4_request"
    string_to_sign = "\n".join(
        [
            algorithm,
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )

    def _hmac(key: bytes, message: str) -> bytes:
        return hmac.new(key, message.encode(), hashlib.sha256).digest()

    k_date = _hmac(("AWS4" + secret_key).encode(), date_stamp)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, "s3")
    k_signing = _hmac(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
    headers["authorization"] = (
        f"{algorithm} Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return headers


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class RealS3Client:
    """Requester-pays S3 reads over hand-rolled SigV4 HTTPS; stdlib only.

    Region is unknown until `verify_region` succeeds; `get_object` refuses to
    run before that so no object read can be misattributed to an unverified
    region. `bytes_read`/`request_count` accumulate for the PL-16 demand
    record; no credential is ever written to either.
    """

    def __init__(
        self,
        *,
        bucket: str,
        access_key: str,
        secret_key: str,
        session_token: str | None,
        timeout_seconds: float = 60.0,
        max_bytes: int = 2 * 1024**3,
    ) -> None:
        self._bucket = bucket
        self._access_key = access_key
        self._secret_key = secret_key
        self._session_token = session_token
        self._timeout = timeout_seconds
        self._max_bytes = max_bytes
        self._region: str | None = None
        self.bytes_read = 0
        self.request_count = 0

    def verify_region(self) -> str:
        host = f"{self._bucket}.s3.amazonaws.com"
        response = self._request("HEAD", host, "/", region="us-east-1")
        region = dict(response.headers).get("x-amz-bucket-region")
        if not region:
            raise RegionUnverified(
                "S3 did not report x-amz-bucket-region; refusing to transfer"
            )
        self._region = region
        return region

    def get_object(self, key: str) -> BoundedResponse:
        if self._region is None:
            raise RegionUnverified("verify_region must succeed before any object read")
        host = f"{self._bucket}.s3.{self._region}.amazonaws.com"
        return self._request("GET", host, "/" + key, region=self._region)

    def _request(
        self, method: str, host: str, path: str, *, region: str
    ) -> BoundedResponse:
        started = _now()
        monotonic_start = time.monotonic()
        payload_hash = hashlib.sha256(b"").hexdigest()
        headers = _sigv4_headers(
            method=method,
            host=host,
            path=path,
            region=region,
            access_key=self._access_key,
            secret_key=self._secret_key,
            session_token=self._session_token,
            payload_hash=payload_hash,
            now=datetime.now(timezone.utc),
        )
        context = ssl.create_default_context()
        connection = http.client.HTTPSConnection(
            host, 443, timeout=self._timeout, context=context
        )
        status: int | None = None
        response_headers: tuple[tuple[str, str], ...] = ()
        body: bytes | None = None
        failure: str | None = None
        try:
            connection.request(method, path, headers=headers)
            response = connection.getresponse()
            status = response.status
            response_headers = tuple(
                (name.lower(), value) for name, value in response.getheaders()
            )
            if status not in (200, 206):
                failure = "not_found" if status == 404 else "rejected"
                response.read()
            else:
                chunks: list[bytes] = []
                size = 0
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self._max_bytes:
                        failure = "invalid_payload"
                        break
                    chunks.append(chunk)
                if failure is None:
                    body = b"".join(chunks)
        except TimeoutError:
            failure = "timeout"
        except (OSError, http.client.HTTPException):
            failure = "transport"
        finally:
            connection.close()
        self.request_count += 1
        if body is not None:
            self.bytes_read += len(body)
        return BoundedResponse(
            started,
            _now(),
            time.monotonic() - monotonic_start,
            status,
            response_headers,
            body,
            failure,
        )


@dataclass
class Sources:
    """Injectable S3 access; production binds it to `RealS3Client`.

    Mirrors `ingest/pilot.py`'s own `Sources` seam: tests substitute an
    in-memory fake serving canned manifest and tar bytes, never touching a
    real socket.
    """

    verify_region: Callable[[], str]
    get_object: Callable[[str], BoundedResponse]


def sources_from_environment(*, bucket: str) -> tuple[Sources, RealS3Client]:
    access_key, secret_key, session_token = credentials_from_environment()
    client = RealS3Client(
        bucket=bucket,
        access_key=access_key,
        secret_key=secret_key,
        session_token=session_token,
    )
    return Sources(
        verify_region=client.verify_region, get_object=client.get_object
    ), client


# --- manifest parsing --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BundleEntry:
    """One `<file>` entry from arXiv's src/pdf manifest XML (#145)."""

    filename: str
    first_item: str
    last_item: str
    yymm: str


def parse_manifest(xml_bytes: bytes) -> tuple[BundleEntry, ...]:
    """Parse arXiv's `arXiv_{src,pdf}_manifest.xml` into ordered bundle entries."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as error:
        raise ManifestFormatError(f"malformed manifest XML: {error}") from error
    entries: list[BundleEntry] = []
    for file_element in root.findall("file"):
        filename = file_element.findtext("filename")
        first_item = file_element.findtext("first_item")
        last_item = file_element.findtext("last_item")
        yymm = file_element.findtext("yymm")
        if not filename or not first_item or not last_item or not yymm:
            continue
        entries.append(
            BundleEntry(
                filename.strip(), first_item.strip(), last_item.strip(), yymm.strip()
            )
        )
    if not entries:
        raise ManifestFormatError("manifest contains no usable file entries")
    return tuple(entries)


def bundle_for_family(
    entries: tuple[BundleEntry, ...], family_id: str
) -> BundleEntry | None:
    """The bundle whose `[first_item, last_item]` range contains `family_id`.

    Canonical arXiv ids are fixed-width and zero-padded within one bundle's
    `YYMM`, so lexicographic range containment matches numeric containment.
    """
    for entry in entries:
        if entry.first_item <= family_id <= entry.last_item:
            return entry
    return None


# --- tar member decoding -----------------------------------------------------


def _find_member(tar: tarfile.TarFile, family_id: str) -> tarfile.TarInfo | None:
    for member in tar.getmembers():
        if not member.isfile():
            continue
        stem = Path(member.name).name
        if stem == family_id:
            return member
        if stem.startswith(family_id) and not stem[len(family_id)].isdigit():
            return member
    return None


def _member_bytes(tar: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    extracted = tar.extractfile(member)
    if extracted is None:
        raise ValueError("tar member is not a regular extractable file")
    return extracted.read()


def _looks_like_tar(payload: bytes) -> bool:
    try:
        with tarfile.open(fileobj=BytesIO(payload), mode="r"):
            return True
    except (tarfile.TarError, OSError, EOFError):
        return False


def _largest_tex_member(inner: tarfile.TarFile) -> bytes | None:
    candidates = [
        member
        for member in inner.getmembers()
        if member.isfile() and member.name.lower().endswith(".tex")
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda member: member.size)
    extracted = inner.extractfile(best)
    return extracted.read() if extracted is not None else None


def decode_latex_source(raw: bytes) -> str | None:
    """Best-effort decode of one arXiv per-paper source entry into LaTeX text.

    arXiv packages a paper's source as one gzip-compressed stream: either
    plain TeX text, or (for a multi-file submission) a nested tar of files.
    A PDF-only submission's "source" is the PDF itself and carries no LaTeX
    text; this returns `None` for it so the caller falls back to
    `reader.extract.extract_unsupported` rather than inventing text.
    """
    try:
        payload = gzip.decompress(raw)
    except (OSError, EOFError):
        payload = raw
    if payload.startswith(b"%PDF"):
        return None
    if _looks_like_tar(payload):
        try:
            with tarfile.open(fileobj=BytesIO(payload), mode="r") as inner:
                tex_bytes = _largest_tex_member(inner)
        except (tarfile.TarError, OSError, EOFError):
            return None
        if tex_bytes is None:
            return None
        payload = tex_bytes
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return payload.decode("latin-1")
        except UnicodeDecodeError:
            return None


def extract_source_member(
    paper_version_id: str, source_hash: str, raw_member: bytes, created_at: str
) -> tuple[ExtractionRecord, ResourceDemand]:
    """Extract one source member's bytes with #111's shared extractor.

    LaTeX/TeX source calls `extract_latex` directly on the decoded text; a
    source with no LaTeX (a PDF-only submission) calls `extract_unsupported`
    so its coverage is honestly `unavailable`/`unsupported_source` rather
    than invented (no PDF text-layer capability exists in this repository).
    """
    text = decode_latex_source(raw_member)
    if text is None:
        return measure(
            extract_unsupported,
            paper_version_id,
            source_hash,
            EXTRACTOR_MANIFEST_HASH,
            created_at,
        )
    return measure(
        extract_latex,
        paper_version_id,
        source_hash,
        EXTRACTOR_MANIFEST_HASH,
        text,
        created_at,
    )


# --- resumable worker ---------------------------------------------------------


@dataclass
class _Lease:
    job_id: UUID
    epoch: int
    input_manifest: str
    spec: dict[str, Any] = field(default_factory=dict)
    completed: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RunSummary:
    jobs_completed: int


class BulkWorker:
    """Claims `capture` jobs and acquires one bundle group per checkpoint.

    Talks to storage the same way `ingest/pilot.py#PilotWorker` does, over
    an authenticated `StorageClient`, because `pilot_local.local_storage`'s
    server capability admits only the `capture` job kind (`ServiceCapability
    .job_kinds`) and that binding cannot be edited for this change.
    """

    def __init__(
        self,
        storage: StorageClient,
        *,
        worker_id: UUID,
        identity: Identity,
        sources: Sources,
        bucket: str,
        evidence_path: Path = _EVIDENCE_PATH,
    ) -> None:
        verified_hash = require_permission(evidence_path)
        if verified_hash != identity.permission_evidence_hash:
            raise PermissionRefused(
                "identity.permission_evidence_hash does not match the "
                "verified arxiv-bulk.md evidence file; refusing to start"
            )
        self._storage = storage
        self._worker = worker_id
        self._identity = identity
        self._sources = sources
        self._bucket = bucket
        self._region: str | None = None

    # --- storage plumbing, mirroring PilotWorker's private methods --------

    def _meta(self, lease: _Lease) -> RecordMeta:
        return RecordMeta(
            1,
            (lease.input_manifest,),
            self._identity.producer,
            self._identity.config_hash,
            utc_now(),
        )

    def _publish(
        self,
        lease: _Lease,
        payload: bytes,
        *,
        media_type: str,
        kind: str,
        inputs: tuple[str, ...],
    ) -> str:
        digest = sha256(payload).hexdigest()
        command = derived_uuid(
            lease.job_id, "publish", digest, media_type, kind, inputs
        )
        result = self._storage.publish_artifact(
            payload,
            expected_hash=digest,
            media_type=media_type,
            kind=kind,
            input_hashes=inputs,
            producer_version=self._identity.producer,
            config_hash=self._identity.config_hash,
            retention_policy_hash=self._identity.retention_policy_hash,
            source_available_at=None,
            job_id=lease.job_id,
            lease_epoch=lease.epoch,
            command_id=command,
            request_id=uuid4(),
            idempotency_key=command,
        )
        manifest = result.data["receipt"]["artifact_hashes"][1]
        assert isinstance(manifest, str)
        return manifest

    def _record(
        self, lease: _Lease, access: SourceAccess, payload_manifest: str | None
    ) -> str:
        inputs = (lease.input_manifest,) + (
            (payload_manifest,) if payload_manifest else ()
        )
        return self._publish(
            lease,
            access.to_canonical_json(),
            media_type="application/json",
            kind="source_response",
            inputs=inputs,
        )

    def _checkpoint(self, lease: _Lease, key: str, outputs: tuple[str, ...]) -> None:
        lease.completed.append(key)
        lease.outputs.extend(
            o for o in dict.fromkeys(outputs) if o not in lease.outputs
        )
        body = JobCheckpoint(
            1,
            str(lease.job_id),
            "bulk",
            (lease.input_manifest,),
            self._identity.config_hash,
            tuple(lease.completed),
            None,
            tuple(lease.outputs),
        ).to_canonical_json()
        checkpoint = self._publish(
            lease,
            body,
            media_type="application/json",
            kind="manifest",
            inputs=(lease.input_manifest, *lease.outputs),
        )
        command = derived_uuid(lease.job_id, lease.epoch, "checkpoint", checkpoint)
        self._storage.checkpoint(
            job_id=lease.job_id,
            worker_id=self._worker,
            lease_epoch=lease.epoch,
            checkpoint_hash=checkpoint,
            command_id=command,
            request_id=uuid4(),
            idempotency_key=command,
        )
        self._renew(lease)

    def _renew(self, lease: _Lease) -> None:
        command = uuid4()
        self._storage.renew(
            job_id=lease.job_id,
            worker_id=self._worker,
            lease_epoch=lease.epoch,
            command_id=command,
            request_id=uuid4(),
            idempotency_key=command,
        )

    def _complete(self, lease: _Lease, summary: dict[str, Any]) -> None:
        report = self._publish(
            lease,
            canonical_json(summary),
            media_type="application/json",
            kind="manifest",
            inputs=(lease.input_manifest, *lease.outputs),
        )
        command = derived_uuid(lease.job_id, lease.epoch, "complete", report)
        self._storage.complete(
            job_id=lease.job_id,
            worker_id=self._worker,
            lease_epoch=lease.epoch,
            result={"kind": "committed", "output_hashes": [report]},
            command_id=command,
            request_id=uuid4(),
            idempotency_key=command,
        )

    def _read_json(self, lease: _Lease, artifact: str) -> Any:
        return canonical_loads(
            self._storage.read_artifact(
                artifact, job_id=lease.job_id, lease_epoch=lease.epoch
            ).payload
        )

    def _read(self, lease: _Lease, artifact: str) -> bytes:
        return self._storage.read_artifact(
            artifact, job_id=lease.job_id, lease_epoch=lease.epoch
        ).payload

    def _produced(self, lease: _Lease, manifest: str) -> bytes:
        return self._read(lease, self._read_json(lease, manifest)["artifact_hash"])

    def _resume(self, lease: _Lease, checkpoint: str | None) -> None:
        if checkpoint is None:
            return
        state = JobCheckpoint.from_json(self._produced(lease, checkpoint))
        lease.completed = list(state.completed_work_keys)
        lease.outputs = list(state.output_hashes)

    # --- run loop -----------------------------------------------------------

    def run(self, *, maximum_jobs: int | None = None) -> RunSummary:
        completed = 0
        while maximum_jobs is None or completed < maximum_jobs:
            command = uuid4()
            claimed = self._storage.claim(
                worker_id=self._worker,
                kinds=("capture",),
                command_id=command,
                request_id=uuid4(),
                idempotency_key=command,
            ).data["lease"]
            if claimed is None:
                break
            job_id = UUID(claimed["job_id"])
            lease = _Lease(job_id, claimed["lease_epoch"], claimed["input_manifest"])
            spec = canonical_loads(self._produced(lease, lease.input_manifest))
            if not isinstance(spec, dict) or spec.get("stage") != "bulk":
                raise ValueError(
                    "capture job input is not a bulk acquisition specification"
                )
            lease.spec = spec
            self._resume(lease, claimed["checkpoint"])
            summary = self._bulk(lease)
            self._complete(lease, summary)
            completed += 1
        return RunSummary(completed)

    # --- the one stage --------------------------------------------------------

    def _bundle_access(
        self,
        lease: _Lease,
        *,
        region: str,
        key: str,
        response: BoundedResponse,
        failure: str | None,
    ) -> SourceAccess:
        meta = self._meta(lease)
        url = f"https://{self._bucket}.s3.{region}.amazonaws.com/{key}"
        return SourceAccess(
            schema_version=1,
            input_hashes=meta.input_hashes,
            producer_version=meta.producer_version,
            config_hash=meta.config_hash,
            created_at=response.completed_at,
            source="arxiv",
            requested_url=url,
            request_parameters_hash=sha256(key.encode()).hexdigest(),
            adapter_version=BULK_ADAPTER,
            capture_started_at=response.started_at,
            capture_completed_at=response.completed_at,
            http_status=response.status,
            retained_payload_hash=(
                None
                if response.body is None or failure is not None
                else sha256_hex(response.body)
            ),
            retention_policy_hash=self._identity.retention_policy_hash,
            license_expression=None,
            permission_evidence_hash=self._identity.permission_evidence_hash,
            failure=failure,
        )

    def _member_access(
        self,
        lease: _Lease,
        *,
        region: str,
        kind: str,
        family_id: str,
        raw: bytes | None,
        failure: str | None,
    ) -> SourceAccess:
        # A member's bytes are already resident in an already-recorded bundle
        # read, not a separate network request; capture start equals its end.
        meta = self._meta(lease)
        now = utc_now()
        url = f"https://{self._bucket}.s3.{region}.amazonaws.com/{kind}#{family_id}"
        return SourceAccess(
            schema_version=1,
            input_hashes=meta.input_hashes,
            producer_version=meta.producer_version,
            config_hash=meta.config_hash,
            created_at=now,
            source="arxiv",
            requested_url=url,
            request_parameters_hash=sha256(f"{kind}:{family_id}".encode()).hexdigest(),
            adapter_version=BULK_ADAPTER,
            capture_started_at=now,
            capture_completed_at=now,
            http_status=None,
            retained_payload_hash=(
                None if raw is None or failure is not None else sha256_hex(raw)
            ),
            retention_policy_hash=self._identity.retention_policy_hash,
            license_expression=None,
            permission_evidence_hash=self._identity.permission_evidence_hash,
            failure=failure,
        )

    def _process_family(
        self,
        lease: _Lease,
        *,
        region: str,
        candidate: PilotCandidate,
        counts: tuple[int, int],
        src_tar: tarfile.TarFile,
        pdf_entry: BundleEntry | None,
        pdf_cache: dict[str, tarfile.TarFile | None],
    ) -> tuple[list[str], bool]:
        """Process one family's src member (required) and pdf member (best
        effort, provenance only); returns its outputs and whether its
        extraction coverage was `unsupported_source`."""
        outputs: list[str] = []
        created_at = utc_now()
        family_id = candidate.family_id
        paper_version_id = str(derived_uuid("gate-paper-version", family_id))

        src_member = _find_member(src_tar, family_id)
        source_hash: str | None = None
        src_access_hash: str | None = None
        extraction_record: ExtractionRecord | None = None
        if src_member is None:
            access = self._member_access(
                lease,
                region=region,
                kind="src",
                family_id=family_id,
                raw=None,
                failure="not_found",
            )
            outputs.append(self._record(lease, access, None))
        else:
            raw = _member_bytes(src_tar, src_member)
            source_hash = sha256_hex(raw)
            payload_manifest = self._publish(
                lease,
                raw,
                media_type="application/octet-stream",
                kind="source_document",
                inputs=(lease.input_manifest,),
            )
            access = self._member_access(
                lease,
                region=region,
                kind="src",
                family_id=family_id,
                raw=raw,
                failure=None,
            )
            src_access_hash = self._record(lease, access, payload_manifest)
            outputs.append(src_access_hash)
            extraction_record, demand = extract_source_member(
                paper_version_id, source_hash, raw, created_at
            )
            extraction_payload = self._publish(
                lease,
                extraction_record.to_canonical_json(),
                media_type="application/json",
                kind="extraction",
                inputs=(lease.input_manifest, src_access_hash),
            )
            outputs.append(extraction_payload)
            demand_payload = self._publish(
                lease,
                canonical_json({"family_id": family_id, **demand.to_dict()}),
                media_type="application/json",
                kind="manifest",
                inputs=(lease.input_manifest,),
            )
            outputs.append(demand_payload)

        pdf_access_hash: str | None = None
        if pdf_entry is not None:
            if pdf_entry.filename not in pdf_cache:
                response = self._sources.get_object(pdf_entry.filename)
                if response.failure is None and response.body is not None:
                    pdf_tar = tarfile.open(fileobj=BytesIO(response.body), mode="r")
                    bundle_access = self._bundle_access(
                        lease,
                        region=region,
                        key=pdf_entry.filename,
                        response=response,
                        failure=None,
                    )
                    bundle_payload = self._publish(
                        lease,
                        response.body,
                        media_type="application/octet-stream",
                        kind="source_response",
                        inputs=(lease.input_manifest,),
                    )
                    outputs.append(self._record(lease, bundle_access, bundle_payload))
                else:
                    pdf_tar = None
                pdf_cache[pdf_entry.filename] = pdf_tar
            pdf_tar = pdf_cache[pdf_entry.filename]
            if pdf_tar is not None:
                pdf_member = _find_member(pdf_tar, family_id)
                if pdf_member is None:
                    access = self._member_access(
                        lease,
                        region=region,
                        kind="pdf",
                        family_id=family_id,
                        raw=None,
                        failure="not_found",
                    )
                    outputs.append(self._record(lease, access, None))
                else:
                    raw_pdf = _member_bytes(pdf_tar, pdf_member)
                    media_type = (
                        "application/pdf"
                        if raw_pdf.startswith(b"%PDF")
                        else "application/octet-stream"
                    )
                    payload_manifest = self._publish(
                        lease,
                        raw_pdf,
                        media_type=media_type,
                        kind="source_document",
                        inputs=(lease.input_manifest,),
                    )
                    access = self._member_access(
                        lease,
                        region=region,
                        kind="pdf",
                        family_id=family_id,
                        raw=raw_pdf,
                        failure=None,
                    )
                    pdf_access_hash = self._record(lease, access, payload_manifest)
                    outputs.append(pdf_access_hash)

        if source_hash is None or extraction_record is None:
            # No source member: provenance is recorded, nothing to extract.
            return outputs, True

        assert src_access_hash is not None
        source_access_hashes = tuple(
            h for h in (src_access_hash, pdf_access_hash) if h is not None
        )
        # No listing/metadata pipeline runs in this path; this evidence hash
        # names the population entry that asserted the first-public time,
        # the same construction ingest/pilot.py's own gate uses for its
        # pre-acquisition placeholder record.
        evidence_hash = sha256_hex(
            canonical_json(
                {"family_id": family_id, "first_public_at": candidate.first_public_at}
            )
        )
        unsupported = (
            extraction_record.coverage == "unavailable"
            and "unsupported_source" in extraction_record.coverage_reasons
        )
        paper = PaperVersionRecord(
            schema_version=1,
            input_hashes=(lease.input_manifest,),
            producer_version=self._identity.producer,
            config_hash=self._identity.config_hash,
            created_at=created_at,
            family_id=str(derived_uuid("gate-paper-family", family_id)),
            version_id=paper_version_id,
            external_ids=(ExternalIdentifier("arxiv", f"{family_id}v1"),),
            is_first_public_version=True,
            first_public_at=candidate.first_public_at,
            first_public_interval=None,
            first_public_evidence_hashes=(evidence_hash,),
            source_access_hashes=source_access_hashes,
            title=f"bulk acquisition {family_id}",
            abstract=(
                "Title and abstract are not part of the arXiv bulk source "
                "bundle; this record is provenance and extracted text only. "
                "See the family's OAI-PMH listing record for title and "
                "abstract (ingest/pilot.py's API acquisition path)."
            ),
            author_ids=(),
            primary_source_subfield=None,
            original_source_hash=source_hash,
            text_source_kind="metadata" if unsupported else "latex",
            source_revision="v1",
            # The bundle carries no listing; these come from the population
            # file, which is exported from the same selection record the API
            # path reads them from. Never defaulted: a record that claims
            # exact counts must have been told them.
            author_count=counts[0],
            categories=candidate.categories,
            version_count=counts[1],
        )
        paper_payload = self._publish(
            lease,
            paper.to_canonical_json(),
            media_type="application/json",
            kind="manifest",
            inputs=(lease.input_manifest, *source_access_hashes),
        )
        outputs.append(paper_payload)
        return outputs, unsupported

    def _bulk(self, lease: _Lease) -> dict[str, Any]:
        spec = lease.spec
        families = [
            PilotCandidate(
                item["family_id"], item["first_public_at"], tuple(item["categories"])
            )
            for item in spec["families"]
        ]
        counts = _family_counts(spec["families"])
        if self._region is None:
            self._region = self._sources.verify_region()
        region = self._region

        src_manifest = self._sources.get_object(SRC_MANIFEST_KEY)
        if src_manifest.failure is not None or src_manifest.body is None:
            raise BundleFetchFailed("source manifest fetch failed")
        pdf_manifest = self._sources.get_object(PDF_MANIFEST_KEY)
        if pdf_manifest.failure is not None or pdf_manifest.body is None:
            raise BundleFetchFailed("pdf manifest fetch failed")
        src_entries = parse_manifest(src_manifest.body)
        pdf_entries = parse_manifest(pdf_manifest.body)

        mapping: dict[str, tuple[BundleEntry | None, BundleEntry | None]] = {
            candidate.family_id: (
                bundle_for_family(src_entries, candidate.family_id),
                bundle_for_family(pdf_entries, candidate.family_id),
            )
            for candidate in families
        }
        src_bundle_keys = sorted(
            {entry.filename for entry, _ in mapping.values() if entry is not None}
        )
        families_processed = 0
        families_unsupported = 0
        for bundle_filename in src_bundle_keys:
            key = work_key("bundle", bundle_filename)
            if key in lease.completed:
                continue
            response = self._sources.get_object(bundle_filename)
            if response.failure is not None or response.body is None:
                raise BundleFetchFailed(f"bundle fetch failed: {bundle_filename}")
            outputs: list[str] = []
            bundle_access = self._bundle_access(
                lease,
                region=region,
                key=bundle_filename,
                response=response,
                failure=None,
            )
            bundle_payload = self._publish(
                lease,
                response.body,
                media_type="application/octet-stream",
                kind="source_response",
                inputs=(lease.input_manifest,),
            )
            outputs.append(self._record(lease, bundle_access, bundle_payload))
            pdf_cache: dict[str, tarfile.TarFile | None] = {}
            try:
                with tarfile.open(fileobj=BytesIO(response.body), mode="r") as tar:
                    for candidate in families:
                        entry, pdf_entry = mapping[candidate.family_id]
                        if entry is None or entry.filename != bundle_filename:
                            continue
                        family_outputs, unsupported = self._process_family(
                            lease,
                            region=region,
                            candidate=candidate,
                            counts=counts[candidate.family_id],
                            src_tar=tar,
                            pdf_entry=pdf_entry,
                            pdf_cache=pdf_cache,
                        )
                        outputs.extend(family_outputs)
                        families_processed += 1
                        if unsupported:
                            families_unsupported += 1
            finally:
                for pdf_tar in pdf_cache.values():
                    if pdf_tar is not None:
                        pdf_tar.close()
            self._checkpoint(lease, key, tuple(outputs))
        families_missing_bundle = sum(
            1 for entry, _ in mapping.values() if entry is None
        )
        return {
            "stage": "bulk",
            "bucket": self._bucket,
            "region": region,
            "families_requested": len(families),
            "families_processed": families_processed,
            "families_unsupported": families_unsupported,
            "families_missing_bundle": families_missing_bundle,
            "bundles_processed": len(src_bundle_keys),
        }


# --- local operator ----------------------------------------------------------


def _commit() -> str:
    return subprocess.run(
        ("git", "-C", str(_ROOT), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def identity_for(
    *, bucket: str, population_hash: str, evidence_path: Path = _EVIDENCE_PATH
) -> Identity:
    permission_hash = require_permission(evidence_path)
    producer = ProducerVersion(sha256(b"local-process").hexdigest(), _commit(), 1)
    config = {
        "bucket": bucket,
        "extractor_manifest_hash": EXTRACTOR_MANIFEST_HASH,
        "population_hash": population_hash,
    }
    return Identity(
        producer,
        sha256(canonical_json(config)).hexdigest(),
        sha256(_RETENTION).hexdigest(),
        permission_hash,
    )


def _family_counts(items: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """Each family's `(author_count, version_count)`, required and integral.

    The bundle carries no listing, so the paper record's counts can only
    come from the population the operator supplies; a family without them
    is refused rather than recorded with a made-up number.
    """
    counts: dict[str, tuple[int, int]] = {}
    for item in items:
        family_id = str(item.get("family_id", "?"))
        try:
            author_count = item["author_count"]
            version_count = item["version_count"]
        except KeyError as error:
            raise ValueError(
                f"population entry {family_id} lacks {error.args[0]}; export the "
                "population from a selection report, which carries it"
            ) from error
        if (
            isinstance(author_count, bool)
            or isinstance(version_count, bool)
            or not isinstance(author_count, int)
            or not isinstance(version_count, int)
            or author_count < 0
            or version_count < 1
        ):
            raise ValueError(f"population entry {family_id} has invalid counts")
        counts[family_id] = (author_count, version_count)
    return counts


def load_population(path: Path) -> tuple[PilotCandidate, ...]:
    """A JSON array shaped like `learning/corpus.py#PilotCandidate`, each
    entry also carrying `author_count` and `version_count` (see
    `_family_counts`)."""
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise ValueError("--population file must contain a JSON array")
    _family_counts(payload)
    return tuple(
        PilotCandidate(
            item["family_id"], item["first_public_at"], tuple(item["categories"])
        )
        for item in payload
    )


def load_population_counts(path: Path) -> dict[str, tuple[int, int]]:
    """The counts `load_population` validated, keyed by family id."""
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise ValueError("--population file must contain a JSON array")
    return _family_counts(payload)


def _population_hash(population: tuple[PilotCandidate, ...]) -> str:
    return sha256(
        canonical_json(
            [
                {
                    "family_id": c.family_id,
                    "first_public_at": c.first_public_at,
                    "categories": list(c.categories),
                }
                for c in population
            ]
        )
    ).hexdigest()


def _report(storage: LocalStorage) -> dict[str, Any]:
    rows = storage.job_rows()
    states: dict[str, int] = {}
    for _, state, _ in rows:
        states[state] = states.get(state, 0) + 1
    return {"jobs": states, "job_count": len(rows)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "report"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument(
        "--dsn", required=True, help="DSN selecting a bulk-acquisition schema"
    )
    parser.add_argument(
        "--population",
        type=Path,
        help="JSON array of selected families; required to run",
    )
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--tls-directory", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.command == "run" and args.population is None:
        parser.error("--population is required to enqueue and run the bulk job")

    state: Path = args.state
    state.mkdir(parents=True, exist_ok=True)
    tls_directory: Path = args.tls_directory or (state / "tls")

    population: tuple[PilotCandidate, ...] = ()
    if args.population is not None:
        population = load_population(args.population)
        population_counts = load_population_counts(args.population)
    identity = identity_for(
        bucket=args.bucket, population_hash=_population_hash(population)
    )

    migrate(Database(args.dsn))
    with local_storage(
        dsn=args.dsn,
        artifact_root=state / "artifacts",
        tls_directory=tls_directory,
        identity=identity,
    ) as storage:
        if args.command == "report":
            print(json.dumps(_report(storage), indent=2, sort_keys=True))
            return 0
        if not storage.job_rows():
            spec = {
                "stage": "bulk",
                "bucket": args.bucket,
                "families": [
                    {
                        "family_id": c.family_id,
                        "first_public_at": c.first_public_at,
                        "categories": list(c.categories),
                        "author_count": population_counts[c.family_id][0],
                        "version_count": population_counts[c.family_id][1],
                    }
                    for c in population
                ],
            }
            storage.enqueue(spec)
        sources, client = sources_from_environment(bucket=args.bucket)
        worker = BulkWorker(
            storage.client,
            worker_id=worker_principal(tls_directory),
            identity=identity,
            sources=sources,
            bucket=args.bucket,
        )
        started = time.monotonic()
        summary = worker.run()
        run = {
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "wall_seconds": round(time.monotonic() - started, 3),
            # macOS reports bytes, Linux kibibytes.
            "peak_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "platform": sys.platform,
            "jobs_completed": summary.jobs_completed,
            "bytes_read": client.bytes_read,
            "request_count": client.request_count,
            "estimated_cost_usd": round(
                client.request_count * ESTIMATED_USD_PER_GET_REQUEST, 6
            ),
            "free_disk_bytes": shutil.disk_usage(state).free,
        }
        with (state / "runs.jsonl").open("a") as runs:
            runs.write(json.dumps(run) + "\n")
        print(json.dumps(run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
