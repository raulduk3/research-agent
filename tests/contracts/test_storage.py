import pytest

from research_agent.contracts import ContractValidationError, canonical_json
from research_agent.contracts.storage import ArtifactPublicationReceipt


def test_receipt_requires_exact_committed_publication_fields() -> None:
    fields = {
        "schema_version": 1,
        "artifact_id": "a" * 64,
        "committed_ledger_sequence": 42,
        "published_at": "2026-09-21T00:00:00.000000Z",
    }
    receipt = ArtifactPublicationReceipt.from_json(canonical_json(fields))
    assert receipt.to_canonical_json() == canonical_json(fields)
    for changed in (
        {**fields, "committed_ledger_sequence": 0},
        {**fields, "committed_ledger_sequence": True},
        {**fields, "schema_version": 2},
        {**fields, "available_at": fields["published_at"]},
        {key: value for key, value in fields.items() if key != "published_at"},
    ):
        with pytest.raises(ContractValidationError):
            ArtifactPublicationReceipt.from_json(canonical_json(changed))
