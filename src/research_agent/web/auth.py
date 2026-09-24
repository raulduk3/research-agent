"""Session-scoped rater and owner identity and access control (PL-22, #139)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from urllib.parse import SplitResult, urlsplit
from uuid import UUID

from research_agent.storage.client import StorageClient
from research_agent.storage.owners import OwnerRepository
from research_agent.storage.raters import RATER_ISLANDS

SESSION_COOKIE_NAME = "rater_session"
SESSION_LIFETIME = timedelta(hours=24)
PRELOGIN_CSRF_COOKIE_NAME = "prelogin_csrf"
PRELOGIN_CSRF_LIFETIME = timedelta(minutes=10)
CREDENTIAL_ITERATIONS = 200_000

#: The owner session cookie is named separately from the rater cookie so a
#: browser holding both never confuses one principal's session for the
#: other's -- the two apps are never the same origin (#139).
OWNER_SESSION_COOKIE_NAME = "owner_session"


class AuthenticationError(Exception):
    """Raised when a presented credential, session or CSRF token is refused."""


@dataclass(frozen=True, slots=True)
class RaterPrincipal:
    """One pseudonymous rater identity provisioned by the operator.

    ``salt`` and ``credential_hash`` are hex-encoded PBKDF2-HMAC-SHA256
    output; the raw credential is never stored. ``island`` is the one rated
    island (SDD-PL-22) this principal is bound to (DeploymentBindings.rater_islands).
    """

    rater_id: UUID
    island: str
    salt: str
    credential_hash: str

    def __post_init__(self) -> None:
        if self.island not in RATER_ISLANDS:
            raise ValueError("rater principal island is not an admitted value")

    def matches(self, presented_credential: str) -> bool:
        computed = _hash_credential(presented_credential, self.salt)
        return hmac.compare_digest(computed, self.credential_hash)

    @property
    def credential_fingerprint(self) -> str:
        """Name the provisioned credential without retaining its raw value."""
        material = bytes.fromhex(self.salt) + bytes.fromhex(self.credential_hash)
        return hashlib.sha256(material).hexdigest()


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
    """Resolves the operator-provisioned rater principals through storage.

    No principal lives in this process; every credential check reads the
    current stored binding and salted hash (TDD-2.1.47). Session revalidation
    uses that same stored binding rather than retaining a second directory.
    """

    storage: StorageClient

    def principals(self) -> tuple[RaterPrincipal, ...]:
        """Read the current principals from storage."""
        return tuple(
            RaterPrincipal(
                rater_id=record.rater_id,
                island=record.island,
                salt=record.salt,
                credential_hash=record.credential_hash,
            )
            for record in self.storage.list_raters()
        )

    def find(self, rater_id: UUID) -> RaterPrincipal | None:
        """Return the principal as currently provisioned, or ``None`` if revoked."""
        for principal in self.principals():
            if principal.rater_id == rater_id:
                return principal
        return None

    def authenticate(self, presented_credential: str) -> RaterPrincipal | None:
        """Return the matching principal, checking every principal regardless.

        Every stored hash is checked even after a match, so how long
        authentication takes cannot reveal which of the two raters, or
        whether either, a wrong credential came close to matching.
        """
        matched: RaterPrincipal | None = None
        for principal in self.principals():
            if principal.matches(presented_credential):
                matched = principal
        return matched


def authorize_island(principal: RaterPrincipal, requested_island: str) -> None:
    """Refuse access to a digest of an island the principal is not bound to.

    Storage binds each rater to exactly one island (DeploymentBindings.rater_islands);
    a rater's own credential never admits another island's digest (PL-22, EN-32).
    """
    if requested_island not in RATER_ISLANDS or principal.island != requested_island:
        raise AuthenticationError("rater is not bound to the requested island")


@dataclass(frozen=True, slots=True)
class RaterSession:
    """An opaque, time-boxed session naming exactly one authenticated rater."""

    session_id: str
    rater_id: UUID
    csrf_token: str
    expires_at: datetime
    island: str | None = None
    credential_fingerprint: str | None = None

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

    def issue(
        self, principal: RaterPrincipal | UUID, *, now: datetime | None = None
    ) -> RaterSession:
        current = now or datetime.now(timezone.utc)
        if isinstance(principal, RaterPrincipal):
            rater_id = principal.rater_id
            island: str | None = principal.island
            credential_fingerprint: str | None = principal.credential_fingerprint
        else:
            rater_id = principal
            island = None
            credential_fingerprint = None
        session = RaterSession(
            session_id=secrets.token_urlsafe(32),
            rater_id=rater_id,
            csrf_token=secrets.token_urlsafe(32),
            expires_at=current + SESSION_LIFETIME,
            island=island,
            credential_fingerprint=credential_fingerprint,
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
    store: SessionStore,
    session_id: str | None,
    *,
    directory: RaterDirectory | None = None,
    now: datetime | None = None,
) -> RaterSession:
    """Resolve an active session and optionally revalidate its principal binding."""
    if not session_id:
        raise AuthenticationError("no session cookie was presented")
    session = store.get(session_id, now=now)
    if session is None:
        raise AuthenticationError("session is absent or expired")
    if directory is not None:
        principal = directory.find(session.rater_id)
        if (
            principal is None
            or session.island is None
            or session.credential_fingerprint is None
            or principal.island != session.island
            or not hmac.compare_digest(
                principal.credential_fingerprint, session.credential_fingerprint
            )
        ):
            store.revoke(session.session_id)
            raise AuthenticationError("session principal is absent or changed")
    return session


def verify_csrf(session: RaterSession, presented_token: str | None) -> None:
    """Refuse a state-changing request whose CSRF token does not match the session."""
    if not _token_matches(session.csrf_token, presented_token):
        raise AuthenticationError("CSRF token does not match the active session")


@dataclass(frozen=True, slots=True)
class OwnerPrincipal:
    """The one operator-provisioned owner identity the actions app admits (#139).

    ``salt`` and ``credential_hash`` are hex-encoded PBKDF2-HMAC-SHA256
    output; the raw credential is never stored, the same scheme
    :class:`RaterPrincipal` uses.
    """

    owner_id: UUID
    salt: str
    credential_hash: str

    def matches(self, presented_credential: str) -> bool:
        computed = _hash_credential(presented_credential, self.salt)
        return hmac.compare_digest(computed, self.credential_hash)


@dataclass(frozen=True, slots=True)
class OwnerDirectory:
    """Resolves the operator-provisioned owner principal through storage.

    No principal lives in this process; every credential check reads the
    salted hash storage holds, the same boundary :class:`RaterDirectory`
    draws, so a credential revoked or rotated at the operator path takes
    effect without restarting the owner actions app.
    """

    repository: OwnerRepository

    def authenticate(self, presented_credential: str) -> OwnerPrincipal | None:
        """Return the matching principal, checking every principal regardless.

        Every stored hash is checked even after a match, so how long
        authentication takes cannot reveal whether a wrong credential came
        close to matching (the same constant-time discipline
        :class:`RaterDirectory` applies).
        """
        matched: OwnerPrincipal | None = None
        for record in self.repository.list_principals():
            principal = OwnerPrincipal(
                owner_id=UUID(record["owner_id"]),
                salt=record["salt"],
                credential_hash=record["credential_hash"],
            )
            if principal.matches(presented_credential):
                matched = principal
        return matched


@dataclass(frozen=True, slots=True)
class OwnerSession:
    """An opaque, time-boxed session naming the authenticated owner principal."""

    session_id: str
    owner_id: UUID
    csrf_token: str
    expires_at: datetime

    def is_expired(self, *, now: datetime | None = None) -> bool:
        return (now or datetime.now(timezone.utc)) >= self.expires_at


def _token_matches(expected_token: str, presented_token: str | None) -> bool:
    if not presented_token:
        return False
    try:
        presented = presented_token.encode("ascii")
    except UnicodeEncodeError:
        return False
    return hmac.compare_digest(expected_token.encode("ascii"), presented)


def verify_origin(presented_origin: str | None, expected_origin: str) -> None:
    """Require a browser mutation to name the configured application origin."""
    expected = _parse_origin(expected_origin, trusted=True)
    if presented_origin is None:
        raise AuthenticationError("request Origin is missing")
    try:
        presented = _parse_origin(presented_origin, trusted=False)
    except ValueError as error:
        raise AuthenticationError("request Origin is invalid") from error
    if presented != expected:
        raise AuthenticationError("request Origin does not match the application")


def _parse_origin(value: str, *, trusted: bool) -> tuple[str, str, int | None]:
    error_type = ValueError
    if not value or value == "null":
        raise error_type("origin is not an admitted value")
    try:
        parsed: SplitResult = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise error_type("origin is not a valid URL") from error
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        qualifier = "configured" if trusted else "request"
        raise error_type(f"{qualifier} origin is not an admitted origin")
    if port == (443 if parsed.scheme == "https" else 80):
        port = None
    return parsed.scheme, parsed.hostname.lower(), port


@dataclass(frozen=True, slots=True)
class PreLoginCSRFToken:
    """One short-lived form token bound to an opaque pre-login cookie."""

    cookie_token: str
    form_token: str
    expires_at: datetime

    def is_expired(self, *, now: datetime | None = None) -> bool:
        return (now or datetime.now(timezone.utc)) >= self.expires_at


class OwnerSessionStore:
    """Server-side opaque session state behind the owner actions app's cookie.

    The cookie carries only an unguessable random id; the owner identity,
    expiry and CSRF token all live here, the same boundary
    :class:`SessionStore` draws for a rater session.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, OwnerSession] = {}

    def issue(self, owner_id: UUID, *, now: datetime | None = None) -> OwnerSession:
        current = now or datetime.now(timezone.utc)
        session = OwnerSession(
            session_id=secrets.token_urlsafe(32),
            owner_id=owner_id,
            csrf_token=secrets.token_urlsafe(32),
            expires_at=current + SESSION_LIFETIME,
        )
        self._sessions[session.session_id] = session
        return session

    def get(
        self, session_id: str, *, now: datetime | None = None
    ) -> OwnerSession | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.is_expired(now=now):
            del self._sessions[session_id]
            return None
        return session

    def revoke(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


def authenticate_owner_session(
    store: OwnerSessionStore, session_id: str | None, *, now: datetime | None = None
) -> OwnerSession:
    """Resolve a cookie value to an active owner session or refuse it outright."""
    if not session_id:
        raise AuthenticationError("no session cookie was presented")
    session = store.get(session_id, now=now)
    if session is None:
        raise AuthenticationError("session is absent or expired")
    return session


def verify_owner_csrf(session: OwnerSession, presented_token: str | None) -> None:
    """Refuse a state-changing request whose CSRF token does not match the session."""
    if not presented_token or not hmac.compare_digest(
        session.csrf_token, presented_token
    ):
        raise AuthenticationError("CSRF token does not match the active session")


class PreLoginCSRFStore:
    """Issues and atomically consumes pre-session login form tokens."""

    def __init__(self) -> None:
        self._tokens: dict[str, PreLoginCSRFToken] = {}
        self._lock = Lock()

    def issue(self, *, now: datetime | None = None) -> PreLoginCSRFToken:
        current = now or datetime.now(timezone.utc)
        token = PreLoginCSRFToken(
            cookie_token=secrets.token_urlsafe(32),
            form_token=secrets.token_urlsafe(32),
            expires_at=current + PRELOGIN_CSRF_LIFETIME,
        )
        with self._lock:
            self._discard_expired(now=current)
            self._tokens[token.cookie_token] = token
        return token

    def current(
        self, cookie_token: str | None, *, now: datetime | None = None
    ) -> PreLoginCSRFToken | None:
        """The live token a cookie names, left unconsumed, or ``None``.

        A browser may fetch the sign-in form twice before submitting it (a
        prefetch, then the navigation); reusing the live token keeps the
        rendered form valid. Only a POST or expiry rotates it.
        """
        if not cookie_token:
            return None
        current = now or datetime.now(timezone.utc)
        with self._lock:
            token = self._tokens.get(cookie_token)
        if token is None or token.is_expired(now=current):
            return None
        return token

    def consume(
        self,
        cookie_token: str | None,
        presented_token: str | None,
        *,
        now: datetime | None = None,
    ) -> None:
        """Consume one cookie-bound token, including on a failed token attempt."""
        if not cookie_token:
            raise AuthenticationError("pre-login CSRF cookie is missing")
        with self._lock:
            token = self._tokens.pop(cookie_token, None)
        if token is None:
            raise AuthenticationError("pre-login CSRF token is absent or already used")
        if token.is_expired(now=now):
            raise AuthenticationError("pre-login CSRF token is expired")
        if not _token_matches(token.form_token, presented_token):
            raise AuthenticationError("pre-login CSRF token does not match its cookie")

    def _discard_expired(self, *, now: datetime) -> None:
        expired = [
            cookie_token
            for cookie_token, token in self._tokens.items()
            if token.is_expired(now=now)
        ]
        for cookie_token in expired:
            del self._tokens[cookie_token]
