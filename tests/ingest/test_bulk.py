"""Pure logic for arXiv S3 bulk acquisition (#146): the permission and
credential gates, manifest parsing, tar member selection, LaTeX decoding and
the hand-rolled SigV4 signer. `BulkWorker`'s storage-facing run loop is
exercised end to end against real PostgreSQL and a loopback S3 stand-in
under `tests/integration/corpus/`, not here.
"""

from __future__ import annotations

import gzip
import json
import io
import tarfile
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from research_agent.ingest import bulk

EVIDENCE_ALLOWED = (
    "# arXiv bulk data on S3\n\n"
    "## Status\n\n"
    "`arxiv_bulk_s3` is added to the permission registry as "
    "**allowed for research use**.\n"
)


def _evidence(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "arxiv-bulk.md"
    path.write_text(text)
    return path


# --- require_permission ------------------------------------------------------


def test_require_permission_returns_the_evidence_file_hash(tmp_path: Path) -> None:
    path = _evidence(tmp_path, EVIDENCE_ALLOWED)
    assert bulk.require_permission(path) == sha256(path.read_bytes()).hexdigest()


def test_require_permission_refuses_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(bulk.PermissionRefused):
        bulk.require_permission(tmp_path / "missing.md")


def test_require_permission_refuses_non_utf8_bytes(tmp_path: Path) -> None:
    path = tmp_path / "arxiv-bulk.md"
    path.write_bytes(b"\xff\xfe\x00not utf-8")
    with pytest.raises(bulk.PermissionRefused):
        bulk.require_permission(path)


def test_require_permission_refuses_a_file_with_no_status_section(
    tmp_path: Path,
) -> None:
    path = _evidence(tmp_path, "# arXiv bulk data on S3\n\nNo status here.\n")
    with pytest.raises(bulk.PermissionRefused):
        bulk.require_permission(path)


def test_require_permission_refuses_a_status_missing_the_adapter_name(
    tmp_path: Path,
) -> None:
    path = _evidence(
        tmp_path, "# arXiv bulk data on S3\n\n## Status\n\nallowed, but unnamed.\n"
    )
    with pytest.raises(bulk.PermissionRefused):
        bulk.require_permission(path)


def test_require_permission_refuses_a_status_that_does_not_say_allowed(
    tmp_path: Path,
) -> None:
    path = _evidence(
        tmp_path,
        "# arXiv bulk data on S3\n\n## Status\n\n`arxiv_bulk_s3` is blocked.\n",
    )
    with pytest.raises(bulk.PermissionRefused):
        bulk.require_permission(path)


# --- credentials_from_environment --------------------------------------------


def test_credentials_from_environment_reads_the_two_required_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIDEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    assert bulk.credentials_from_environment() == ("AKIDEXAMPLE", "secret", None)


def test_credentials_from_environment_includes_an_optional_session_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIDEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "token")
    assert bulk.credentials_from_environment() == ("AKIDEXAMPLE", "secret", "token")


def test_credentials_from_environment_refuses_a_missing_access_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    with pytest.raises(bulk.CredentialsUnavailable):
        bulk.credentials_from_environment()


def test_credentials_from_environment_refuses_a_missing_secret_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIDEXAMPLE")
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    with pytest.raises(bulk.CredentialsUnavailable):
        bulk.credentials_from_environment()


# --- parse_manifest -----------------------------------------------------------


def _manifest_xml(*files: str) -> bytes:
    body = "".join(files)
    return f"<arXivSRC>{body}</arXivSRC>".encode()


def _file_entry(
    filename: str = "src/arXiv_src_2306_001.tar",
    first_item: str = "2306.00001",
    last_item: str = "2306.00999",
    yymm: str = "2306",
) -> str:
    return (
        "<file><content_md5sum>x</content_md5sum>"
        f"<filename>{filename}</filename>"
        f"<first_item>{first_item}</first_item>"
        f"<last_item>{last_item}</last_item>"
        f"<yymm>{yymm}</yymm></file>"
    )


def test_parse_manifest_reads_ordered_bundle_entries() -> None:
    xml = _manifest_xml(
        _file_entry(filename="src/arXiv_src_2306_001.tar"),
        _file_entry(
            filename="src/arXiv_src_2307_001.tar",
            first_item="2307.00001",
            last_item="2307.00999",
            yymm="2307",
        ),
    )
    entries = bulk.parse_manifest(xml)
    assert [entry.filename for entry in entries] == [
        "src/arXiv_src_2306_001.tar",
        "src/arXiv_src_2307_001.tar",
    ]
    assert entries[0].first_item == "2306.00001"
    assert entries[0].last_item == "2306.00999"
    assert entries[0].yymm == "2306"


