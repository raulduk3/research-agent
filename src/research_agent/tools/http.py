"""The shared tool service's own listener (PL-20, #323).

One tool service runs in its own container and answers every run's calls
over mutually authenticated TLS. ``POST /v1/calls`` takes one call as the
run worker forwards it -- the run, the snapshot the run's trusted context
names, the model's ``tool_call_id``, the tool name and the call envelope --
and answers it through :class:`~research_agent.tools.service.ToolService`,
which admits, traces and answers it exactly as it does in process. The
reply carries the envelope the model receives and the budgets the answer
consumed, for the run's loop to charge (AG-12). ``GET /health`` reports
readiness to an admitted caller.

The call envelope travels as the ASCII JSON text the worker encoded, not
as a nested object: a call the model made with a value canonical JSON has
no form for (a nonfinite number, a lone surrogate) reaches the service as it
was made, so admission refuses it and the trace records it as it would in
process (TDD-2.1.2, TDD-2.1.5).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import UUID

from research_agent.contracts.canonical import (
    CanonicalJsonError,
    canonical_json,
    canonical_loads,
)
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_sha256,
)

from .service import ToolService

__all__ = ["CALL_FIELDS", "OUTCOME_FIELDS", "create_tool_server"]

#: The fields of one forwarded call; all are required and no other is admitted.
CALL_FIELDS = frozenset(
    {"schema_version", "run_id", "snapshot_id", "tool_call_id", "tool", "call"}
)
#: The fields of one answered call.
OUTCOME_FIELDS = frozenset(
    {"tool_call_id", "status", "envelope", "deep_reads", "images", "accepted_submit"}
)
# A submit with its rationales is the largest call a run makes.
_MAXIMUM_REQUEST_BYTES = 1024 * 1024


def create_tool_server(
    address: tuple[str, int],
    service: ToolService,
    *,
    tls_context: ssl.SSLContext,
    client_fingerprints: frozenset[str],
) -> ThreadingHTTPServer:
    """Serve *service* to the admitted run-worker certificates.

    ``POST /v1/calls`` and the readiness route ``GET /health``, over mutually
    authenticated TLS: a caller whose certificate fingerprint is not
    admitted is refused before its request is read.
    """

    if tls_context.verify_mode != ssl.CERT_REQUIRED:
        raise ValueError("the tool service requires verified client certificates")
    if not client_fingerprints:
        raise ValueError("at least one client certificate is required")
    for fingerprint in client_fingerprints:
        validate_sha256(fingerprint)

    class Handler(_ToolRequestHandler):
        tools = service
        fingerprints = client_fingerprints

    server = ThreadingHTTPServer(address, Handler)
    server.socket = tls_context.wrap_socket(server.socket, server_side=True)
    return server


class _ToolRequestHandler(BaseHTTPRequestHandler):
    tools: ToolService
    fingerprints: frozenset[str]
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802
        if not self._authenticated():
            self._reply(401, error="unauthenticated")
            return
        if self.path != "/v1/calls":
            self._reply(404, error="not_found")
            return
        try:
            request = self._call_request()
        except ContractValidationError as error:
            self._reply(422, error="invalid_input", message=str(error))
            return
        try:
            outcome = self.tools.call(
                run_id=request["run_id"],
                snapshot_id=request["snapshot_id"],
                tool=request["tool"],
                raw_call=request["call"],
            )
        except Exception:
            # A call the service could not answer fails the worker's
            # dispatch, as it would in process; its detail stays here.
            self._reply(500, error="internal_error", message="the call failed")
            return
        self._reply(
            200,
            data={
                "tool_call_id": request["tool_call_id"],
                "status": outcome.status,
                "envelope": outcome.data,
                "deep_reads": outcome.deep_reads,
                "images": outcome.images,
                "accepted_submit": outcome.accepted_submit,
            },
        )

    def do_GET(self) -> None:  # noqa: N802
        if not self._authenticated():
            self._reply(401, error="unauthenticated")
            return
        if self.path != "/health":
            self._reply(404, error="not_found")
            return
        self._reply(200, data={"state": "ready"})

    def _authenticated(self) -> bool:
        connection = self.connection
        if not isinstance(connection, ssl.SSLSocket):
            return False
        certificate = connection.getpeercert(binary_form=True)
        if certificate is None:
            return False
        supplied = hashlib.sha256(certificate).hexdigest()
        return any(
            hmac.compare_digest(supplied, fingerprint)
            for fingerprint in self.fingerprints
        )

    def _call_request(self) -> dict[str, Any]:
        if self.headers.get("Content-Type") != "application/json":
            raise ContractValidationError("Content-Type must be application/json")
        raw_length = self.headers.get("Content-Length", "")
        if not raw_length.isascii() or not raw_length.isdigit():
            raise ContractValidationError("a valid Content-Length is required")
        length = int(raw_length)
        if length > _MAXIMUM_REQUEST_BYTES:
            self.close_connection = True
            raise ContractValidationError("call request is too large")
        try:
            value = canonical_loads(self.rfile.read(length))
        except CanonicalJsonError as error:
            raise ContractValidationError(
                "call request is not canonical JSON"
            ) from error
        if not isinstance(value, dict) or set(value) != CALL_FIELDS:
            raise ContractValidationError("call request has unknown or missing fields")
        if isinstance(value["schema_version"], bool) or value["schema_version"] != 1:
            raise ContractValidationError("schema_version must be 1")
        run_id = value["run_id"]
        try:
            if not isinstance(run_id, str) or str(UUID(run_id)) != run_id:
                raise ValueError(run_id)
        except ValueError as error:
            raise ContractValidationError("run_id must be a UUID") from error
        validate_sha256(value["snapshot_id"])
        # The tool name and call id are the model's own; an unknown or empty
        # name is the service's to refuse and record, not the transport's.
        if not isinstance(value["tool_call_id"], str) or not isinstance(
            value["tool"], str
        ):
            raise ContractValidationError("tool_call_id and tool must be strings")
        if not isinstance(value["call"], str):
            raise ContractValidationError("call must be the call envelope's JSON text")
        try:
            call = json.loads(value["call"])
        except ValueError as error:
            raise ContractValidationError("call is not JSON") from error
        return {**value, "call": call}

    def _reply(
        self,
        status: int,
        *,
        data: dict[str, Any] | None = None,
        error: str | None = None,
        message: str = "",
    ) -> None:
        try:
            body = canonical_json(
                {
                    "schema_version": 1,
                    "status": "ok" if error is None else "error",
                    "data": data,
                    "error": None
                    if error is None
                    else {"code": error, "message": message[:512]},
                }
            )
        except CanonicalJsonError:
            self._reply(
                500, error="internal_error", message="the answer has no JSON form"
            )
            return
        if error is not None:
            # An unread or refused body must not be parsed as a next request.
            self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        # A call is agent-written text; the service logger owns safe metadata.
        return

    def _unsupported_method(self) -> None:
        self._reply(404, error="not_found")

    do_PUT = _unsupported_method
    do_PATCH = _unsupported_method
    do_DELETE = _unsupported_method
