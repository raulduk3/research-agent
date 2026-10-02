"""Island sessions: one shared credential per island, one signed token.

A visitor enters an island's credential and receives a signed token naming
that island. Nothing is stored for a session: the token is checked by its
signature and expiry, so there is no session table and no chat transcript
row. A browser on another origin sends the token as a bearer header; a
same-site browser may rely on the cookie, and then every POST must also
carry the token's CSRF value.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime

from research_agent.beta.config import BetaConfig
from research_agent.beta.errors import Unauthenticated

COOKIE = "swarm_session"
OPERATOR = "operator"


@dataclass(frozen=True)
class Session:
    role: str
    #: The island an island session is bound to; ``None`` for the operator.
    island_id: str | None
    expires_at: int
    token: str
    csrf_token: str

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


def _csrf(secret: str, token: str) -> str:
    return _sign(secret, f"csrf:{token}")[:32]


def _issue(
    config: BetaConfig, role: str, island_id: str | None, now: datetime
) -> Session:
    expires = int(now.timestamp()) + config.session_ttl_seconds
    claims = json.dumps(
        {"role": role, "island": island_id, "exp": expires}, sort_keys=True
    )
    body = base64.urlsafe_b64encode(claims.encode()).decode().rstrip("=")
    token = f"v1.{body}.{_sign(config.session_secret, body)}"
    return Session(role, island_id, expires, token, _csrf(config.session_secret, token))


def open_island_session(config: BetaConfig, credential: str, now: datetime) -> Session:
    """Exchange a credential for a session bound to the island it belongs to."""
    if _same(credential, config.operator_token):
        return _issue(config, OPERATOR, None, now)
    matched: str | None = None
    for island_id, password in config.island_passwords.items():
        # Every password is compared, so timing does not name the island.
        if _same(credential, password):
            matched = island_id
    if matched is None:
        raise Unauthenticated("that credential opens no island", "credential")
    return _issue(config, "island", matched, now)


def read_session(config: BetaConfig, token: str, now: datetime) -> Session:
    """Check a token's signature and expiry and return the session it names."""
    if _same(token, config.operator_token):
        # The operator token itself is accepted as a bearer, for scripts and cron.
        return Session(OPERATOR, None, 0, token, _csrf(config.session_secret, token))
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
    return Session(role, island, expires, token, _csrf(config.session_secret, token))
