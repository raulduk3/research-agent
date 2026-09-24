"""bin/serve-public refuses to open the tunnel unless decision 0030 holds (#336)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from research_agent.platform.ingress import (
    DEPLOY_DIR,
    INGRESS_PORT,
    IngressRefused,
    IngressRoute,
    TunnelPlan,
    TunnelRefused,
    plan_tunnel,
    render_caddyfile,
    start_tunnel,
    stop_tunnel,
)

DOMAIN = "owner.example.org"
TOKEN = "token-value-not-a-real-credential"
ENVIRON = {"NGROK_AUTHTOKEN": TOKEN, "NGROK_DOMAIN": DOMAIN}
CADDYFILE = (DEPLOY_DIR / "ingress" / "Caddyfile").read_text()


def _plan(
    environ: dict[str, str],
    *,
    public_hostname: str = DOMAIN,
    caddyfile: str = CADDYFILE,
) -> TunnelPlan:
    return plan_tunnel(
        "ngrok", environ, public_hostname=public_hostname, caddyfile=caddyfile
    )


def test_the_plan_forwards_the_public_domain_to_the_ingress() -> None:
    plan = _plan(ENVIRON)
    assert plan.public_url == f"https://{DOMAIN}"
    assert plan.argv[:2] == ("ngrok", "http")
    assert f"--url=https://{DOMAIN}" in plan.argv
    assert plan.argv[-1] == f"http://127.0.0.1:{INGRESS_PORT}"


def test_the_token_never_reaches_the_command_line() -> None:
    assert not any(TOKEN in part for part in _plan(ENVIRON).argv)


@pytest.mark.parametrize(
    "environ",
    [
        {"NGROK_DOMAIN": DOMAIN},
        {"NGROK_AUTHTOKEN": "  ", "NGROK_DOMAIN": DOMAIN},
        {"NGROK_AUTHTOKEN": TOKEN},
        {"NGROK_AUTHTOKEN": TOKEN, "NGROK_DOMAIN": "other.example.org"},
    ],
)
def test_the_tunnel_refuses_without_its_token_or_the_profile_domain(
    environ: dict[str, str],
) -> None:
    with pytest.raises(TunnelRefused):
        _plan(environ)


def test_the_tunnel_refuses_a_profile_without_a_public_hostname() -> None:
    with pytest.raises(TunnelRefused):
        _plan(ENVIRON, public_hostname="")


def test_the_tunnel_refuses_a_route_without_session_authentication() -> None:
    rating = render_caddyfile(
        (
            IngressRoute(path="/rate/*", service="app", port=8443),
            IngressRoute(path="/*", service="owner", port=8443),
        )
    )
    with pytest.raises(IngressRefused):
        _plan(ENVIRON, caddyfile=rating)


def test_the_tunnel_refuses_an_ingress_that_terminates_tls() -> None:
    with pytest.raises(IngressRefused):
        _plan(ENVIRON, caddyfile=CADDYFILE.replace("\tauto_https off\n", ""))


def test_the_tunnel_refuses_an_unknown_provider() -> None:
    with pytest.raises(TunnelRefused):
        plan_tunnel("elsewhere", ENVIRON, public_hostname=DOMAIN, caddyfile=CADDYFILE)


def test_one_client_runs_at_a_time_and_stop_ends_it(tmp_path: Path) -> None:
    pid_file = tmp_path / "serve-public.pid"
    log_file = tmp_path / "serve-public.log"
    plan = TunnelPlan(
        argv=(sys.executable, "-c", "import time; time.sleep(60)"),
        public_url=f"https://{DOMAIN}",
    )
    pid = start_tunnel(plan, pid_file=pid_file, log_file=log_file)
    assert pid_file.read_text() == f"{pid}\n"
    with pytest.raises(TunnelRefused):
        start_tunnel(plan, pid_file=pid_file, log_file=log_file)
    assert stop_tunnel(pid_file=pid_file) is True
    assert not pid_file.exists()
    assert stop_tunnel(pid_file=pid_file) is False