def test_parse_manifest_skips_an_entry_missing_a_required_field() -> None:
    incomplete = (
        "<file><filename>src/arXiv_src_2306_001.tar</filename>"
        "<first_item>2306.00001</first_item></file>"
    )
    xml = f"<arXivSRC>{incomplete}{_file_entry()}</arXivSRC>".encode()
    entries = bulk.parse_manifest(xml)
    assert len(entries) == 1
    assert entries[0].filename == "src/arXiv_src_2306_001.tar"


def test_parse_manifest_refuses_malformed_xml() -> None:
    with pytest.raises(bulk.ManifestFormatError):
        bulk.parse_manifest(b"<arXivSRC><file>not closed")


def test_parse_manifest_refuses_a_manifest_with_no_usable_entries() -> None:
    with pytest.raises(bulk.ManifestFormatError):
        bulk.parse_manifest(b"<arXivSRC></arXivSRC>")


# --- bundle_for_family ---------------------------------------------------------


def test_bundle_for_family_finds_the_bundle_containing_the_id() -> None:
    entries = bulk.parse_manifest(
        _manifest_xml(
            _file_entry(
                filename="a.tar", first_item="2306.00001", last_item="2306.00500"
            ),
            _file_entry(
                filename="b.tar", first_item="2306.00501", last_item="2306.00999"
            ),
        )
    )
    assert bulk.bundle_for_family(entries, "2306.00777").filename == "b.tar"


def test_bundle_for_family_matches_at_the_exact_boundaries() -> None:
    entries = bulk.parse_manifest(
        _manifest_xml(
            _file_entry(
                filename="a.tar", first_item="2306.00001", last_item="2306.00500"
            )
        )
    )
    assert bulk.bundle_for_family(entries, "2306.00001").filename == "a.tar"
    assert bulk.bundle_for_family(entries, "2306.00500").filename == "a.tar"


def test_bundle_for_family_returns_none_when_no_bundle_contains_the_id() -> None:
    entries = bulk.parse_manifest(
        _manifest_xml(
            _file_entry(
                filename="a.tar", first_item="2306.00001", last_item="2306.00500"
            )
        )
    )
    assert bulk.bundle_for_family(entries, "2308.00001") is None


# --- _find_member ---------------------------------------------------------------


def _tar_with(names: list[str]) -> tarfile.TarFile:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name in names:
            data = name.encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    buffer.seek(0)
    return tarfile.open(fileobj=buffer, mode="r")


def test_find_member_matches_the_exact_stem() -> None:
    tar = _tar_with(["2306.00001"])
    member = bulk._find_member(tar, "2306.00001")
    assert member is not None and member.name == "2306.00001"


def test_find_member_matches_a_suffixed_stem() -> None:
    tar = _tar_with(["2306.00001.tex"])
    member = bulk._find_member(tar, "2306.00001")
    assert member is not None and member.name == "2306.00001.tex"


def test_find_member_does_not_match_a_longer_numeric_id() -> None:
    # "2306.000011" is a distinct, longer arXiv id; a naive prefix match
    # would wrongly treat it as "2306.00001" with a numeric suffix.
    tar = _tar_with(["2306.000011"])
    assert bulk._find_member(tar, "2306.00001") is None


def test_find_member_returns_none_when_absent() -> None:
    tar = _tar_with(["2306.00002"])
    assert bulk._find_member(tar, "2306.00001") is None


# --- decode_latex_source ---------------------------------------------------------


def test_decode_latex_source_reads_plain_gzip_text() -> None:
    raw = gzip.compress("\\section{Intro}\ntext".encode())
    assert bulk.decode_latex_source(raw) == "\\section{Intro}\ntext"


def test_decode_latex_source_reads_ungzipped_text() -> None:
    assert bulk.decode_latex_source(b"plain tex, not gzipped") == (
        "plain tex, not gzipped"
    )


def test_decode_latex_source_returns_none_for_a_pdf_only_submission() -> None:
    assert bulk.decode_latex_source(b"%PDF-1.5 rest of the file") is None
    assert bulk.decode_latex_source(gzip.compress(b"%PDF-1.5 rest")) is None


