"""One bounded anonymous OpenAlex incoming-citation page request."""

from __future__ import annotations

import http.client
import io
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import cast
from urllib.parse import urlencode

from research_agent.contracts import RecordMeta, canonical_json, canonical_loads
from research_agent.contracts.papers import SourceAccess, normalize_identifier
from research_agent.contracts.primitives import validate_sha256

_FIELDS = "id,ids,doi,publication_date,primary_topic,referenced_works"
_MAX_BYTES = 8 * 1024 * 1024
_TIMEOUT_SECONDS = 30.0


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("OpenAlex page deadline elapsed")
    return remaining


class _DeadlineRaw(io.RawIOBase):
    def __init__(self, sock: ssl.SSLSocket, deadline: float):
        self._socket = sock
        self._deadline = deadline

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: object) -> int:
        self._socket.settimeout(_remaining(self._deadline))
        return self._socket.recv_into(cast(memoryview, buffer))


class _DeadlineSocket:
    def __init__(self, sock: ssl.SSLSocket, deadline: float):
        self._socket = sock
        self._deadline = deadline

    def sendall(self, data: bytes) -> None:
        self._socket.settimeout(_remaining(self._deadline))
        self._socket.sendall(data)

    def makefile(self, mode: str) -> io.BufferedReader:
        if mode != "rb":
            raise ValueError("deadline socket supports response reads only")
        return io.BufferedReader(_DeadlineRaw(self._socket, self._deadline))

    def close(self) -> None:
        # http.client releases its connection on Connection: close before the
        # response body has been read. The fetch owner closes after that read.
        pass

    def close_owned(self) -> None:
        self._socket.close()


class _DeadlineHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self, host: str, port: int, *, context: ssl.SSLContext, deadline: float
    ) -> None:
        self._deadline = deadline
        self._tls_context = context
        self._owned_socket: _DeadlineSocket | None = None
        super().__init__(host, port, timeout=_remaining(deadline), context=context)

    def connect(self) -> None:
        raw = socket.create_connection(
            (self.host, self.port), _remaining(self._deadline)
        )
        try:
            raw.settimeout(_remaining(self._deadline))
            secured = self._tls_context.wrap_socket(raw, server_hostname=self.host)
            secured.settimeout(_remaining(self._deadline))
        except BaseException:
            raw.close()
            raise
        self._owned_socket = _DeadlineSocket(secured, self._deadline)
        self.sock = cast(socket.socket, self._owned_socket)

    def close_owned(self) -> None:
        super().close()
        if self._owned_socket is not None:
            self._owned_socket.close_owned()
            self._owned_socket = None


@dataclass(frozen=True, slots=True)
class FetchedOpenAlexPage:
    access: SourceAccess
    payload: bytes | None
    request_parameters: bytes
    observed_budget_headers: tuple[tuple[str, str], ...]
    elapsed_seconds: float


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _request(
    target_provider_ids: tuple[str, ...], cursor: str | None, per_page: int
) -> tuple[str, bytes]:
    if (
        not isinstance(target_provider_ids, tuple)
        or not 1 <= len(target_provider_ids) <= 100
        or len(set(target_provider_ids)) != len(target_provider_ids)
    ):
        raise ValueError("target work ids must be a unique tuple of 1..100")
    targets = tuple(
        normalize_identifier("openalex", value) for value in target_provider_ids
    )
    if targets != target_provider_ids:
        raise ValueError("target work ids must be canonical OpenAlex ids")
    if (
        isinstance(per_page, bool)
        or not isinstance(per_page, int)
        or not 1 <= per_page <= 100
    ):
        raise ValueError("per_page must be 1..100")
    if cursor is not None and (
        not isinstance(cursor, str)
        or not cursor
        or len(cursor) > 4096
        or any(ord(character) < 33 for character in cursor)
    ):
        raise ValueError("cursor is invalid")
    parameters = {
        "filter": "cites:" + "|".join(targets),
        "select": _FIELDS,
        "per_page": str(per_page),
        "cursor": "*" if cursor is None else cursor,
    }
    return "/works?" + urlencode(parameters), canonical_json(parameters)


