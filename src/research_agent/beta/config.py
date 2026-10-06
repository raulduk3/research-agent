"""Deployment configuration, read once from the environment.

Only what must not be edited from the app lives here: where the database is,
the secrets, the browser origins and the model provider. Everything a person
tunes while the swarm runs (islands, genomes, budget levers) is in the swarm
spec and is edited through the API with a revision history.
"""

from __future__ import annotations

import math
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path


class ConfigError(Exception):
    """The environment names a setting this deployment cannot start with."""


@dataclass(frozen=True)
class ModelProvider:
    """One chat-completions endpoint and the prices its receipts are computed from.

    Prices are USD per million tokens, which is also micro-dollars per token.
    A run is refused until the endpoint, key,
    model and both prices are stated. The transport timeout defaults to 300 seconds.
    """

    name: str
    endpoint: str
    api_key: str
    model: str
    input_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal
    send_max_tokens: bool = True
    timeout_seconds: float = 300.0


@dataclass(frozen=True)
class BetaConfig:
    database: Path
    session_secret: str
    island_passwords: Mapping[str, str] = field(default_factory=dict)
    operator_token: str | None = None
    allowed_origins: tuple[str, ...] = ()
    allowed_origin_regex: str | None = None
    session_ttl_seconds: int = 30 * 24 * 3600
    provider: ModelProvider | None = None
    arxiv_api: str = "https://export.arxiv.org/api/query"
    arxiv_delay_seconds: float = 3.0
    #: Seconds between the swarm advancing on its own; zero leaves it to a
    #: caller (the operator endpoint or the command line).
    tick_seconds: int = 0
    #: Seconds between ingestion passes the process starts itself; zero is off.
    ingest_seconds: int = 0


_PROVIDER_VARS = (
    "RESEARCH_AGENT_MODEL_ENDPOINT",
    "RESEARCH_AGENT_MODEL_API_KEY",
    "RESEARCH_AGENT_MODEL_ID",
    "RESEARCH_AGENT_MODEL_INPUT_USD_PER_MTOK",
    "RESEARCH_AGENT_MODEL_OUTPUT_USD_PER_MTOK",
)


def _flag(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name} must be true or false")


def _price(env: Mapping[str, str], name: str) -> Decimal:
    try:
        value = Decimal(env[name].strip())
    except InvalidOperation as exc:
        raise ConfigError(f"{name} must be a decimal number") from exc
    if value < 0:
        raise ConfigError(f"{name} must not be negative")
    return value


def _seconds(env: Mapping[str, str], name: str, default: int = 0) -> int:
    raw = env.get(name, "").strip() or str(default)
    if not raw.isdigit():
        raise ConfigError(f"{name} must be a whole number of seconds")
    return int(raw)


def _provider_timeout(env: Mapping[str, str]) -> float:
    name = "RESEARCH_AGENT_MODEL_TIMEOUT_SECONDS"
    raw = env.get(name, "").strip() or "300"
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be finite positive seconds") from exc
    if not math.isfinite(value) or value <= 0:
        raise ConfigError(f"{name} must be finite positive seconds")
    return value


def _provider(env: Mapping[str, str]) -> ModelProvider | None:
    present = [name for name in _PROVIDER_VARS if env.get(name, "").strip()]
    if not present:
        return None
    missing = [name for name in _PROVIDER_VARS if name not in present]
    if missing:
        raise ConfigError(
            "the model provider is half configured; set " + ", ".join(missing)
        )
    endpoint = env["RESEARCH_AGENT_MODEL_ENDPOINT"].strip()
    if not endpoint.startswith("https://"):
        raise ConfigError("RESEARCH_AGENT_MODEL_ENDPOINT must be an https URL")
    return ModelProvider(
        name=env.get("RESEARCH_AGENT_MODEL_PROVIDER", "").strip() or "provider",
        endpoint=endpoint,
        api_key=env["RESEARCH_AGENT_MODEL_API_KEY"].strip(),
        model=env["RESEARCH_AGENT_MODEL_ID"].strip(),
        input_usd_per_mtok=_price(env, "RESEARCH_AGENT_MODEL_INPUT_USD_PER_MTOK"),
        output_usd_per_mtok=_price(env, "RESEARCH_AGENT_MODEL_OUTPUT_USD_PER_MTOK"),
        send_max_tokens=_flag(env, "RESEARCH_AGENT_MODEL_SEND_MAX_TOKENS", True),
        timeout_seconds=_provider_timeout(env),
    )


def _passwords(raw: str) -> dict[str, str]:
    passwords: dict[str, str] = {}
    for item in raw.split(","):
        if not item.strip():
            continue
        island, _, password = item.partition(":")
        island, password = island.strip(), password.strip()
        if not island or not password:
            raise ConfigError(
                "RESEARCH_AGENT_ISLAND_PASSWORDS entries are island:password"
            )
        passwords[island] = password
    # Login takes the credential alone, so a credential must name one island.
    if len(set(passwords.values())) != len(passwords):
        raise ConfigError("each island needs its own password")
    return passwords


def load_config(env: Mapping[str, str] | None = None) -> BetaConfig:
    source = os.environ if env is None else env
    passwords = _passwords(source.get("RESEARCH_AGENT_ISLAND_PASSWORDS", ""))
    operator = source.get("RESEARCH_AGENT_OPERATOR_TOKEN", "").strip() or None
    if operator is not None and operator in passwords.values():
        raise ConfigError("the operator token must differ from every island password")
    origins = tuple(
        origin.strip().rstrip("/")
        for origin in source.get("RESEARCH_AGENT_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    )
    if "*" in origins:
        raise ConfigError("list each browser origin; credentials forbid a wildcard")
    return BetaConfig(
        database=Path(source.get("RESEARCH_AGENT_BETA_DB", "./swarm-beta.sqlite3")),
        # Without a stated secret every restart signs sessions with a new one.
        session_secret=source.get("RESEARCH_AGENT_SESSION_SECRET", "").strip()
        or secrets.token_hex(32),
        island_passwords=passwords,
        operator_token=operator,
        allowed_origins=origins,
        allowed_origin_regex=source.get(
            "RESEARCH_AGENT_ALLOWED_ORIGIN_REGEX", ""
        ).strip()
        or None,
        provider=_provider(source),
        # Unset, the process paces itself: a tick a minute, a paper every ten.
        tick_seconds=_seconds(source, "RESEARCH_AGENT_TICK_SECONDS", 60),
        ingest_seconds=_seconds(source, "RESEARCH_AGENT_INGEST_SECONDS", 600),
    )
