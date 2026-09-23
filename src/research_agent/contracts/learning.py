"""Closed automatic-citation observation and label contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar, cast

from .canonical import canonical_json, canonical_loads
from .papers import ExternalIdentifier, SourceInterval
from .primitives import (
    ContractValidationError,
    validate_finite,
    validate_non_empty_string,
    validate_non_negative_int,
    validate_positive_int,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
    RecordMeta,
    ProducerVersion,
)

# modernbert-embed-base vectors; head features concatenate overview and passages.
EMBEDDING_DIMENSION = 768
# The embedding-only block width: CombinedFeatureRecord.combined_vector stays this
# width and this width alone (unit-L2, overview_passage_sqrt2_v1); it is not the
# fitted head's input width (#149).
EMBEDDING_FEATURE_DIMENSION = 2 * EMBEDDING_DIMENSION
TARGET_IDS = (
    "citation_reach_365d",
    "late_citation_activity_365d",
    "cross_subfield_reach_365d",
)
# The closed primary-category registry (#149 Appendix B): reused for the
# metadata block's primary-category one-hot and for the corpus's admitted
# categories, so neither list drifts from the other.
PRIMARY_CATEGORY_IDS: tuple[str, ...] = ("cs.AI", "cs.LG", "quant-ph", "q-bio")
# The closed metadata block order (#149 Appendix B): author count (log1p),
# listed-category count, primary-category one-hot, abstract token count
# (log1p), title token count, first-availability weekday one-hot, a
# code-repository-link flag, and the version count at seal.
_METADATA_BLOCK_WIDTHS = (
    1,
    1,
    len(PRIMARY_CATEGORY_IDS),
    1,
    1,
    7,
    1,
    1,
)
METADATA_DIMENSION = sum(_METADATA_BLOCK_WIDTHS)
# The fitted head's actual input width: the embedding block followed by the
# declared metadata block (#149).
HEAD_INPUT_DIMENSION = EMBEDDING_FEATURE_DIMENSION + METADATA_DIMENSION
T = TypeVar("T")


class CanonicalRecord:
    def to_canonical_json(self) -> bytes:
        return canonical_json(asdict(cast(Any, self)))


def _closed(raw: bytes, fields: set[str], name: str) -> dict[str, Any]:
    value = canonical_loads(raw)
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} fields do not match schema")
    return cast(dict[str, Any], value)


def _meta(values: dict[str, Any]) -> None:
    producer = values.get("producer_version")
    inputs = values.get("input_hashes")
    if not isinstance(producer, dict) or not isinstance(inputs, list):
        raise ContractValidationError("RecordMeta fields are invalid")
    values["producer_version"] = ProducerVersion.from_json(canonical_json(producer))
    values["input_hashes"] = tuple(inputs)


def _fields(cls: Any, *, meta: bool = False) -> set[str]:
    fields = set(cls.__slots__)
    if meta:
        fields.update(RecordMeta.__slots__)
    return fields


def _construct(cls: type[T], values: dict[str, Any], name: str) -> T:
    try:
        return cls(**values)
    except ContractValidationError:
        raise
    except (AttributeError, KeyError, TypeError) as error:
        raise ContractValidationError(f"{name} field types are invalid") from error


@dataclass(frozen=True, slots=True)
class TargetWindow(CanonicalRecord):
    start_offset_seconds: int
    end_offset_seconds: int
    start_inclusive: bool = False
    end_inclusive: bool = True

    def __post_init__(self) -> None:
        validate_non_negative_int(self.start_offset_seconds)
        validate_positive_int(self.end_offset_seconds)
        if (
            self.end_offset_seconds <= self.start_offset_seconds
            or self.start_inclusive is not False
            or self.end_inclusive is not True
        ):
            raise ContractValidationError("target window is invalid")

    @classmethod
    def from_json(cls, raw: bytes) -> "TargetWindow":
        return _construct(
            cls, _closed(raw, _fields(cls), "TargetWindow"), "TargetWindow"
        )


@dataclass(frozen=True, slots=True)
class TargetDefinition(CanonicalRecord, RecordMeta):
    target_id: str
    protocol: str
    question: str
    predicate: str
    windows: tuple[TargetWindow, ...]
    threshold: int
    indexing_allowance_seconds: int
    prospective_capture_allowance_seconds: int
    source: str
    self_author_citations: str
    self_family_links: str
    taxonomy_policy: str
    family_policy: str

    def __post_init__(self) -> None:
        RecordMeta.__post_init__(self)
        exact = {
            TARGET_IDS[0]: ("distinct_family_threshold", ((0, 31536000),), 5),
            TARGET_IDS[1]: (
                "both_window_activity",
                ((15552000, 23328000), (23328000, 31536000)),
                1,
            ),
            TARGET_IDS[2]: ("distinct_other_subfield_threshold", ((0, 31536000),), 2),
        }
        validate_non_empty_string(self.question)
        row = exact.get(self.target_id)
        if (
            row is None
            or self.protocol != "automatic-citations-v1"
            or self.predicate != row[0]
            or tuple(
                (w.start_offset_seconds, w.end_offset_seconds) for w in self.windows
            )
            != row[1]
            or self.threshold != row[2]
        ):
            raise ContractValidationError(
                "target definition differs from fixed registry row"
            )
        if (
            self.indexing_allowance_seconds,
            self.prospective_capture_allowance_seconds,
            self.source,
            self.self_author_citations,
            self.self_family_links,
            self.taxonomy_policy,
            self.family_policy,
        ) != (
            7776000,
            86400,
            "openalex",
            "included",
            "excluded",
            "captured_primary_subfield",
            "exact_identifiers_explicit_versions_v1",
        ):
            raise ContractValidationError("target definition policy is invalid")

    @classmethod
    def from_json(cls, raw: bytes) -> "TargetDefinition":
        values = _closed(raw, _fields(cls, meta=True), "TargetDefinition")
        _meta(values)
        windows = values["windows"]
        if not isinstance(windows, list):
            raise ContractValidationError("windows must be an array")
        values["windows"] = tuple(
            TargetWindow.from_json(canonical_json(item)) for item in windows
        )
        return _construct(cls, values, "TargetDefinition")


@dataclass(frozen=True, slots=True)
class TargetRegistry(CanonicalRecord, RecordMeta):
    protocol: str
    definitions: tuple[TargetDefinition, ...]
    calibrated_domains: tuple[str, ...]

    def __post_init__(self) -> None:
        RecordMeta.__post_init__(self)
        if self.protocol != "automatic-citations-v1" or self.calibrated_domains != (
            "cs.AI",
            "cs.LG",
        ):
            raise ContractValidationError("target registry policy is invalid")
        if tuple(item.target_id for item in self.definitions) != TARGET_IDS:
            raise ContractValidationError(
                "target registry definitions are incomplete or unordered"
            )
        if len({item.to_canonical_json() for item in self.definitions}) != 3:
            raise ContractValidationError("target registry definitions are duplicated")

    @classmethod
    def from_json(cls, raw: bytes) -> "TargetRegistry":
        values = _closed(raw, _fields(cls, meta=True), "TargetRegistry")
        _meta(values)
        definitions = values["definitions"]
        domains = values["calibrated_domains"]
        if not isinstance(definitions, list) or not isinstance(domains, list):
            raise ContractValidationError("registry arrays are invalid")
        values["definitions"] = tuple(
            TargetDefinition.from_json(canonical_json(item)) for item in definitions
        )
        values["calibrated_domains"] = tuple(domains)
        return _construct(cls, values, "TargetRegistry")


@dataclass(frozen=True, slots=True)
class PaginationPage(CanonicalRecord):
    page_index: int
    request_hash: str
    response_hash: str | None
    cursor_in: str | None
    cursor_out: str | None
    returned_count: int
    capture_started_at: str
    capture_completed_at: str
    status: str
    failure: str | None

    def __post_init__(self) -> None:
        validate_non_negative_int(self.page_index)
        validate_sha256(self.request_hash)
        validate_non_negative_int(self.returned_count)
        if self.response_hash is not None:
            validate_sha256(self.response_hash)
        for cursor in (self.cursor_in, self.cursor_out):
            if cursor is not None:
                validate_non_empty_string(cursor)
        if validate_utc_instant(self.capture_completed_at) < validate_utc_instant(
            self.capture_started_at
        ):
            raise ContractValidationError("page clocks are reversed")
        if self.status == "failed":
            if (
                self.failure
                not in {"timeout", "rejected", "transport", "invalid_payload"}
                or self.returned_count
            ):
                raise ContractValidationError("failed page is invalid")
        elif (
            self.status != "completed"
            or self.failure is not None
            or self.response_hash is None
        ):
            raise ContractValidationError("completed page is invalid")

    @classmethod
    def from_json(cls, raw: bytes) -> "PaginationPage":
        return _construct(
            cls, _closed(raw, _fields(cls), "PaginationPage"), "PaginationPage"
        )


def _validate_page_chain(pages: tuple[PaginationPage, ...], complete: bool) -> None:
    if not pages:
        raise ContractValidationError("citation observation requires an initial page")
    expected: str | None = None
    seen: set[str] = set()
    for index, page in enumerate(pages):
        if page.page_index != index or page.cursor_in != expected:
            raise ContractValidationError("pagination cursor chain is invalid")
        if page.status == "failed":
            if index != len(pages) - 1 or complete:
                raise ContractValidationError(
                    "failed pagination page must be terminal and incomplete"
                )
            return
        if expected is None and index > 0:
            raise ContractValidationError("pages follow a terminal cursor")
        if page.cursor_out is not None:
            if page.cursor_out in seen:
                raise ContractValidationError("pagination cursor repeats")
            seen.add(page.cursor_out)
        expected = page.cursor_out
    if complete != (expected is None):
        raise ContractValidationError(
            "pagination completeness disagrees with terminal cursor"
        )


@dataclass(frozen=True, slots=True)
class CountBounds(CanonicalRecord):
    lower: int
    upper: int | None

    def __post_init__(self) -> None:
        validate_non_negative_int(self.lower)
        if (
            self.upper is not None
            and validate_non_negative_int(self.upper) < self.lower
        ):
            raise ContractValidationError("count upper bound is below lower")

    @classmethod
    def from_json(cls, raw: bytes) -> "CountBounds":
        return _construct(cls, _closed(raw, _fields(cls), "CountBounds"), "CountBounds")


@dataclass(frozen=True, slots=True)
class LabelCounts(CanonicalRecord):
    year_families: CountBounds
    late_180_270_families: CountBounds
    late_270_365_families: CountBounds
    other_primary_subfields: CountBounds

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, CountBounds)
            for value in (
                self.year_families,
                self.late_180_270_families,
                self.late_270_365_families,
                self.other_primary_subfields,
            )
        ):
            raise ContractValidationError("label counters are invalid")

    @classmethod
    def from_json(cls, raw: bytes) -> "LabelCounts":
        values = _closed(raw, _fields(cls), "LabelCounts")
        return _construct(
            cls,
            {
                name: CountBounds.from_json(canonical_json(value))
                for name, value in values.items()
            },
            "LabelCounts",
        )


@dataclass(frozen=True, slots=True)
class CitationObservation(CanonicalRecord, RecordMeta):
    paper_family_id: str
    original_version_id: str
    t0: str
    protocol: str
    target_registry_hash: str
    provider: str
    kind: str
    target_match_state: str
    target_provider_ids: tuple[str, ...]
    target_subfield_id: str | None
    target_subfield_state: str
    taxonomy_hash: str | None
    capture_started_at: str
    capture_completed_at: str
    maturity_at: str
    acquisition_lag_seconds: int | float
    pages: tuple[PaginationPage, ...]
    pagination_complete: bool
    citation_family_hashes: tuple[str, ...]
    failure: str | None

    def __post_init__(self) -> None:
        RecordMeta.__post_init__(self)
        validate_uuid4(self.paper_family_id)
        validate_uuid4(self.original_version_id)
        validate_sha256(self.target_registry_hash)
        if self.kind not in {"historical_reconstructed", "prospective_maturity"}:
            raise ContractValidationError("citation observation kind is invalid")
        if self.target_match_state not in {"matched", "unmatched", "ambiguous"}:
            raise ContractValidationError("target match state is invalid")
        if self.target_subfield_state not in {"known", "missing", "conflicting"}:
            raise ContractValidationError("target subfield state is invalid")
        if (self.target_subfield_state == "known") != (
            self.target_subfield_id is not None
        ):
            raise ContractValidationError("target subfield value disagrees with state")
        if len(set(self.target_provider_ids)) != len(self.target_provider_ids):
            raise ContractValidationError("target provider ids are duplicated")
        if self.target_match_state == "matched" and not self.target_provider_ids:
            raise ContractValidationError("matched target lacks provider identity")
        if self.taxonomy_hash is not None:
            validate_sha256(self.taxonomy_hash)
        for value in self.target_provider_ids:
            validate_non_empty_string(value)
        t0 = datetime.strptime(
            validate_utc_instant(self.t0), "%Y-%m-%dT%H:%M:%S.%fZ"
        ).replace(tzinfo=timezone.utc)
        maturity = (t0 + timedelta(days=455)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        if (
            self.maturity_at != maturity
            or self.protocol != "automatic-citations-v1"
            or self.provider != "openalex"
        ):
            raise ContractValidationError("citation observation protocol is invalid")
        started = datetime.strptime(
            validate_utc_instant(self.capture_started_at),
            "%Y-%m-%dT%H:%M:%S.%fZ",
        ).replace(tzinfo=timezone.utc)
        completed = datetime.strptime(
            validate_utc_instant(self.capture_completed_at),
            "%Y-%m-%dT%H:%M:%S.%fZ",
        ).replace(tzinfo=timezone.utc)
        if completed < started:
            raise ContractValidationError("capture clocks are reversed")
        lag = validate_finite(self.acquisition_lag_seconds)
        expected_lag = (completed - (t0 + timedelta(days=455))).total_seconds()
        if lag != expected_lag:
            raise ContractValidationError("acquisition lag differs from capture clocks")
        outside_prospective_window = started < t0 + timedelta(
            days=455
        ) or completed > t0 + timedelta(days=456)
        if not isinstance(self.pagination_complete, bool):
            raise ContractValidationError("pagination_complete must be boolean")
        for page in self.pages:
            page_started = datetime.strptime(
                page.capture_started_at, "%Y-%m-%dT%H:%M:%S.%fZ"
            ).replace(tzinfo=timezone.utc)
            page_completed = datetime.strptime(
                page.capture_completed_at, "%Y-%m-%dT%H:%M:%S.%fZ"
            ).replace(tzinfo=timezone.utc)
            if page_started < started or page_completed > completed:
                raise ContractValidationError(
                    "pagination page lies outside observation capture"
                )
        for value in self.citation_family_hashes:
            validate_sha256(value)
        if len(set(self.citation_family_hashes)) != len(self.citation_family_hashes):
            raise ContractValidationError("citation family hashes are duplicated")
        if self.failure not in {
            None,
            "initial_request_failed",
            "invalid_source",
            "outside_capture_window",
        }:
            raise ContractValidationError("citation observation failure is invalid")
        if self.kind == "prospective_maturity":
            if outside_prospective_window != (self.failure == "outside_capture_window"):
                raise ContractValidationError(
                    "prospective timing and failure state disagree"
                )
        elif self.failure == "outside_capture_window":
            raise ContractValidationError(
                "historical observation cannot have prospective window failure"
            )
        if not self.pages:
            if (
                self.failure != "initial_request_failed"
                or self.pagination_complete
                or self.citation_family_hashes
            ):
                raise ContractValidationError(
                    "empty pagination requires an initial request failure"
                )
        else:
            _validate_page_chain(self.pages, self.pagination_complete)
        if (
            self.failure == "initial_request_failed"
            and self.pages
            and (self.pages[0].status != "failed" or self.pagination_complete)
        ):
            raise ContractValidationError(
                "initial request failure lacks failed first page"
            )
        validate_utc_instant(self.created_at)

    @classmethod
    def from_json(cls, raw: bytes) -> "CitationObservation":
        values = _closed(raw, _fields(cls, meta=True), "CitationObservation")
        _meta(values)
        for name in ("target_provider_ids", "citation_family_hashes"):
            if not isinstance(values[name], list):
                raise ContractValidationError(f"{name} must be an array")
            values[name] = tuple(values[name])
        pages = values["pages"]
        if not isinstance(pages, list):
            raise ContractValidationError("pages must be an array")
        values["pages"] = tuple(
            PaginationPage.from_json(canonical_json(item)) for item in pages
        )
        return _construct(cls, values, "CitationObservation")


@dataclass(frozen=True, slots=True)
class AutomaticLabel(CanonicalRecord, RecordMeta):
    paper_family_id: str
    target_id: str
    target_definition_hash: str
    state: str
    reason: str
    observation_hash: str
    counts: LabelCounts
    witness_family_ids: tuple[str, ...]
    witness_subfield_ids: tuple[str, ...]
    completion_page_hashes: tuple[str, ...]
    maturity_at: str
    resolved_at: str
    supersedes_label_hash: str | None
    correction_hash: str | None

    def __post_init__(self) -> None:
        RecordMeta.__post_init__(self)
        validate_uuid4(self.paper_family_id)
        validate_sha256(self.target_definition_hash)
        validate_sha256(self.observation_hash)
        if self.target_id not in TARGET_IDS or self.state not in {
            "true",
            "false",
            "unknown",
        }:
            raise ContractValidationError("automatic label identity/state is invalid")
        reasons = {
            "sufficient_positive_witnesses",
            "complete_negative_evidence",
            "immature",
            "unknown_t0",
            "unmatched_target",
            "ambiguous_target",
            "initial_request_failed",
            "invalid_source",
            "outside_capture_window",
            "missing_target_subfield",
            "uncertain_dates",
            "uncertain_identity",
            "uncertain_subfields",
            "incomplete_capture",
        }
        if self.reason not in reasons:
            raise ContractValidationError("automatic label reason is invalid")
        if self.state == "true" and self.reason != "sufficient_positive_witnesses":
            raise ContractValidationError("true label lacks positive witnesses")
        if self.state == "false" and self.reason != "complete_negative_evidence":
            raise ContractValidationError(
                "false label lacks complete negative evidence"
            )
        if self.state == "unknown" and self.reason in {
            "sufficient_positive_witnesses",
            "complete_negative_evidence",
        }:
            raise ContractValidationError("unknown label has a decisive reason")
        if (self.supersedes_label_hash is None) != (self.correction_hash is None):
            raise ContractValidationError("correction lineage must be paired")
        for value in self.completion_page_hashes:
            validate_sha256(value)
        for values in (
            self.witness_family_ids,
            self.witness_subfield_ids,
            self.completion_page_hashes,
        ):
            if len(set(values)) != len(values):
                raise ContractValidationError("automatic label evidence is duplicated")
        for values in (self.witness_family_ids, self.witness_subfield_ids):
            if tuple(sorted(values)) != values:
                raise ContractValidationError(
                    "automatic label witnesses are not canonical"
                )
        for value in (*self.witness_family_ids, *self.witness_subfield_ids):
            validate_non_empty_string(value)
        validate_utc_instant(self.maturity_at)
        validate_utc_instant(self.resolved_at)
        for lineage_hash in (self.supersedes_label_hash, self.correction_hash):
            if lineage_hash is not None:
                validate_sha256(lineage_hash)

    @classmethod
    def from_json(cls, raw: bytes) -> "AutomaticLabel":
        values = _closed(raw, _fields(cls, meta=True), "AutomaticLabel")
        _meta(values)
        values["counts"] = LabelCounts.from_json(canonical_json(values["counts"]))
        for name in (
            "witness_family_ids",
            "witness_subfield_ids",
            "completion_page_hashes",
        ):
            if not isinstance(values[name], list):
                raise ContractValidationError(f"{name} must be an array")
            values[name] = tuple(values[name])
        return _construct(cls, values, "AutomaticLabel")


@dataclass(frozen=True, slots=True)
class CitationFamilyRecord(CanonicalRecord, RecordMeta):
    canonical_family_id: str
    provider_work_ids: tuple[str, ...]
    external_ids: tuple[ExternalIdentifier, ...]
    identity_evidence_hashes: tuple[str, ...]
    representative_work_id: str
    representative_rule: str
    identity_state: str
    possible_identity_cluster: str | None
    target_link_work_ids: tuple[str, ...]
    publication_interval: SourceInterval | None
    alternative_publication_intervals: tuple[SourceInterval, ...]
    date_state: str
    primary_subfield_id: str | None
    alternative_subfield_ids: tuple[str, ...]
    subfield_state: str
    raw_response_hashes: tuple[str, ...]
    is_target_family_self_link: bool

    def __post_init__(self) -> None:
        RecordMeta.__post_init__(self)
        validate_non_empty_string(self.canonical_family_id)
        if self.representative_rule not in {
            "explicit_published_version",
            "lowest_provider_id",
        }:
            raise ContractValidationError("representative rule is invalid")
        if self.identity_state not in {"resolved", "ambiguous"}:
            raise ContractValidationError("identity state is invalid")
        if self.date_state not in {
            "known",
            "missing",
            "conflicting",
        } or self.subfield_state not in {"known", "missing", "conflicting"}:
            raise ContractValidationError("date or subfield state is invalid")
        for values in (self.provider_work_ids, self.target_link_work_ids):
            if not values:
                raise ContractValidationError("provider work ids cannot be empty")
            if len(set(values)) != len(values):
                raise ContractValidationError("provider work ids are duplicated")
            for value in values:
                validate_non_empty_string(value)
        if self.representative_work_id not in self.provider_work_ids:
            raise ContractValidationError("representative work is not a family member")
        if len(set(self.external_ids)) != len(self.external_ids):
            raise ContractValidationError("external identifiers are duplicated")
        if not all(
            isinstance(value, ExternalIdentifier) for value in self.external_ids
        ):
            raise ContractValidationError("external identifiers are invalid")
        for values in (self.identity_evidence_hashes, self.raw_response_hashes):
            if not values:
                raise ContractValidationError("identity evidence cannot be empty")
            if len(set(values)) != len(values):
                raise ContractValidationError("evidence hashes are duplicated")
            for value in values:
                validate_sha256(value)
        if len(set(self.alternative_publication_intervals)) != len(
            self.alternative_publication_intervals
        ):
            raise ContractValidationError("publication alternatives are duplicated")
        if not all(
            isinstance(value, SourceInterval)
            for value in self.alternative_publication_intervals
        ) or (
            self.publication_interval is not None
            and not isinstance(self.publication_interval, SourceInterval)
        ):
            raise ContractValidationError("publication intervals are invalid")
        if len(set(self.alternative_subfield_ids)) != len(
            self.alternative_subfield_ids
        ):
            raise ContractValidationError("subfield alternatives are duplicated")
        for value in self.alternative_subfield_ids:
            validate_non_empty_string(value)
        if self.primary_subfield_id is not None:
            validate_non_empty_string(self.primary_subfield_id)
        if self.possible_identity_cluster is not None:
            validate_non_empty_string(self.possible_identity_cluster)
        if not isinstance(self.is_target_family_self_link, bool):
            raise ContractValidationError("self-link marker must be boolean")
        if (
            self.identity_state == "resolved"
            and self.possible_identity_cluster is not None
        ):
            raise ContractValidationError(
                "resolved identity cannot retain possible cluster"
            )
        if (
            self.identity_state == "ambiguous"
            and self.possible_identity_cluster is None
        ):
            raise ContractValidationError("ambiguous identity lacks possible cluster")
        if self.date_state == "known" and (
            self.publication_interval is None or self.alternative_publication_intervals
        ):
            raise ContractValidationError("known date state is inconsistent")
        if self.subfield_state == "known" and (
            self.primary_subfield_id is None or self.alternative_subfield_ids
        ):
            raise ContractValidationError("known subfield state is inconsistent")
        if self.date_state == "missing" and (
            self.publication_interval is not None
            or self.alternative_publication_intervals
        ):
            raise ContractValidationError("missing date state retains dates")
        if self.date_state == "conflicting" and (
            self.publication_interval is not None
            or len(self.alternative_publication_intervals) < 2
        ):
            raise ContractValidationError("conflicting date state lacks alternatives")
        if self.subfield_state == "missing" and (
            self.primary_subfield_id is not None or self.alternative_subfield_ids
        ):
            raise ContractValidationError("missing subfield state retains values")
        if self.subfield_state == "conflicting" and (
            self.primary_subfield_id is not None
            or len(self.alternative_subfield_ids) < 2
        ):
            raise ContractValidationError(
                "conflicting subfield state lacks alternatives"
            )

    @classmethod
    def from_json(cls, raw: bytes) -> "CitationFamilyRecord":
        values = _closed(raw, _fields(cls, meta=True), "CitationFamilyRecord")
        _meta(values)
        for name in (
            "provider_work_ids",
            "identity_evidence_hashes",
            "target_link_work_ids",
            "alternative_subfield_ids",
            "raw_response_hashes",
        ):
            if not isinstance(values[name], list):
                raise ContractValidationError(f"{name} must be an array")
            values[name] = tuple(values[name])
        external = values["external_ids"]
        intervals = values["alternative_publication_intervals"]
        if not isinstance(external, list) or not isinstance(intervals, list):
            raise ContractValidationError("family nested arrays are invalid")
        values["external_ids"] = tuple(
            ExternalIdentifier.from_json(canonical_json(item)) for item in external
        )
        values["alternative_publication_intervals"] = tuple(
            SourceInterval.from_json(canonical_json(item)) for item in intervals
        )
        interval = values["publication_interval"]
        values["publication_interval"] = (
            None
            if interval is None
            else SourceInterval.from_json(canonical_json(interval))
        )
        return _construct(cls, values, "CitationFamilyRecord")


@dataclass(frozen=True, slots=True)
class TensorRef(CanonicalRecord):
    payload_hash: str
    dtype: str
    shape: tuple[int, ...]
    layout: str
    byte_length: int

    def __post_init__(self) -> None:
        validate_sha256(self.payload_hash)
        widths = {"float32_le": 4, "float64_le": 8, "uint8": 1}
        if (
            not isinstance(self.dtype, str)
            or self.dtype not in widths
            or self.layout != "C"
        ):
            raise ContractValidationError("tensor dtype or layout is invalid")
        if not isinstance(self.shape, tuple) or not 1 <= len(self.shape) <= 2:
            raise ContractValidationError("tensor shape requires one or two dimensions")
        expected = widths[self.dtype]
        for dimension in self.shape:
            expected *= validate_positive_int(dimension)
        if validate_non_negative_int(self.byte_length) != expected:
            raise ContractValidationError("tensor shape and byte length disagree")

    @classmethod
    def from_json(cls, raw: bytes) -> "TensorRef":
        values = _closed(raw, _fields(cls), "TensorRef")
        if not isinstance(values["shape"], list):
            raise ContractValidationError("tensor shape must be an array")
        values["shape"] = tuple(values["shape"])
        return _construct(cls, values, "TensorRef")


@dataclass(frozen=True, slots=True)
class CombinedFeatureRecord(CanonicalRecord, RecordMeta):
    paper_family_id: str
    original_version_id: str
    original_source_hash: str
    extraction_hash: str
    representation_hash: str
    overview_embedding_hash: str
    ordered_passage_embedding_hashes: tuple[str, ...]
    ordered_passage_weights: tuple[float, ...]
    pooled_passage_vector: TensorRef
    combined_vector: TensorRef
    feature_policy: str
    computed_at: str

    def __post_init__(self) -> None:
        RecordMeta.__post_init__(self)
        validate_uuid4(self.paper_family_id)
        validate_uuid4(self.original_version_id)
        for value in (
            self.original_source_hash,
            self.extraction_hash,
            self.representation_hash,
            self.overview_embedding_hash,
        ):
            validate_sha256(value)
        if (
            not isinstance(self.ordered_passage_embedding_hashes, tuple)
            or not isinstance(self.ordered_passage_weights, tuple)
            or not self.ordered_passage_embedding_hashes
            or len(self.ordered_passage_weights)
            != len(self.ordered_passage_embedding_hashes)
        ):
            raise ContractValidationError(
                "feature passage references and weights differ"
            )
        for value in self.ordered_passage_embedding_hashes:
            validate_sha256(value)
        for weight in self.ordered_passage_weights:
            if validate_finite(weight) <= 0:
                raise ContractValidationError(
                    "feature passage weights must be positive"
                )
        for reference, shape in (
            (self.pooled_passage_vector, (EMBEDDING_DIMENSION,)),
            (self.combined_vector, (EMBEDDING_FEATURE_DIMENSION,)),
        ):
            if (
                not isinstance(reference, TensorRef)
                or reference.dtype != "float32_le"
                or reference.shape != shape
            ):
                raise ContractValidationError(
                    "feature tensor reference is incompatible"
                )
        if self.feature_policy != "overview_passage_sqrt2_v1":
            raise ContractValidationError("feature policy is invalid")
        if validate_utc_instant(self.computed_at) > validate_utc_instant(
            self.created_at
        ):
            raise ContractValidationError("feature computation follows record creation")

    @classmethod
    def from_json(cls, raw: bytes) -> "CombinedFeatureRecord":
        values = _closed(raw, _fields(cls, meta=True), "CombinedFeatureRecord")
        _meta(values)
        for name in ("ordered_passage_embedding_hashes", "ordered_passage_weights"):
            if not isinstance(values[name], list):
                raise ContractValidationError(f"{name} must be an array")
            values[name] = tuple(values[name])
        for name in ("pooled_passage_vector", "combined_vector"):
            values[name] = TensorRef.from_json(canonical_json(values[name]))
        return _construct(cls, values, "CombinedFeatureRecord")


@dataclass(frozen=True, slots=True)
class TrainingArrays(CanonicalRecord, RecordMeta):
    ordered_family_ids: tuple[str, ...]
    features: TensorRef
    labels: TensorRef
    known_mask: TensorRef
    feature_hashes: tuple[str, ...]
    label_hashes: tuple[tuple[str | None, str | None, str | None], ...]
    corpus_release_hash: str
    split_hash: str
    target_registry_hash: str
    representation_hash: str
    partition: str

    def __post_init__(self) -> None:
        RecordMeta.__post_init__(self)
        if not all(
            isinstance(value, tuple)
            for value in (
                self.ordered_family_ids,
                self.feature_hashes,
                self.label_hashes,
            )
        ):
            raise ContractValidationError("training rows must be immutable tuples")
        count = len(self.ordered_family_ids)
        if count == 0 or len(set(self.ordered_family_ids)) != count:
            raise ContractValidationError(
                "training family ids must be nonempty and unique"
            )
        for family_id in self.ordered_family_ids:
            validate_uuid4(family_id)
        if (
            not isinstance(self.features, TensorRef)
            or not isinstance(self.labels, TensorRef)
            or not isinstance(self.known_mask, TensorRef)
            or self.features.dtype != "float32_le"
            or self.features.shape != (count, HEAD_INPUT_DIMENSION)
            or self.labels.dtype != "uint8"
            or self.labels.shape != (count, 3)
            or self.known_mask.dtype != "uint8"
            or self.known_mask.shape != (count, 3)
        ):
            raise ContractValidationError("training tensor references are incompatible")
        if len(self.feature_hashes) != count or len(self.label_hashes) != count:
            raise ContractValidationError("training row reference counts differ")
        for feature_hash in self.feature_hashes:
            validate_sha256(feature_hash)
        for row in self.label_hashes:
            if not isinstance(row, tuple) or len(row) != 3:
                raise ContractValidationError("training label hashes must be N by 3")
            for label_hash in row:
                if label_hash is not None:
                    validate_sha256(label_hash)
        for value in (
            self.corpus_release_hash,
            self.split_hash,
            self.target_registry_hash,
            self.representation_hash,
        ):
            validate_sha256(value)
        if self.partition not in {
            "fit",
            "development",
            "calibration",
            "locked_evaluation",
            "refresh_fit",
            "refresh_calibration",
        }:
            raise ContractValidationError("training partition is invalid")

    @classmethod
    def from_json(cls, raw: bytes) -> "TrainingArrays":
        values = _closed(raw, _fields(cls, meta=True), "TrainingArrays")
        _meta(values)
        for name in ("ordered_family_ids", "feature_hashes", "label_hashes"):
            if not isinstance(values[name], list):
                raise ContractValidationError(f"{name} must be an array")
        values["ordered_family_ids"] = tuple(values["ordered_family_ids"])
        values["feature_hashes"] = tuple(values["feature_hashes"])
        labels = values["label_hashes"]
        if not all(isinstance(row, list) for row in labels):
            raise ContractValidationError("label_hashes rows must be arrays")
        values["label_hashes"] = tuple(tuple(row) for row in labels)
        for name in ("features", "labels", "known_mask"):
            values[name] = TensorRef.from_json(canonical_json(values[name]))
        return _construct(cls, values, "TrainingArrays")
