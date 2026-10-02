"""Island sessions: one shared credential per island, one signed token.

A visitor picks an island and enters its credential, and receives a signed
token naming that island. The browser sends the token as a bearer header on
every later request. Nothing is stored for a session: the token is checked
by its signature and expiry, so there is no session table, no cookie and no
chat transcript row.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime

from research_agent.beta.config import BetaConfig
from research_agent.beta.errors import Forbidden, NotFound, Unauthenticated

OPERATOR = "operator"


@dataclass(frozen=True)
class Session:
    role: str
    #: The island an island session is bound to; ``None`` for the operator.
    island_id: str | None
    expires_at: int
    token: str

    @property
    def is_operator(self) -> bool:
        return self.role == OPERATOR

    @property
    def actor(self) -> str:
        return OPERATOR if self.is_operator else f"island:{self.island_id}"


def _sign(secret: str, text: str) -> str:
    return hmac.new(secret.encode(), text.encode(), hashlib.sha256).hexdigest()


def _same(given: str, expected: str | None) -> bool:
    return expected is not None and hmac.compare_digest(
        given.encode(), expected.encode()
    )


def _issue(
    config: BetaConfig, role: str, island_id: str | None, now: datetime
) -> Session:
    expires = int(now.timestamp()) + config.session_ttl_seconds
    claims = json.dumps(
        {"role": role, "island": island_id, "exp": expires}, sort_keys=True
    )
    body = base64.urlsafe_b64encode(claims.encode()).decode().rstrip("=")
    token = f"v1.{body}.{_sign(config.session_secret, body)}"
    return Session(role, island_id, expires, token)


def open_island_session(
    config: BetaConfig,
    credential: str,
    now: datetime,
    island_id: str | None = None,
    known_islands: frozenset[str] = frozenset(),
) -> Session:
    """Exchange a credential for a session bound to one island.

    With an island named, the credential must be that island's: an unknown
    island is not found and a wrong credential is forbidden. With none, the
    credential alone names the island it belongs to. The operator's
    credential opens an operator session either way.
    """
    if _same(credential, config.operator_token):
        return _issue(config, OPERATOR, None, now)
    if island_id is not None:
        if island_id not in known_islands:
            raise NotFound(f"no island {island_id}", "island")
        if not _same(credential, config.island_passwords.get(island_id)):
            raise Forbidden("that is not this island's credential", "password")
        return _issue(config, "island", island_id, now)
    matched: str | None = None
    for candidate, password in config.island_passwords.items():
        # Every password is compared, so timing does not name the island.
        if _same(credential, password):
            matched = candidate
    if matched is None:
        raise Unauthenticated("that credential opens no island", "credential")
    return _issue(config, "island", matched, now)


def read_session(config: BetaConfig, token: str, now: datetime) -> Session:
    """Check a token's signature and expiry and return the session it names."""
    if _same(token, config.operator_token):
        # The operator token itself is accepted as a bearer, for scripts and cron.
        return Session(OPERATOR, None, 0, token)
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "v1":
        raise Unauthenticated("the session token is not valid")
    if not _same(parts[2], _sign(config.session_secret, parts[1])):
        raise Unauthenticated("the session token is not valid")
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
        role, island, expires = (
            str(claims["role"]),
            claims["island"],
            int(claims["exp"]),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise Unauthenticated("the session token is not valid") from exc
    if expires <= int(now.timestamp()):
        raise Unauthenticated("the session has expired")
    return Session(role, island, expires, token)
