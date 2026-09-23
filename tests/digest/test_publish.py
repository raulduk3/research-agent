from dataclasses import replace

import pytest

from research_agent.digest.build import build_digest
from research_agent.digest.nominations import Nomination
from research_agent.digest.publish import DigestAccessRefused, publish_digest

BASE_KWARGS = dict(
    batch_id="batch-hash-1",
    source_watermark=1,
    cutoff="2026-09-22T00:00:00.000000Z",
    profile_id="profile-hash-1",
    control_rubric_version="v1",
    day_ordinal=0,
    population_nominations={"cfg-a": [Nomination("p1", 0.9), Nomination("p2", 0.5)]},
    eligible_family_ids=["p1", "p2", "p3"],
    service_picks={},
)


def _manifest(island: str):
    return build_digest(**{**BASE_KWARGS, "island": island})


def test_cs_rater_reads_the_cs_digest():
    publication = publish_digest(_manifest("cs"))
    assert publication.readable_by == "cs_rater"
    assert publication.read(identity="cs_rater") is publication.manifest


def test_unauthenticated_identity_is_refused():
    publication = publish_digest(_manifest("cs"))
    with pytest.raises(DigestAccessRefused):
        publication.read(identity=None)


def test_other_islands_rater_is_refused():
    publication = publish_digest(_manifest("cs"))
    with pytest.raises(DigestAccessRefused):
        publication.read(identity="quant_ph_rater")


def test_quant_ph_rater_reads_only_its_own_island():
    cs_publication = publish_digest(_manifest("cs"))
    quant_publication = publish_digest(_manifest("quant-ph"))
    with pytest.raises(DigestAccessRefused):
        cs_publication.read(identity="quant_ph_rater")
    assert (
        quant_publication.read(identity="quant_ph_rater") is quant_publication.manifest
    )


def test_q_bio_digest_has_no_reader_at_all():
    publication = publish_digest(_manifest("q-bio"))
    assert publication.readable_by is None
    for identity in ("cs_rater", "quant_ph_rater", "q_bio_rater", None):
        with pytest.raises(DigestAccessRefused):
            publication.read(identity=identity)


def test_digest_id_is_the_manifest_content_hash_and_stable_on_replay():
    manifest = _manifest("cs")
    first = publish_digest(manifest)
    second = publish_digest(manifest)
    assert first.digest_id == manifest.digest_hash
    assert first.digest_id == second.digest_id


def test_unknown_island_is_refused_before_publication():
    bad_manifest = replace(_manifest("cs"), island="unknown-island")
    with pytest.raises(ValueError):
        publish_digest(bad_manifest)


def test_oversized_manifest_is_refused_before_publication():
    manifest = _manifest("cs")
    padded_entries = manifest.entries + (manifest.entries[0],) * 12
    bad_manifest = replace(manifest, entries=padded_entries)
    with pytest.raises(ValueError):
        publish_digest(bad_manifest)
