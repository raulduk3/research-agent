from research_agent.platform.network import (
    EgressEndpoint,
    EgressManifest,
    compile_reachability,
)


def _endpoint(hostname: str) -> EgressEndpoint:
    return EgressEndpoint(
        scheme="https",
        hostname=hostname,
        port=443,
        resolved_addresses=("93.184.216.34",),
        tls_identity="a" * 64,
    )


def test_reachability_policy_denies_by_default() -> None:
    policy = compile_reachability((), EgressManifest({}))
    assert not policy.allows("worker", "postgres:5432")


def test_reachability_policy_allows_a_declared_service_edge() -> None:
    policy = compile_reachability((("worker", "tools:8443"),), EgressManifest({}))
    assert policy.allows("worker", "tools:8443")
    assert not policy.allows("worker", "postgres:5432")


def test_reachability_policy_allows_a_manifest_bound_egress_endpoint() -> None:
    manifest = EgressManifest({"ingest": (_endpoint("export.arxiv.org"),)})
    policy = compile_reachability((), manifest)
    assert policy.allows("ingest", "export.arxiv.org:443")
    assert not policy.allows("worker", "export.arxiv.org:443")


def test_reachability_policy_same_network_membership_is_not_authorization() -> None:
    # Two roles could share a Compose network without either edge being
    # declared; only a compiled edge grants reach, never network membership.
    policy = compile_reachability((("storage", "postgres:5432"),), EgressManifest({}))
    assert not policy.allows("worker", "postgres:5432")


def test_destinations_for_lists_only_that_roles_allowed_edges() -> None:
    policy = compile_reachability(
        (("worker", "tools:8443"), ("storage", "postgres:5432")), EgressManifest({})
    )
    assert policy.destinations_for("worker") == frozenset({"tools:8443"})
