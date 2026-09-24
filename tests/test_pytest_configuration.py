import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_test_modules_in_different_directories_may_share_a_basename(
    tmp_path: Path,
) -> None:
    for directory in ("first", "second"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "test_same.py").write_text(
            "def test_runs() -> None:\n    pass\n"
        )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(ROOT / "pyproject.toml"),
            "--rootdir",
            str(tmp_path),
            "-p",
            "no:cacheprovider",
            "-q",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout
