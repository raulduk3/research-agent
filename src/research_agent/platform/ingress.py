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

import argparse
import os
import re
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from research_agent.contracts.primitives import ContractValidationError
from research_agent.platform.compose import STATIC_ROLE_IDS
from research_agent.platform.profile import LaunchProfile

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

#: The deployable definition the tunnel command reads its Caddyfile from.
DEPLOY_DIR: Path = Path(__file__).resolve().parents[3] / "deploy"

#: Each static Compose service's role: every service is named for its role,
#: which tests hold the committed ``deploy/compose.yaml`` labels to.
SERVICE_ROLES: Mapping[str, str] = {role: role for role in STATIC_ROLE_IDS}

#: Where the tunnel client's process id and log live on the host.
DEFAULT_STATE_DIR: Path = Path.home() / ".local" / "state" / "research-agent"


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
    caddyfile: str, service_roles: Mapping[str, str] = SERVICE_ROLES
) -> frozenset[str]:
    """Refuse unless every upstream is a declared, owner-authenticated service.

    Returns the published roles.
    """

    upstreams = published_upstreams(caddyfile)
    if not upstreams:
        raise IngressRefused("the ingress publishes no route")
    roles: set[str] = set()
    for name in sorted(upstreams):
        role = service_roles.get(name)
        if role is None:
            raise IngressRefused(f"upstream {name!r} is not a declared service")
        if role not in PUBLISHABLE_ROLES:
            raise IngressRefused(
                f"upstream {name!r} has role {role!r}, which is not "
                "owner-authenticated and is never published"
            )
        roles.add(role)
    return frozenset(roles)


def verify_tunnel_terminates_tls(caddyfile: str) -> None:
    """Refuse a Caddyfile that would serve or ask for a certificate itself.

    The tunnel terminates TLS at the public hostname; the ingress behind it
    listens on plain HTTP with automatic HTTPS off, so it never holds a
    public certificate or answers on port 443.
    """

    if "\tauto_https off\n" not in caddyfile:
        raise IngressRefused("the ingress must leave TLS to the tunnel")
    for line in caddyfile.splitlines():
        if line and not line[0].isspace() and line.endswith("{") and line != "{":
            if not line.startswith("http://"):
                raise IngressRefused(f"site {line[:-1].strip()!r} is not plain HTTP")
        if line.strip().startswith("tls "):
            raise IngressRefused("the ingress must not hold a certificate")


class TunnelRefused(IngressRefused):
    """The tunnel is not started: a precondition of decision 0030 is unmet."""


@dataclass(frozen=True, slots=True)
class TunnelPlan:
    """The tunnel client's command line and the public URL it serves."""

    argv: tuple[str, ...]
    public_url: str


def plan_tunnel(
    provider: str,
    environ: Mapping[str, str],
    *,
    public_hostname: str,
    caddyfile: str,
    service_roles: Mapping[str, str] = SERVICE_ROLES,
) -> TunnelPlan:
    """The ngrok command that publishes the ingress, or a refusal.

    Refuses without ``NGROK_AUTHTOKEN`` or ``NGROK_DOMAIN`` in *environ*,
    with a domain that is not the profile's *public_hostname*, and with an
    ingress configuration that publishes a route without owner sessions or
    terminates TLS itself. The token stays in the environment the client
    inherits; it is never on the command line.
    """

    if provider != "ngrok":
        raise TunnelRefused(f"unknown tunnel provider {provider!r}")
    if not environ.get("NGROK_AUTHTOKEN", "").strip():
        raise TunnelRefused("NGROK_AUTHTOKEN is not set in the environment")
    domain = environ.get("NGROK_DOMAIN", "").strip()
    if not domain:
        raise TunnelRefused("NGROK_DOMAIN is not set in the environment")
    if not public_hostname:
        raise TunnelRefused("the launch profile records no host.public_hostname")
    if domain != public_hostname:
        raise TunnelRefused("NGROK_DOMAIN is not the profile's host.public_hostname")
    verify_published(caddyfile, service_roles)
    verify_tunnel_terminates_tls(caddyfile)
    public_url = f"https://{domain}"
    return TunnelPlan(
        argv=(
            "ngrok",
            "http",
            f"--url={public_url}",
            "--log=stdout",
            "--log-format=json",
            f"http://127.0.0.1:{INGRESS_PORT}",
        ),
        public_url=public_url,
    )


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def start_tunnel(plan: TunnelPlan, *, pid_file: Path, log_file: Path) -> int:
    """Start the tunnel client detached, recording its process id.

    Refuses while a recorded client is still running, so one tunnel serves
    the ingress at a time; ``stop_tunnel`` then ``start_tunnel`` restarts it.
    """

    if pid_file.exists():
        recorded = int(pid_file.read_text().strip() or 0)
        if recorded and _pid_running(recorded):
            raise TunnelRefused(f"a tunnel is already running as process {recorded}")
        pid_file.unlink()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("ab") as log:
        process = subprocess.Popen(  # noqa: S603 - fixed argv from plan_tunnel
            plan.argv,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    pid_file.write_text(f"{process.pid}\n")
    return process.pid


def stop_tunnel(*, pid_file: Path) -> bool:
    """Stop the recorded tunnel client; ``False`` when none was running."""

    if not pid_file.exists():
        return False
    recorded = int(pid_file.read_text().strip() or 0)
    pid_file.unlink()
    if not recorded or not _pid_running(recorded):
        return False
    os.kill(recorded, signal.SIGTERM)
    return True


def main(argv: Sequence[str] | None = None) -> int:
    """``bin/serve-public``: publish the owner surfaces through the tunnel."""

    parser = argparse.ArgumentParser(prog="serve-public")
    parser.add_argument("--provider", choices=["ngrok"], default="ngrok")
    parser.add_argument("--profile", type=Path, help="the launch profile")
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args(argv)
    pid_file = args.state_dir / "serve-public.pid"
    if args.stop:
        stopped = stop_tunnel(pid_file=pid_file)
        print("Tunnel stopped." if stopped else "No tunnel was running.")
        return 0
    if args.profile is None:
        parser.error("--profile is required")
    try:
        profile = LaunchProfile.from_json(args.profile.read_bytes())
        plan = plan_tunnel(
            args.provider,
            os.environ,
            public_hostname=profile.host.public_hostname,
            caddyfile=(DEPLOY_DIR / "ingress" / "Caddyfile").read_text(),
        )
        pid = start_tunnel(
            plan, pid_file=pid_file, log_file=args.state_dir / "serve-public.log"
        )
    except (OSError, ValueError) as error:
        print(f"Tunnel refused: {error}", file=sys.stderr)
        return 1
    print(f"{plan.public_url} (process {pid})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
