"""The versioned JSON contract every web app serves under ``/api/v1`` (#249).

Each HTML route has a JSON twin built from the same view context its
template renders, so the two can never disagree about what a page shows.
Success is ``{"contract": "1", "data": ...}``, a refusal is
``{"contract": "1", "error": {"code", "message", "field"}}``, a list is
``{"items", "next_cursor"}``. A v1 field is never renamed or removed; a
breaking change is ``/api/v2``. The schemas are ``docs/contracts/api-v1/``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import threading
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Final
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from research_agent.contracts.primitives import validate_utc_instant

CONTRACT: Final[str] = "1"
PREFIX: Final[str] = "/api/v1"
MAX_IDEMPOTENCY_KEY_LENGTH: Final[int] = 255

#: The closed set of refusal codes, one per status the apps answer with.
ERROR_CODES: Final[Mapping[int, str]] = {
    400: "invalid_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    409: "state_conflict",
    422: "invalid_request",
    502: "not_saved",
    503: "unavailable",
}


class ApiError(Exception):
    """A refusal on a JSON route, rendered as the contract's error envelope."""

    def __init__(
        self, status_code: int, message: str, *, field: str | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.field = field


def ok(data: Mapping[str, Any], *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        {"contract": CONTRACT, "data": jsonable(data)}, status_code=status_code
    )


def refusal(status_code: int, message: str, field: str | None = None) -> JSONResponse:
    return JSONResponse(
        {
            "contract": CONTRACT,
            "error": {
                "code": ERROR_CODES[status_code],
                "message": message,
                "field": field,
            },
        },
        status_code=status_code,
    )


def listing(items: Sequence[Any], next_cursor: str | None = None) -> dict[str, Any]:
    return {"items": list(items), "next_cursor": next_cursor}


def utc_instant(value: datetime) -> str:
    """Format an aware datetime in the repository's one UTC instant format."""
    text = value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return validate_utc_instant(text)


def jsonable(value: Any) -> Any:
    """A view context as plain JSON values; dataclasses become objects."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: jsonable(getattr(value, item.name))
            for item in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def is_api(request: Request) -> bool:
    return request.url.path.startswith(f"{PREFIX}/")


def install(app: FastAPI) -> None:
    """Render every refusal on an ``/api/v1`` path as the error envelope.

    HTML routes keep FastAPI's own error bodies; a shared dependency such as
    the session check raises one exception and each path renders it in its
    own form.
    """

    async def on_api_error(request: Request, error: Exception) -> Response:
        assert isinstance(error, ApiError)
        return refusal(error.status_code, error.message, error.field)

    async def on_http_error(request: Request, error: Exception) -> Response:
        assert isinstance(error, HTTPException)
        if not is_api(request) or error.status_code not in ERROR_CODES:
            return await http_exception_handler(request, error)
        return refusal(error.status_code, str(error.detail))

    async def on_validation_error(request: Request, error: Exception) -> Response:
        assert isinstance(error, RequestValidationError)
        if not is_api(request):
            return await request_validation_exception_handler(request, error)
        first = error.errors()[0] if error.errors() else {}
        location = first.get("loc", ())
        return refusal(
            422,
            str(first.get("msg", "request is not an admitted value")),
            str(location[-1]) if location else None,
        )

    app.add_exception_handler(ApiError, on_api_error)
    app.add_exception_handler(HTTPException, on_http_error)
    app.add_exception_handler(RequestValidationError, on_validation_error)


async def raw_body(request: Request) -> bytes:
    return await request.body()


def json_fields(
    body: bytes,
    required: Sequence[str],
    optional: Sequence[str] = (),
) -> dict[str, str]:
    """A closed JSON object of string fields; anything else is a 422 naming its field.

    An empty body is the empty object, for a command that takes no fields.
    """
    try:
        parsed = json.loads(body) if body else {}
    except (ValueError, UnicodeDecodeError) as error:
        raise ApiError(422, "request body is not JSON") from error
    if not isinstance(parsed, dict):
        raise ApiError(422, "request body is not a JSON object")
    for name in parsed:
        if name not in required and name not in optional:
            raise ApiError(422, "field is not admitted", field=name)
    for name in required:
        if name not in parsed:
            raise ApiError(422, "field is required", field=name)
    for name, value in parsed.items():
        if not isinstance(value, str):
            raise ApiError(422, "field must be a string", field=name)
    return parsed


def post_headers(
    x_csrf_token: str | None = Header(None),
    idempotency_key: str | None = Header(None),
) -> tuple[str, str]:
    """The two headers every state-changing JSON request carries.

    The CSRF token is checked against the session by the route that owns the
    session; here it only has to be present.
    """
    if not x_csrf_token:
        raise ApiError(403, "CSRF token is missing", field="X-CSRF-Token")
    if not idempotency_key or len(idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise ApiError(
            400, "Idempotency-Key is missing or too long", field="Idempotency-Key"
        )
    return x_csrf_token, idempotency_key


def derived_id(purpose: str, principal: str, key: str) -> UUID:
    """A stable storage id for one principal's ``Idempotency-Key``.

    Scoping by principal keeps two sessions that happen to send the same key
    from colliding in storage's own idempotency record, and deriving rather
    than drawing lets storage replay a retry that outlived this process.
    Storage admits only UUIDv4 ids, so the digest is given that form.
    """
    digest = hashlib.sha256(f"{purpose}\n{principal}\n{key}".encode()).digest()
    return UUID(bytes=digest[:16], version=4)


class IdempotencyCache:
    """Replays the first answer to a principal's reused ``Idempotency-Key``.

    The same key with the same request returns the stored response, marked
    ``X-Replayed: true``, and runs nothing; the same key with a different
    request, or while the first is still running, is a 409. Server failures
    are not stored, so a retry after one runs again. Entries live as long as
    the process, like the sessions they are scoped to.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, str], tuple[str, JSONResponse | None]] = {}

    @staticmethod
    def fingerprint(request: Request, body: bytes) -> str:
        return hashlib.sha256(
            f"{request.method} {request.url.path}\n".encode() + body
        ).hexdigest()

    def begin(self, principal: str, key: str, fingerprint: str) -> JSONResponse | None:
        with self._lock:
            entry = self._entries.get((principal, key))
            if entry is None:
                self._entries[(principal, key)] = (fingerprint, None)
                return None
        stored_fingerprint, response = entry
        if stored_fingerprint != fingerprint:
            raise ApiError(
                409,
                "Idempotency-Key was used for another request",
                field="Idempotency-Key",
            )
        if response is None:
            raise ApiError(409, "request with this Idempotency-Key is still running")
        replay = JSONResponse(
            json.loads(bytes(response.body)), status_code=response.status_code
        )
        replay.headers["X-Replayed"] = "true"
        return replay

    def finish(
        self, principal: str, key: str, fingerprint: str, response: JSONResponse
    ) -> JSONResponse:
        with self._lock:
            if response.status_code >= 500:
                self._entries.pop((principal, key), None)
            else:
                self._entries[(principal, key)] = (fingerprint, response)
        return response

    def abandon(self, principal: str, key: str) -> None:
        with self._lock:
            entry = self._entries.get((principal, key))
            if entry is not None and entry[1] is None:
                del self._entries[(principal, key)]

    def run(
        self,
        principal: str,
        key: str,
        fingerprint: str,
        handler: Callable[[], JSONResponse],
    ) -> JSONResponse:
        """Run ``handler`` once for this key, turning its refusal into a stored answer."""
        replay = self.begin(principal, key, fingerprint)
        if replay is not None:
            return replay
        try:
            response = handler()
        except ApiError as error:
            response = refusal(error.status_code, error.message, error.field)
        except HTTPException as error:
            if error.status_code not in ERROR_CODES:
                self.abandon(principal, key)
                raise
            response = refusal(error.status_code, str(error.detail))
        except BaseException:
            self.abandon(principal, key)
            raise
        return self.finish(principal, key, fingerprint, response)
