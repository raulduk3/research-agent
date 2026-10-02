"""Refusals the API answers with, one class per error code.

A service raises the refusal; the application answers with its status and
``{"detail", "code", "field"}``.
"""

from __future__ import annotations


class Refusal(Exception):
    """A request the service declines, with the status and code it answers."""

    status = 400
    code = "invalid_request"

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field = field


class Invalid(Refusal):
    status = 422
    code = "invalid_request"


class Unauthenticated(Refusal):
    status = 401
    code = "unauthenticated"


class Forbidden(Refusal):
    status = 403
    code = "forbidden"


class NotFound(Refusal):
    status = 404
    code = "not_found"


class Conflict(Refusal):
    """The request is well formed and the current state refuses it.

    Budget refusals use this: the message starts with a reason code such as
    ``daily_hard_budget_exhausted`` so a client can branch on it.
    """

    status = 409
    code = "state_conflict"


class Unavailable(Refusal):
    status = 503
    code = "unavailable"
