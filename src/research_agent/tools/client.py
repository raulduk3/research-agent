"""The run worker's client of the shared tool service (PL-20, #323).

A run worker reaches the one tool service over its mutually authenticated
``POST /v1/calls`` route (``tools.http.create_tool_server``). Each call
goes out once, never retried: the service records a call before it runs
(TDD-2.1.2), so a second send would be a second call. :meth:`for_run`
binds the client to the snapshot the run's own trusted context names
(TDD-3.1.51) and is the run loop's dispatcher (``agents.loop``).
"""

from __future__ import annotations

import json
import math
import socket
import ssl
from http.client import HTTPException, HTTPResponse, HTTPSConnection
from pathlib import Path

from research_agent.agents.loop import ToolCall, ToolOutcome
from research_agent.contracts.canonical import (
    CanonicalJsonError,
    canonical_json,
    canonical_loads,
)
from research_agent.contracts.primitives import validate_sha256

from .http import OUTCOME_FIELDS

__all__ = [
    "RemoteRunToolDispatcher",
    "ToolServiceClient",
    "ToolServiceError",
    "ToolTransportError",
]

# A deep read of three rendered pages is the largest answer a run receives.
_MAXIMUM_RESPONSE_BYTES = 64 * 1024 * 1024
_OUTCOME_STATUSES = frozenset({"ok", "refused", "error"})


class ToolServiceError(Exception):
    """The tool service answered with a typed refusal of the request itself."""

    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class ToolTransportError(Exception):
    """One transport attempt failed or answered malformed bytes; not retried."""


class _BoundHTTPSConnection(HTTPSConnection):
    def __init__(
        self,
        connect_host: str,
        port: int,
        *,
        server_hostname: str,
        context: ssl.SSLContext,
        timeout: float,
    ) -> None:
        super().__init__(server_hostname, port, timeout=timeout, context=context)
        self._connect_host = connect_host
        self._server_hostname = server_hostname
        self._tls_context = context

    def connect(self) -> None:
        raw = socket.create_connection((self._connect_host, self.port), self.timeout)
        try:
            self.sock = self._tls_context.wrap_socket(
                raw, server_hostname=self._server_hostname
            )
        except BaseException:
            raw.close()
            raise


class ToolServiceClient:
    """Forwards a run's tool calls to the shared tool service, one per request."""

    def __init__(
        self,
        *,
        connect_host: str,
        port: int,
        server_hostname: str,
        ca_file: Path,
        client_cert_file: Path,
        client_key_file: Path,
        timeout_seconds: float = 120.0,
    ) -> None:
        if (
            not connect_host
            or not server_hostname
            or isinstance(port, bool)
            or not isinstance(port, int)
            or not 1 <= port <= 65535
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("tool service endpoint or timeout is invalid")
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_file)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_cert_chain(client_cert_file, client_key_file)
        self._connect_host = connect_host
        self._port = port
        self._server_hostname = server_hostname
        self._context = context
        self._timeout = float(timeout_seconds)

    def for_run(self, snapshot_id: str) -> RemoteRunToolDispatcher:
        """One run's dispatcher, bound to the snapshot its context names."""

        return RemoteRunToolDispatcher(self, snapshot_id=validate_sha256(snapshot_id))

    def call(
        self,
        *,
        run_id: str,
        snapshot_id: str,
        tool_call_id: str,
        tool: str,
        raw_call: object,
    ) -> ToolOutcome:
        """The service's answer to one call of *run_id*, sent once."""

        # ASCII JSON text keeps a value canonical JSON refuses -- a nonfinite
        # number, a lone surrogate -- for the service's admission to refuse.
        encoded_call = json.dumps(raw_call, ensure_ascii=True)
        status, body = self._request(
            "POST",
            "/v1/calls",
            canonical_json(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "snapshot_id": snapshot_id,
                    "tool_call_id": tool_call_id,
                    "tool": tool,
                    "call": encoded_call,
                }
            ),
        )
        try:
            envelope = canonical_loads(body)
        except CanonicalJsonError as error:
            raise ToolTransportError("tool service answered malformed JSON") from error
        if not isinstance(envelope, dict) or set(envelope) != {
            "schema_version",
            "status",
            "data",
            "error",
        }:
            raise ToolTransportError("tool service envelope is invalid")
        if status != 200:
            refusal = envelope["error"]
            if not isinstance(refusal, dict) or not isinstance(
                refusal.get("code"), str
            ):
                raise ToolTransportError("tool service error envelope is invalid")
            raise ToolServiceError(
                status_code=status,
                code=str(refusal["code"]),
                message=str(refusal.get("message", "")),
            )
        data = envelope["data"]
        if (
            envelope["status"] != "ok"
            or not isinstance(data, dict)
            or set(data) != OUTCOME_FIELDS
            or data["tool_call_id"] != tool_call_id
            or data["status"] not in _OUTCOME_STATUSES
            or not isinstance(data["envelope"], dict)
            or not isinstance(data["accepted_submit"], bool)
        ):
            raise ToolTransportError("tool service outcome is invalid")
        deep_reads, images = data["deep_reads"], data["images"]
        for count in (deep_reads, images):
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ToolTransportError("tool service outcome is invalid")
        assert isinstance(deep_reads, int) and isinstance(images, int)
        return ToolOutcome(
            str(data["status"]),
            dict(data["envelope"]),
            deep_reads=deep_reads,
            images=images,
            accepted_submit=data["accepted_submit"],
        )

    def health(self) -> str:
        """The service's readiness state, as ``GET /health`` reports it."""

        status, body = self._request("GET", "/health", None)
        try:
            envelope = canonical_loads(body)
        except CanonicalJsonError as error:
            raise ToolTransportError("tool service answered malformed JSON") from error
        data = envelope.get("data") if isinstance(envelope, dict) else None
        state = data.get("state") if isinstance(data, dict) else None
        if status != 200 or not isinstance(state, str):
            raise ToolTransportError("tool service health is invalid")
        return state

    def _request(self, method: str, path: str, body: bytes | None) -> tuple[int, bytes]:
        connection = _BoundHTTPSConnection(
            self._connect_host,
            self._port,
            server_hostname=self._server_hostname,
            context=self._context,
            timeout=self._timeout,
        )
        try:
            connection.request(
                method,
                path,
                body=body,
                headers={} if body is None else {"Content-Type": "application/json"},
            )
            raw: HTTPResponse = connection.getresponse()
            declared = raw.getheader("Content-Length", "")
            if not declared.isascii() or not declared.isdigit():
                raise ToolTransportError("tool service response length is invalid")
            if int(declared) > _MAXIMUM_RESPONSE_BYTES:
                raise ToolTransportError("tool service response is too large")
            payload = raw.read(_MAXIMUM_RESPONSE_BYTES + 1)
            if len(payload) != int(declared):
                raise ToolTransportError("tool service response length is invalid")
            return raw.status, payload
        except ToolTransportError:
            raise
        except (HTTPException, OSError, ssl.SSLError) as error:
            raise ToolTransportError(
                "tool service request outcome is unknown; request was not retried"
            ) from error
        finally:
            connection.close()


class RemoteRunToolDispatcher:
    """One run's loop-side view of the shared service, over its listener."""

    def __init__(self, client: ToolServiceClient, *, snapshot_id: str) -> None:
        self._client = client
        self._snapshot_id = snapshot_id

    def dispatch(self, call: ToolCall, *, run_id: str) -> ToolOutcome:
        return self._client.call(
            run_id=run_id,
            snapshot_id=self._snapshot_id,
            tool_call_id=call.tool_call_id,
            tool=call.name,
            raw_call=call.arguments,
        )
