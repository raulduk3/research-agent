"""Session-scoped rater identity and access control (PL-22)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

SESSION_COOKIE_NAME = "rater_session"
SESSION_LIFETIME = timedelta(hours=24)
CREDENTIAL_ITERATIONS = 200_000
PROVISIONED_RATER_COUNT = 2


class AuthenticationError(Exception):
    """Raised when a presented credential, session or CSRF token is refused."""


@dataclass(frozen=True, slots=True)
class RaterPrincipal:
    """One pseudonymous rater identity provisioned by the operator.

    ``salt`` and ``credential_hash`` are hex-encoded PBKDF2-HMAC-SHA256
    output; the raw credential is never stored.
    """

    rater_id: UUID
    salt: str
    credential_hash: str

    def matches(self, presented_credential: str) -> bool:
        computed = _hash_credential(presented_credential, self.salt)
        return hmac.compare_digest(computed, self.credential_hash)


def hash_credential(credential: str) -> tuple[str, str]:
    """Return a fresh ``(salt, credential_hash)`` pair for operator provisioning."""
    salt = secrets.token_hex(16)
    return salt, _hash_credential(credential, salt)


def _hash_credential(credential: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", credential.encode(), bytes.fromhex(salt), CREDENTIAL_ITERATIONS
    ).hex()


@dataclass(frozen=True, slots=True)
class RaterDirectory:
    """Exactly the two rater principals Appendix A: Launch profile provisions."""

    principals: tuple[RaterPrincipal, ...]

    def __post_init__(self) -> None:
        if len(self.principals) != PROVISIONED_RATER_COUNT:
            raise ValueError("exactly two rater identities must be provisioned")
        if len({principal.rater_id for principal in self.principals}) != len(
            self.principals
        ):
            raise ValueError("provisioned rater identities must be distinct")

    def authenticate(self, presented_credential: str) -> RaterPrincipal | None:
        """Return the matching principal, checking every principal regardless.

        Every stored hash is checked even after a match, so how long
        authentication takes cannot reveal which of the two raters, or
        whether either, a wrong credential came close to matching.
        """
        matched: RaterPrincipal | None = None
        for principal in self.principals:
            if principal.matches(presented_credential):
                matched = principal
        return matched


@dataclass(frozen=True, slots=True)
class RaterSession:
    """An opaque, time-boxed session naming exactly one authenticated rater."""

    session_id: str
    rater_id: UUID
    csrf_token: str
    expires_at: datetime

    def is_expired(self, *, now: datetime | None = None) -> bool:
        return (now or datetime.now(timezone.utc)) >= self.expires_at


class SessionStore:
    """Server-side opaque session state behind the rating app's session cookie.

    The cookie itself carries only an unguessable random id; the rater
    identity, expiry and CSRF token all live here, so a browser-supplied id
    can never select another rater's identity (PL-22).
    """

    def __init__(self) -> None:
        self._sessions: dict[str, RaterSession] = {}

    def issue(self, rater_id: UUID, *, now: datetime | None = None) -> RaterSession:
        current = now or datetime.now(timezone.utc)
        session = RaterSession(
            session_id=secrets.token_urlsafe(32),
            rater_id=rater_id,
            csrf_token=secrets.token_urlsafe(32),
            expires_at=current + SESSION_LIFETIME,
        )
        self._sessions[session.session_id] = session
        return session

    def get(
        self, session_id: str, *, now: datetime | None = None
    ) -> RaterSession | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.is_expired(now=now):
            del self._sessions[session_id]
            return None
        return session

    def revoke(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


def authenticate_session(
    store: SessionStore, session_id: str | None, *, now: datetime | None = None
) -> RaterSession:
    """Resolve a cookie value to an active session or refuse it outright."""
    if not session_id:
        raise AuthenticationError("no session cookie was presented")
    session = store.get(session_id, now=now)
    if session is None:
        raise AuthenticationError("session is absent or expired")
    return session


def verify_csrf(session: RaterSession, presented_token: str | None) -> None:
    """Refuse a state-changing request whose CSRF token does not match the session."""
    if not presented_token or not hmac.compare_digest(
        session.csrf_token, presented_token
    ):
        raise AuthenticationError("CSRF token does not match the active session")
