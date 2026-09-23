"""Explicit external egress roles and the host-enforced reach graph.

`EgressManifest` (SDD-SR-13) represents every deployment-bound external
endpoint as scheme, hostname, port, resolved addresses and TLS identity, so
a worker never resolves a hostname itself; a trusted component resolves it
once and the immutable manifest is what the platform actually allows.
`ReachabilityPolicy` (SDD-PL-19) compiles that manifest together with the
declared inter-service edges into one default-deny matrix: two containers on
the same Compose network are not thereby authorized to reach each other,
only an edge named here is.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_positive_int,
)


def _is_private_or_reserved(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as error:
        raise ContractValidationError("resolved address must be a valid IP") from error
    return (
        parsed.is_private
        or parsed.is_link_local
        or parsed.is_loopback
        or parsed.is_reserved
        or parsed.is_multicast
    )


@dataclass(frozen=True, slots=True)
class EgressEndpoint:
    """One deployment-bound external destination, resolved outside the worker."""

    scheme: str
    hostname: str
    port: int
    resolved_addresses: tuple[str, ...]
    tls_identity: str
    permits_private_address: bool = False

    def __post_init__(self) -> None:
        if self.scheme != "https":
            raise ContractValidationError("egress endpoints must use https")
        validate_non_empty_string(self.hostname)
        validate_positive_int(self.port)
        if self.port > 65535:
            raise ContractValidationError("port must be at most 65535")
        if not self.resolved_addresses:
            raise ContractValidationError("resolved_addresses must be nonempty")
        for address in self.resolved_addresses:
            if _is_private_or_reserved(address) and not self.permits_private_address:
                raise ContractValidationError(
                    "resolved address is private or reserved and not an "
                    "explicitly bound private receiver route"
                )
        validate_non_empty_string(self.tls_identity)

    def label(self) -> str:
        return f"{self.hostname}:{self.port}"


@dataclass(frozen=True, slots=True)
class EgressManifest:
    """The immutable, role-scoped set of external endpoints a deployment binds."""

    by_role: Mapping[str, tuple[EgressEndpoint, ...]]

    def for_role(self, role: str) -> tuple[EgressEndpoint, ...]:
        return self.by_role.get(role, ())

    def permits(self, role: str, hostname: str, port: int) -> bool:
        return any(
            endpoint.hostname == hostname and endpoint.port == port
            for endpoint in self.for_role(role)
        )


@dataclass(frozen=True, slots=True)
class ReachEdge:
    """One allowed (source role, destination label) pair in the reach graph."""

    source_role: str
    destination: str


@dataclass(frozen=True, slots=True)
class ReachabilityPolicy:
    """A compiled, default-deny matrix of every container-to-container edge.

    Membership on the same Compose network is never itself authorization;
    only a compiled edge is. `allows` is what both the platform's installed
    firewall rules and the acceptance matrix test are checked against.
    """

    edges: frozenset[ReachEdge]

    def allows(self, source_role: str, destination: str) -> bool:
        return ReachEdge(source_role, destination) in self.edges

    def destinations_for(self, source_role: str) -> frozenset[str]:
        return frozenset(
            edge.destination for edge in self.edges if edge.source_role == source_role
        )


def compile_reachability(
    service_edges: Iterable[tuple[str, str]], egress: EgressManifest
) -> ReachabilityPolicy:
    """Compile declared inter-service edges and the egress manifest into one policy."""

    edges = {ReachEdge(source, destination) for source, destination in service_edges}
    for role, endpoints in egress.by_role.items():
        for endpoint in endpoints:
            edges.add(ReachEdge(role, endpoint.label()))
    return ReachabilityPolicy(frozenset(edges))