def test_decode_latex_source_picks_the_largest_tex_member_of_a_nested_tar() -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as inner:
        for name, data in (
            ("small.tex", b"\\section{A}"),
            ("main.tex", b"\\section{Much larger main document}" * 5),
            ("notes.txt", b"not tex, ignored regardless of size" * 10),
        ):
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            inner.addfile(info, io.BytesIO(data))
    raw = gzip.compress(buffer.getvalue())
    assert bulk.decode_latex_source(raw) == ("\\section{Much larger main document}" * 5)


def _gzipped_tar(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as inner:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            inner.addfile(info, io.BytesIO(data))
    return gzip.compress(buffer.getvalue())


def test_decode_latex_source_resolves_the_root_and_inlines_its_inputs() -> None:
    raw = _gzipped_tar(
        {
            "main.tex": (
                b"\\documentclass{revtex4}\n\\begin{document}\n"
                b"\\input{sec/intro}\n\\include{sec/results}\n\\end{document}\n"
            ),
            "sec/intro.tex": b"\\section{Introduction}\nIntro.\n",
            # latin-1 member beside utf-8 ones: each decodes on its own.
            "sec/results.tex": "\\section{Results}\nCaf\u00e9.\n".encode("latin-1"),
            # Larger than the root, so the largest-member rule chose it.
            "response-to-referees.tex": b"Dear editor, " * 100,
        }
    )
    text = bulk.decode_latex_source(raw)
    assert text is not None
    assert text.startswith("\\documentclass{revtex4}")
    assert "\\section{Introduction}\nIntro." in text
    assert "\\section{Results}\nCaf\u00e9." in text
    assert "Dear editor" not in text


def test_extractor_manifest_names_the_v2_latex_extractor() -> None:
    assert bulk.EXTRACTOR_MANIFEST_HASH == (
        sha256(b"reader.extract-latex-v2").hexdigest()
    )


def test_decode_latex_source_returns_none_for_a_tar_with_no_tex_member() -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as inner:
        data = b"not tex"
        info = tarfile.TarInfo(name="readme.txt")
        info.size = len(data)
        inner.addfile(info, io.BytesIO(data))
    assert bulk.decode_latex_source(gzip.compress(buffer.getvalue())) is None


def test_decode_latex_source_falls_back_to_latin_1() -> None:
    raw = "café \x92".encode("latin-1")
    assert bulk.decode_latex_source(raw) == "café \x92"


# --- extract_source_member -------------------------------------------------------


def test_extract_source_member_extracts_latex_text() -> None:
    raw = "\\section{Intro}\nSome body text.".encode()
    record, demand = bulk.extract_source_member(
        str(bulk.derived_uuid("paper-version", "2306.00001")),
        sha256(raw).hexdigest(),
        raw,
        bulk.utc_now(),
    )
    assert record.coverage != "unavailable"
    assert record.source_hash == sha256(raw).hexdigest()
    assert demand.wall_seconds >= 0.0


def test_extract_source_member_records_unsupported_for_a_pdf_only_source() -> None:
    raw = b"%PDF-1.5 no latex here"
    record, _demand = bulk.extract_source_member(
        str(bulk.derived_uuid("paper-version", "2306.00002")),
        sha256(raw).hexdigest(),
        raw,
        bulk.utc_now(),
    )
    assert record.coverage == "unavailable"
    assert record.coverage_reasons == ("unsupported_source",)


# --- _sigv4_headers ----------------------------------------------------------------


_NOW = datetime(2023, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _headers(**overrides: object) -> dict[str, str]:
    base = dict(
        method="GET",
        host="arxiv.s3.us-east-1.amazonaws.com",
        path="/src/arXiv_src_manifest.xml",
        region="us-east-1",
        access_key="AKIDEXAMPLE",
        secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        session_token=None,
        payload_hash=sha256(b"").hexdigest(),
        now=_NOW,
    )
    base.update(overrides)
    return bulk._sigv4_headers(**base)  # type: ignore[arg-type]


def test_sigv4_headers_requests_requester_pays() -> None:
    assert _headers()["x-amz-request-payer"] == "requester"


def test_sigv4_headers_names_the_access_key_and_scope_in_the_authorization() -> None:
    authorization = _headers()["authorization"]
    assert authorization.startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
    assert "20230601/us-east-1/s3/aws4_request" in authorization
    assert "SignedHeaders=" in authorization
    assert "Signature=" in authorization


def test_sigv4_headers_omits_the_session_token_header_when_absent() -> None:
    assert "x-amz-security-token" not in _headers()


def test_sigv4_headers_includes_the_session_token_header_when_present() -> None:
    assert _headers(session_token="token")["x-amz-security-token"] == "token"


def test_sigv4_headers_is_deterministic_for_the_same_inputs() -> None:
    assert _headers()["authorization"] == _headers()["authorization"]


def test_sigv4_headers_signature_changes_with_the_secret_key() -> None:
    assert (
        _headers()["authorization"]
        != _headers(secret_key="different-secret")["authorization"]
    )


def test_sigv4_headers_signature_changes_with_the_payload_hash() -> None:
    other = sha256(b"body").hexdigest()
    assert _headers()["authorization"] != _headers(payload_hash=other)["authorization"]


# --- _population_hash / identity_for ----------------------------------------------


def _candidate(family_id: str) -> object:
    from research_agent.learning.corpus import PilotCandidate

    return PilotCandidate(family_id, "2023-06-01T00:00:00.000000Z", ("cs.AI",))


def test_population_hash_is_stable_for_the_same_population() -> None:
    population = (_candidate("2306.00001"), _candidate("2306.00002"))
    assert bulk._population_hash(population) == bulk._population_hash(population)


def test_population_hash_changes_with_the_population_order() -> None:
    a, b = _candidate("2306.00001"), _candidate("2306.00002")
    assert bulk._population_hash((a, b)) != bulk._population_hash((b, a))


def test_population_hash_changes_with_membership() -> None:
    population = (_candidate("2306.00001"),)
    other = (_candidate("2306.00002"),)
    assert bulk._population_hash(population) != bulk._population_hash(other)


def test_identity_for_ties_the_permission_hash_to_the_evidence_file(
    tmp_path: Path,
) -> None:
    path = _evidence(tmp_path, EVIDENCE_ALLOWED)
    identity = bulk.identity_for(
        bucket="arxiv", population_hash="a" * 64, evidence_path=path
    )
    assert identity.permission_evidence_hash == sha256(path.read_bytes()).hexdigest()


def test_identity_for_refuses_when_the_evidence_does_not_confirm_permission(
    tmp_path: Path,
) -> None:
    path = _evidence(tmp_path, "# arXiv bulk data on S3\n\n## Status\n\nblocked.\n")
    with pytest.raises(bulk.PermissionRefused):
        bulk.identity_for(bucket="arxiv", population_hash="a" * 64, evidence_path=path)


def test_identity_for_changes_the_config_hash_with_the_population(
    tmp_path: Path,
) -> None:
    path = _evidence(tmp_path, EVIDENCE_ALLOWED)
    first = bulk.identity_for(
        bucket="arxiv", population_hash="a" * 64, evidence_path=path
    )
    second = bulk.identity_for(
        bucket="arxiv", population_hash="b" * 64, evidence_path=path
    )
    assert first.config_hash != second.config_hash


# --- population counts -------------------------------------------------------


def _population_entry(family_id: str, **extra: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "family_id": family_id,
        "first_public_at": "2023-06-01T00:00:00.000000Z",
        "categories": ["cs.AI"],
        "author_count": 3,
        "version_count": 2,
    }
    entry.update(extra)
    return entry


def test_load_population_reads_the_counts_the_record_needs(tmp_path: Path) -> None:
    path = tmp_path / "population.json"
    path.write_text(json.dumps([_population_entry("2306.00001")]))
    population = bulk.load_population(path)
    assert population[0].family_id == "2306.00001"
    assert bulk.load_population_counts(path) == {"2306.00001": (3, 2)}


def test_load_population_refuses_an_entry_without_counts(tmp_path: Path) -> None:
    """The prohibited alternative is a record with a made-up count: the
    bundle carries no listing, so an entry that does not say is refused."""
    path = tmp_path / "population.json"
    entry = _population_entry("2306.00001")
    del entry["version_count"]
    path.write_text(json.dumps([entry]))
    with pytest.raises(ValueError, match="2306.00001 lacks version_count"):
        bulk.load_population(path)


def test_load_population_refuses_a_non_integral_count(tmp_path: Path) -> None:
    path = tmp_path / "population.json"
    path.write_text(json.dumps([_population_entry("2306.00001", author_count="3")]))
    with pytest.raises(ValueError, match="invalid counts"):
        bulk.load_population(path)
