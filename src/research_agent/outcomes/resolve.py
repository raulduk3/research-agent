"""Resolve fixed citation targets using only retained immutable evidence."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from research_agent.contracts import sha256_hex
from research_agent.contracts.learning import (
    AutomaticLabel,
    CitationFamilyRecord,
    CitationObservation,
    CountBounds,
    LabelCounts,
    TargetDefinition,
    TargetRegistry,
)
from research_agent.contracts.papers import PaperVersionRecord
from research_agent.contracts.primitives import RecordMeta
from research_agent.outcomes.bounds import BoundEvidence, citation_bounds
from research_agent.outcomes.windows import (
    OutcomeWindow,
    capture_timing_failure,
    instant,
)
from research_agent.storage.errors import IntegrityFailure


class Resolver:
    """Bind the immutable reader and producer identity once, outside caller payloads."""

    def __init__(
        self,
        read_family: Callable[[str], CitationFamilyRecord],
        meta: RecordMeta,
        *,
        registry: TargetRegistry,
    ) -> None:
        self._read_family = read_family
        self._meta = meta
        self._registry_hash = sha256_hex(registry.to_canonical_json())
        self._registry_created_at = registry.created_at
        self._definitions = {
            item.target_id: sha256_hex(item.to_canonical_json())
            for item in registry.definitions
        }

    def resolve_target(
        self,
        target: TargetDefinition,
        paper: PaperVersionRecord,
        observation: CitationObservation,
        as_of: str,
    ) -> AutomaticLabel:
        instant(as_of)
        target_hash = sha256_hex(target.to_canonical_json())
        if self._definitions.get(target.target_id) != target_hash:
            raise IntegrityFailure("target definition is not in the bound registry")
        observation_hash = sha256_hex(observation.to_canonical_json())
        empty = CountBounds(0, None)
        evidence = BoundEvidence(
            LabelCounts(empty, empty, empty, empty), (), (), (), ()
        )
        reason = self._failure(paper, observation, as_of)
        if reason is None and (
            instant(target.created_at) > instant(as_of)
            or instant(self._registry_created_at) > instant(as_of)
        ):
            reason = "invalid_source"
        state = "unknown"
        families: tuple[CitationFamilyRecord, ...] = ()
        if reason is None:
            loaded = []
            for artifact_hash in observation.citation_family_hashes:
                record = self._read_family(artifact_hash)
                if sha256_hex(record.to_canonical_json()) != artifact_hash or instant(
                    record.created_at
                ) > instant(observation.created_at):
                    raise IntegrityFailure(
                        "citation family bytes do not match identity"
                    )
                if not set(record.target_link_work_ids).intersection(
                    observation.target_provider_ids
                ):
                    raise IntegrityFailure("citation family has no matched target link")
                loaded.append(record)
            families = tuple(loaded)
            assert paper.first_public_at is not None
            evidence = citation_bounds(
                families,
                t0=paper.first_public_at,
                target_subfield=(
                    observation.target_subfield_id
                    if observation.target_subfield_state == "known"
                    else None
                ),
                complete=observation.pagination_complete,
            )
            state, reason = self._predicate(target, observation, evidence, families)
        family_witnesses: tuple[str, ...] = ()
        field_witnesses: tuple[str, ...] = ()
        if state == "true":
            if target.target_id == "citation_reach_365d":
                family_witnesses = evidence.year_witnesses[:5]
            elif target.target_id == "late_citation_activity_365d":
                family_witnesses = tuple(
                    sorted(
                        {
                            evidence.first_late_witnesses[0],
                            evidence.second_late_witnesses[0],
                        }
                    )
                )
            else:
                selected = sorted(
                    evidence.subfield_witnesses, key=lambda pair: (pair[1], pair[0])
                )[:2]
                field_witnesses = tuple(sorted(field for field, _ in selected))
                family_witnesses = tuple(sorted(family for _, family in selected))
        meta = replace(
            self._meta,
            input_hashes=(
                target_hash,
                sha256_hex(paper.to_canonical_json()),
                observation_hash,
            ),
            created_at=as_of,
        )
        return AutomaticLabel(
            schema_version=meta.schema_version,
            input_hashes=meta.input_hashes,
            producer_version=meta.producer_version,
            config_hash=meta.config_hash,
            created_at=meta.created_at,
            paper_family_id=paper.family_id,
            target_id=target.target_id,
            target_definition_hash=target_hash,
            state=state,
            reason=reason,
            observation_hash=observation_hash,
            counts=evidence.counts,
            witness_family_ids=family_witnesses,
            witness_subfield_ids=field_witnesses,
            completion_page_hashes=tuple(
                page.response_hash
                for page in observation.pages
                if page.status == "completed" and page.response_hash is not None
            ),
            maturity_at=observation.maturity_at,
            resolved_at=as_of,
            supersedes_label_hash=None,
            correction_hash=None,
        )

    def _failure(
        self, paper: PaperVersionRecord, observation: CitationObservation, as_of: str
    ) -> str | None:
        if paper.first_public_at is None:
            return "unknown_t0"
        if (
            not paper.is_first_public_version
            or paper.family_id != observation.paper_family_id
            or paper.version_id != observation.original_version_id
            or paper.first_public_at != observation.t0
            or observation.target_registry_hash != self._registry_hash
        ):
            return "invalid_source"
        timing = capture_timing_failure(
            t0=paper.first_public_at,
            kind=observation.kind,
            started_at=observation.capture_started_at,
            completed_at=observation.capture_completed_at,
            as_of=as_of,
        )
        if timing is not None:
            return timing
        if instant(paper.created_at) > instant(as_of) or instant(
            observation.created_at
        ) > instant(as_of):
            return "invalid_source"
        if observation.failure is not None:
            return observation.failure
        if observation.target_match_state != "matched":
            return (
                "ambiguous_target"
                if observation.target_match_state == "ambiguous"
                else "unmatched_target"
            )
        if not observation.pages or observation.pages[0].status != "completed":
            return "initial_request_failed"
        return None

    @staticmethod
    def _predicate(
        target: TargetDefinition,
        observation: CitationObservation,
        evidence: BoundEvidence,
        records: tuple[CitationFamilyRecord, ...],
    ) -> tuple[str, str]:
        counts = evidence.counts
        if (
            target.target_id == "cross_subfield_reach_365d"
            and observation.target_subfield_state != "known"
        ):
            return "unknown", "missing_target_subfield"
        if target.target_id == "citation_reach_365d":
            positive = counts.year_families.lower >= 5
            negative = (
                counts.year_families.upper is not None
                and counts.year_families.upper < 5
            )
        elif target.target_id == "late_citation_activity_365d":
            positive = (
                counts.late_180_270_families.lower >= 1
                and counts.late_270_365_families.lower >= 1
            )
            negative = (
                counts.late_180_270_families.upper == 0
                or counts.late_270_365_families.upper == 0
            )
        else:
            positive = counts.other_primary_subfields.lower >= 2
            negative = (
                counts.other_primary_subfields.upper is not None
                and counts.other_primary_subfields.upper <= 1
            )
        if positive:
            return "true", "sufficient_positive_witnesses"
        if observation.pagination_complete and negative:
            return "false", "complete_negative_evidence"
        if not observation.pagination_complete:
            return "unknown", "incomplete_capture"
        if any(record.identity_state == "ambiguous" for record in records):
            return "unknown", "uncertain_identity"
        if any(
            record.date_state != "known"
            or any(
                OutcomeWindow(
                    window.start_offset_seconds, window.end_offset_seconds
                ).classify(observation.t0, record.publication_interval)
                == "possible"
                for window in target.windows
            )
            for record in records
        ):
            return "unknown", "uncertain_dates"
        return "unknown", "uncertain_subfields"
