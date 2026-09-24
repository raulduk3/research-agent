"""The tool service's client of the shared model service (PL-08, #287).

The tools container holds no copy of the embedding model. A search query is
embedded by the one shared model service over its mutually authenticated
``POST /v1/embeddings/query`` route (``models.service.create_model_server``),
naming the representation the caller ranks against; the vector comes back
stamped with the identity that produced it.
"""

from __future__ import annotations

import math
import socket
import ssl
from http.client import HTTPException, HTTPResponse, HTTPSConnection
from pathlib import Path

from research_agent.contracts.canonical import (
    CanonicalJsonError,
    canonical_json,
    canonical_loads,
)
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_sha256,
)

from .service import MAXIMUM_QUERY_CHARS, EmbeddingResult

__all__ = ["ModelServiceClient", "ModelServiceError", "ModelTransportError"]

# A 768-coordinate vector is about 15 KiB of JSON.
_MAXIMUM_RESPONSE_BYTES = 256 * 1024


class ModelServiceError(Exception):
    """The model service answered with a typed refusal."""

    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class ModelTransportError(Exception):
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


class ModelServiceClient:
    """Embeds search queries through the shared model service, one request per call."""

    def __init__(
        self,
        *,
        connect_host: str,
        port: int,
        server_hostname: str,
        ca_file: Path,
        client_cert_file: Path,
        client_key_file: Path,
        timeout_seconds: float = 30.0,
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
            raise ValueError("model service endpoint or timeout is invalid")
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

    def embed_query(self, text: str, *, representation_hash: str) -> EmbeddingResult:
        """The query's vector under *representation_hash*, with its producer.

        A vector stamped with any other representation is refused here as
        well as by the service.
        """

        text = validate_non_empty_string(text)
        if len(text) > MAXIMUM_QUERY_CHARS:
            raise ContractValidationError("query text is too long")
        validate_sha256(representation_hash)
        status, body = self._post(
            "/v1/embeddings/query",
            canonical_json(
                {
                    "schema_version": 1,
                    "text": text,
                    "representation_hash": representation_hash,
                }
            ),
        )
        try:
            envelope = canonical_loads(body)
        except CanonicalJsonError as error:
            raise ModelTransportError(
                "model service answered malformed JSON"
            ) from error
        if not isinstance(envelope, dict) or set(envelope) != {
            "schema_version",
            "status",
            "data",
            "error",
        }:
            raise ModelTransportError("model service envelope is invalid")
        if status != 200:
            refusal = envelope["error"]
            if not isinstance(refusal, dict) or not isinstance(
                refusal.get("code"), str
            ):
                raise ModelTransportError("model service error envelope is invalid")
            raise ModelServiceError(
                status_code=status,
                code=str(refusal["code"]),
                message=str(refusal.get("message", "")),
            )
        data = envelope["data"]
        if (
            envelope["status"] != "ok"
            or not isinstance(data, dict)
            or set(data)
            != {
                "vector",
                "representation_hash",
                "model_id",
                "revision",
                "checkpoint_date",
            }
            or data["representation_hash"] != representation_hash
        ):
            raise ModelTransportError("model service query embedding is invalid")
        coordinates, model_id = data["vector"], data["model_id"]
        revision, checkpoint_date = data["revision"], data["checkpoint_date"]
        if (
            not isinstance(coordinates, list)
            or not coordinates
            or not isinstance(model_id, str)
            or not isinstance(revision, str)
            or not isinstance(checkpoint_date, str)
        ):
            raise ModelTransportError("model service query embedding is invalid")
        vector: list[float] = []
        for coordinate in coordinates:
            if (
                isinstance(coordinate, bool)
                or not isinstance(coordinate, (int, float))
                or not math.isfinite(coordinate)
            ):
                raise ModelTransportError("model service vector is not finite")
            vector.append(float(coordinate))
        return EmbeddingResult(
            vector=tuple(vector),
            representation_hash=representation_hash,
            model_id=model_id,
            revision=revision,
            checkpoint_date=checkpoint_date,
        )

    def _post(self, path: str, body: bytes) -> tuple[int, bytes]:
        connection = _BoundHTTPSConnection(
            self._connect_host,
            self._port,
            server_hostname=self._server_hostname,
            context=self._context,
            timeout=self._timeout,
        )
        try:
            connection.request(
                "POST",
                path,
                body=body,
                headers={"Content-Type": "application/json"},
            )
            raw: HTTPResponse = connection.getresponse()
            declared = raw.getheader("Content-Length", "")
            if not declared.isascii() or not declared.isdigit():
                raise ModelTransportError("model service response length is invalid")
            if int(declared) > _MAXIMUM_RESPONSE_BYTES:
                raise ModelTransportError("model service response is too large")
            payload = raw.read(_MAXIMUM_RESPONSE_BYTES + 1)
            if len(payload) != int(declared):
                raise ModelTransportError("model service response length is invalid")
            return raw.status, payload
        except ModelTransportError:
            raise
        except (HTTPException, OSError, ssl.SSLError) as error:
            raise ModelTransportError(
                "model service request outcome is unknown; request was not retried"
            ) from error
        finally:
            connection.close()
