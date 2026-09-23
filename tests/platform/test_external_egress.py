import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.platform.network import EgressEndpoint, EgressManifest


def _endpoint(**overrides: object) -> EgressEndpoint:
    values: dict[str, object] = {
        "scheme": "https",
        "hostname": "api.z.ai",
        "port": 443,
        "resolved_addresses": ("93.184.216.34",),
        "tls_identity": "a" * 64,
    }
    values.update(overrides)
    return EgressEndpoint(**values)  # type: ignore[arg-type]


def test_egress_endpoint_rejects_a_non_https_scheme() -> None:
    with pytest.raises(ContractValidationError):
        _endpoint(scheme="http")


def test_egress_endpoint_rejects_dns_rebinding_to_a_private_address() -> None:
    with pytest.raises(ContractValidationError):
        _endpoint(resolved_addresses=("10.0.0.5",))


def test_egress_endpoint_permits_a_private_address_only_when_explicitly_bound() -> None:
    endpoint = _endpoint(resolved_addresses=("10.0.0.5",), permits_private_address=True)
    assert endpoint.resolved_addresses == ("10.0.0.5",)


def test_egress_endpoint_rejects_a_metadata_style_link_local_address() -> None:
    with pytest.raises(ContractValidationError):
        _endpoint(resolved_addresses=("169.254.169.254",))


def test_egress_manifest_permits_only_its_declared_role_and_endpoint() -> None:
    manifest = EgressManifest({"ingest": (_endpoint(hostname="export.arxiv.org"),)})
    assert manifest.permits("ingest", "export.arxiv.org", 443)
    assert not manifest.permits("worker", "export.arxiv.org", 443)
    assert not manifest.permits("ingest", "unlisted.example", 443)
