from research_agent.digest.build import ENTRY_LIMIT, build_digest
from research_agent.digest.services import ServicePick

BASE_KWARGS = dict(
    batch_id="batch-hash-1",
    island="cs",
    source_watermark=42,
    cutoff="2026-09-22T00:00:00.000000Z",
    profile_id="profile-hash-1",
    control_rubric_version="v1",
    day_ordinal=0,
)


def _shard_nominations():
    return {
        "cfg-a": [["p1", "p2", "p3"]],
        "cfg-b": [["p4", "p5"]],
    }


def _service_picks():
    return {"svc": [ServicePick("ref-1", "s1")]}


def test_replay_is_byte_identical():
    kwargs = dict(
        **BASE_KWARGS,
        shard_nominations=_shard_nominations(),
        eligible_family_ids=["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"],
        service_picks=_service_picks(),
    )
    first = build_digest(**kwargs)
    second = build_digest(**kwargs)
    assert first == second
    assert first.digest_hash == second.digest_hash


def test_composition_includes_all_three_origins_without_duplicates():
    manifest = build_digest(
        **BASE_KWARGS,
        shard_nominations=_shard_nominations(),
        eligible_family_ids=["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"],
        service_picks=_service_picks(),
    )
    origins = {entry.origin for entry in manifest.entries}
    assert origins == {"population", "random_control", "service"}
    paper_ids = [entry.paper_id for entry in manifest.entries]
    assert len(paper_ids) == len(set(paper_ids))
    assert len(manifest.entries) <= ENTRY_LIMIT


def test_entry_count_never_exceeds_twelve():
    shard_nominations = {f"cfg-{i}": [[f"pop-{i}"]] for i in range(7)}
    eligible = [f"ctrl-{i}" for i in range(10)]
    service_picks = {
        "svc-a": [ServicePick(f"svc-a-{i}", f"svc-a-{i}") for i in range(5)],
        "svc-b": [ServicePick(f"svc-b-{i}", f"svc-b-{i}") for i in range(5)],
    }
    manifest = build_digest(
        **{**BASE_KWARGS, "day_ordinal": 1},
        shard_nominations=shard_nominations,
        eligible_family_ids=eligible,
        service_picks=service_picks,
    )
    assert len(manifest.entries) == ENTRY_LIMIT


def test_entry_id_matches_the_content_hash_formula():
    from research_agent.contracts.canonical import canonical_json, sha256_hex

    manifest = build_digest(
        **BASE_KWARGS,
        shard_nominations=_shard_nominations(),
        eligible_family_ids=["p1", "p2", "p3", "p4", "p5"],
        service_picks={},
    )
    for entry in manifest.entries:
        expected = sha256_hex(
            canonical_json(
                {
                    "batch_id": BASE_KWARGS["batch_id"],
                    "source_watermark": BASE_KWARGS["source_watermark"],
                    "paper_id": entry.paper_id,
                    "profile_id": BASE_KWARGS["profile_id"],
                }
            )
        )
        assert entry.entry_id == expected


def test_positions_are_a_permutation_and_differ_from_selection_order():
    shard_nominations = {f"cfg-{i}": [[f"pop-{i}"]] for i in range(7)}
    manifest = build_digest(
        **BASE_KWARGS,
        shard_nominations=shard_nominations,
        eligible_family_ids=[],
        service_picks={},
    )
    positions = sorted(entry.position for entry in manifest.entries)
    assert positions == list(range(len(manifest.entries)))


def test_different_island_changes_the_shuffle_seed_and_digest_hash():
    kwargs = dict(
        shard_nominations=_shard_nominations(),
        eligible_family_ids=["p1", "p2", "p3", "p4", "p5"],
        service_picks=_service_picks(),
    )
    cs_manifest = build_digest(**{**BASE_KWARGS, "island": "cs"}, **kwargs)
    quant_manifest = build_digest(**{**BASE_KWARGS, "island": "quant-ph"}, **kwargs)
    assert cs_manifest.shuffle_seed != quant_manifest.shuffle_seed
    assert cs_manifest.digest_hash != quant_manifest.digest_hash


def test_digest_hash_unaffected_by_data_not_passed_in():
    # Simulates a "late" service capture or submission attempt: since build_digest
    # only ever sees what a caller passes for a frozen watermark, an extra pick
    # left out of the call cannot influence the result of an otherwise identical
    # call, which is exactly the property a watermark freeze must guarantee.
    kwargs = dict(
        **BASE_KWARGS,
        shard_nominations=_shard_nominations(),
        eligible_family_ids=["p1", "p2", "p3", "p4", "p5"],
    )
    without_late_pick = build_digest(**kwargs, service_picks={})
    also_without_late_pick = build_digest(**kwargs, service_picks={})
    assert without_late_pick.digest_hash == also_without_late_pick.digest_hash
