"""The fixed, ordered automatic-citations-v1 target registry."""

from __future__ import annotations

from research_agent.contracts.learning import (
    TargetDefinition,
    TargetRegistry,
    TargetWindow,
)
from research_agent.contracts.primitives import ContractValidationError, RecordMeta

TARGET_ORDER = (
    "citation_reach_365d",
    "late_citation_activity_365d",
    "cross_subfield_reach_365d",
)


def definitions(meta: RecordMeta) -> tuple[TargetDefinition, ...]:
    """Construct the admitted definitions without caller-adjustable thresholds."""
    rows = (
        (
            "Will at least five indexed works cite this paper in its first year?",
            "distinct_family_threshold",
            ((0, 31536000),),
            5,
        ),
        (
            "Will indexed citations continue in both final parts of the first year?",
            "both_window_activity",
            ((15552000, 23328000), (23328000, 31536000)),
            1,
        ),
        (
            "Will it receive indexed citations from at least two other research subfields in its first year?",
            "distinct_other_subfield_threshold",
            ((0, 31536000),),
            2,
        ),
    )
    return tuple(
        TargetDefinition(
            schema_version=meta.schema_version,
            input_hashes=meta.input_hashes,
            producer_version=meta.producer_version,
            config_hash=meta.config_hash,
            created_at=meta.created_at,
            target_id=target_id,
            protocol="automatic-citations-v1",
            question=question,
            predicate=predicate,
            windows=tuple(
                TargetWindow(start, end, False, True) for start, end in windows
            ),
            threshold=threshold,
            indexing_allowance_seconds=7776000,
            prospective_capture_allowance_seconds=86400,
            source="openalex",
            self_author_citations="included",
            self_family_links="excluded",
            taxonomy_policy="captured_primary_subfield",
            family_policy="exact_identifiers_explicit_versions_v1",
        )
        for target_id, (question, predicate, windows, threshold) in zip(
            TARGET_ORDER, rows, strict=True
        )
    )


def registry(meta: RecordMeta) -> TargetRegistry:
    return TargetRegistry(
        schema_version=meta.schema_version,
        input_hashes=meta.input_hashes,
        producer_version=meta.producer_version,
        config_hash=meta.config_hash,
        created_at=meta.created_at,
        protocol="automatic-citations-v1",
        definitions=definitions(meta),
        calibrated_domains=("cs.AI", "cs.LG"),
    )


def validate_extension(
    current: TargetRegistry,
    *,
    previous_order: tuple[str, ...],
    requested_target_id: str,
    qualification_manifest_hash: str | None,
) -> None:
    """Gate a target-registry extension request without ever widening the launch set (FT-20).

    The launch registry admits exactly the three ``automatic-citations-v1``
    rows and no code path constructs a fourth: raise unless
    ``requested_target_id`` already names one of ``current``'s own admitted
    definitions and carries an accepted qualification manifest hash. An old
    snapshot's ``previous_order`` must remain the frozen prefix it always
    was; a genuinely unknown target id is always rejected, and a rejected
    request never touches ``current`` or its callers' existing outputs.
    """
    if previous_order != TARGET_ORDER[: len(previous_order)]:
        raise ContractValidationError(
            "a prior snapshot's target order no longer prefixes the current registry"
        )
    ids = {item.target_id for item in current.definitions}
    if requested_target_id not in ids:
        raise ContractValidationError(
            "target extension does not name an accepted definition"
        )
    if qualification_manifest_hash is None:
        raise ContractValidationError(
            "target extension requires an accepted qualification manifest"
        )
