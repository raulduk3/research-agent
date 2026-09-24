import json
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ISSUE_CERTS = ROOT / "bin" / "issue-certs"


def test_issues_every_certificate_the_compose_definition_mounts(tmp_path: Path) -> None:
    directory = tmp_path / "certs"
    subprocess.run((str(ISSUE_CERTS), str(directory)), check=True, capture_output=True)
    text = re.sub(
        r"\$\{[A-Z_]+:\?[^}]*\}", "VAR", (ROOT / "deploy/compose.yaml").read_text()
    )
    mounted = {
        secret["file"].removeprefix("VAR/")
        for secret in yaml.safe_load(text)["secrets"].values()
        if secret["file"].endswith((".pem", ".key"))
    }
    assert mounted
    missing = sorted(name for name in mounted if not (directory / name).is_file())
    assert missing == []
    fingerprints = json.loads((directory / "fingerprints.json").read_text())
    assert {"app", "owner"} <= set(fingerprints)


def test_app_and_owner_server_certificates_name_their_service(tmp_path: Path) -> None:
    directory = tmp_path / "certs"
    subprocess.run((str(ISSUE_CERTS), str(directory)), check=True, capture_output=True)
    for service in ("app", "owner"):
        text = subprocess.run(
            (
                "openssl",
                "x509",
                "-noout",
                "-ext",
                "subjectAltName,extendedKeyUsage",
                "-in",
                str(directory / f"{service}-server.pem"),
            ),
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert f"DNS:{service}" in text
        assert "TLS Web Server Authentication" in text
