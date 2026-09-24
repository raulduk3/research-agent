"""The one ingress and what it may publish (decision 0030, #336).

The ingress is a reverse proxy on the guest's loopback that the tunnel
client forwards the public hostname to. It publishes owner surfaces only:
every route it proxies must reach a Compose service whose role requires an
owner session on every route (`PUBLISHABLE_ROLES`). The owner app serves the
owner actions pages, the inspector pages and their ``/api/v1`` twins, so it
is the one upstream. The rating app, storage, models, tools and every other
internal service are never published.

`render_caddyfile` is the committed ``deploy/ingress/Caddyfile``;
`published_upstreams` reads the upstreams back out of a Caddyfile's
``reverse_proxy`` lines and `verify_published` refuses a Caddyfile that would
publish any role outside `PUBLISHABLE_ROLES`, so an edit to the file cannot
publish an internal service without the check that starts the tunnel
refusing it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from research_agent.contracts.primitives import ContractValidationError
from research_agent.platform.compose import inventory_from_definition

#: The roles whose every route answers an unauthenticated request with the
#: login page or 401 and never with data. Only these may be published.
PUBLISHABLE_ROLES: frozenset[str] = frozenset({"owner"})

#: The port the ingress listens on, published to the guest's loopback and
#: forwarded from there to the host's loopback for the tunnel client.
INGRESS_PORT: int = 8480

#: The path the ingress answers its own health check on, on any host.
HEALTH_PATH: str = "/ingress/health"

#: The environment variable the ingress reads the public hostname from; the
#: operator sets it from the profile's ``host.public_hostname``.
PUBLIC_HOSTNAME_VARIABLE: str = "RESEARCH_AGENT_PUBLIC_HOSTNAME"


class IngressRefused(ContractValidationError):
    """The ingress would publish a route that is not owner-authenticated."""


@dataclass(frozen=True, slots=True)
class IngressRoute:
    """One path prefix the public hostname proxies to one Compose service."""

    path: str
    service: str
    port: int


#: Every published route, in the order the Caddyfile matches them.
ROUTES: tuple[IngressRoute, ...] = (
    IngressRoute(path="/api/v1/*", service="owner", port=8443),
    IngressRoute(path="/*", service="owner", port=8443),
)

_SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    ("Strict-Transport-Security", "max-age=31536000"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Content-Security-Policy", "frame-ancestors 'none'"),
)

_UPSTREAM = re.compile(r"^\s*reverse_proxy\s+(?:\S+\s+)?https?://([a-z0-9-]+):(\d+)")


def render_caddyfile(routes: tuple[IngressRoute, ...] = ROUTES) -> str:
    """The ingress configuration for *routes*, byte for byte.

    TLS is the tunnel's: the ingress listens on plain HTTP and never asks
    for a certificate. It proxies each upstream over HTTPS, trusting only the
    platform's certificate authority. Any host but the public one gets the
    health route and otherwise 404.
    """

    lines = [
        "# Rendered by platform/ingress.py#render_caddyfile; tests compare it.",
        "{",
        "\tauto_https off",
        "\tadmin off",
        "\tpersist_config off",
        "}",
        "",
        f"http://{{${PUBLIC_HOSTNAME_VARIABLE}}}:{INGRESS_PORT} {{",
        "\tlog {",
        "\t\toutput stdout",
        "\t\tformat json",
        "\t}",
        "\theader {",
        *(f'\t\t{name} "{value}"' for name, value in _SECURITY_HEADERS),
        "\t\t-Server",
        "\t}",
        f"\thandle {HEALTH_PATH} {{",
        "\t\trespond 200",
        "\t}",
    ]
    for route in routes:
        lines += [
            f"\thandle {route.path} {{",
            f"\t\treverse_proxy https://{route.service}:{route.port} {{",
            "\t\t\ttransport http {",
            "\t\t\t\ttls_trust_pool file /run/secrets/ingress_ca",
            f"\t\t\t\ttls_server_name {route.service}",
            "\t\t\t}",
            "\t\t}",
            "\t}",
        ]
    lines += [
        "}",
        "",
        f"http://:{INGRESS_PORT} {{",
        f"\thandle {HEALTH_PATH} {{",
        "\t\trespond 200",
        "\t}",
        "\thandle {",
        "\t\trespond 404",
        "\t}",
        "}",
    ]
    return "\n".join(lines) + "\n"


def published_upstreams(caddyfile: str) -> frozenset[str]:
    """The Compose service names a Caddyfile's ``reverse_proxy`` lines name."""

    services: set[str] = set()
    for line in caddyfile.splitlines():
        if line.strip().startswith("reverse_proxy"):
            match = _UPSTREAM.match(line)
            if match is None:
                raise IngressRefused(f"unreadable upstream: {line.strip()!r}")
            services.add(match.group(1))
    return frozenset(services)


def verify_published(
    caddyfile: str, compose_services: Mapping[str, Mapping[str, Any]]
) -> frozenset[str]:
    """Refuse unless every upstream is a declared, owner-authenticated service.

    Returns the published roles.
    """

    upstreams = published_upstreams(caddyfile)
    if not upstreams:
        raise IngressRefused("the ingress publishes no route")
    inventory = inventory_from_definition(compose_services)
    roles: set[str] = set()
    for name in sorted(upstreams):
        service = inventory.services.get(name)
        if service is None:
            raise IngressRefused(f"upstream {name!r} is not a declared service")
        if service.role not in PUBLISHABLE_ROLES:
            raise IngressRefused(
                f"upstream {name!r} has role {service.role!r}, which is not "
                "owner-authenticated and is never published"
            )
        roles.add(service.role)
    return frozenset(roles)