def fetch_openalex_citation_page(
    *,
    target_provider_ids: tuple[str, ...],
    cursor: str | None,
    per_page: int,
    provenance: RecordMeta,
    permission_evidence_hash: str,
    retention_policy_hash: str,
) -> FetchedOpenAlexPage:
    """Fetch one anonymous page; callers own pacing, persistence and pagination."""

    return _fetch_page(
        target_provider_ids=target_provider_ids,
        cursor=cursor,
        per_page=per_page,
        provenance=provenance,
        permission_evidence_hash=permission_evidence_hash,
        retention_policy_hash=retention_policy_hash,
        host="api.openalex.org",
        port=443,
        context=ssl.create_default_context(),
    )


def _fetch_page(
    *,
    target_provider_ids: tuple[str, ...],
    cursor: str | None,
    per_page: int,
    provenance: RecordMeta,
    permission_evidence_hash: str,
    retention_policy_hash: str,
    host: str,
    port: int,
    context: ssl.SSLContext,
    max_bytes: int = _MAX_BYTES,
    timeout_seconds: float = _TIMEOUT_SECONDS,
) -> FetchedOpenAlexPage:
    """Private endpoint seam for loopback TLS protocol tests."""

    if not isinstance(provenance, RecordMeta):
        raise ValueError("verified capture provenance is required")
    validate_sha256(permission_evidence_hash)
    validate_sha256(retention_policy_hash)
    if not 0 < max_bytes <= _MAX_BYTES or not 0 < timeout_seconds <= _TIMEOUT_SECONDS:
        raise ValueError("fetch limits are invalid")
    path, request_parameters = _request(target_provider_ids, cursor, per_page)
    requested_url = f"https://{host}{':' + str(port) if port != 443 else ''}{path}"
    start = _now()
    monotonic_start = time.monotonic()
    status: int | None = None
    payload: bytes | None = None
    failure: str | None = None
    observed: tuple[tuple[str, str], ...] = ()
    deadline = monotonic_start + timeout_seconds
    connection = _DeadlineHTTPSConnection(
        host, port, context=context, deadline=deadline
    )
    try:
        connection.request(
            "GET",
            path,
            headers={"Accept": "application/json", "Accept-Encoding": "identity"},
        )
        response = connection.getresponse()
        status = response.status
        observed = tuple(
            (name.lower(), value)
            for name, value in response.getheaders()
            if name.lower()
            in {
                "x-ratelimit-remaining",
                "x-ratelimit-reset",
                "x-ratelimit-limit",
                "x-ratelimit-credits-used",
                "retry-after",
            }
        )
        if status != 200:
            failure = "not_found" if status == 404 else "rejected"
        elif response.getheader("Content-Encoding", "identity").lower() != "identity":
            failure = "invalid_payload"
        else:
            chunks: list[bytes] = []
            size = 0
            while True:
                _remaining(deadline)
                chunk = response.read1(min(65536, max_bytes - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    failure = "invalid_payload"
                    break
                chunks.append(chunk)
            if failure is None and response.length not in (None, 0):
                failure = "transport"
            if failure is None:
                raw = b"".join(chunks)
                try:
                    value = canonical_loads(raw)
                    if not isinstance(value, dict):
                        raise ValueError("OpenAlex response envelope is invalid")
                    response_meta = value.get("meta")
                    if (
                        not isinstance(response_meta, dict)
                        or "next_cursor" not in response_meta
                        or not isinstance(value.get("results"), list)
                    ):
                        raise ValueError("OpenAlex response envelope is invalid")
                except ValueError:
                    failure = "invalid_payload"
                else:
                    _remaining(deadline)
                    payload = raw
    except TimeoutError:
        failure = "timeout"
    except (OSError, http.client.HTTPException):
        failure = "transport"
    finally:
        connection.close_owned()
    completed = _now()
    elapsed = time.monotonic() - monotonic_start
    access = SourceAccess(
        schema_version=provenance.schema_version,
        input_hashes=provenance.input_hashes,
        producer_version=provenance.producer_version,
        config_hash=provenance.config_hash,
        created_at=completed,
        source="openalex",
        requested_url=requested_url,
        request_parameters_hash=sha256(request_parameters).hexdigest(),
        adapter_version="openalex-anonymous-citations-v1",
        capture_started_at=start,
        capture_completed_at=completed,
        http_status=status,
        retained_payload_hash=sha256(payload).hexdigest()
        if payload is not None
        else None,
        retention_policy_hash=retention_policy_hash,
        license_expression="CC0-1.0",
        permission_evidence_hash=permission_evidence_hash,
        failure=failure,
    )
    return FetchedOpenAlexPage(access, payload, request_parameters, observed, elapsed)
