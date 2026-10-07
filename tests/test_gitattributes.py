"""`.gitattributes` keeps digest-checked JSON byte-exact under `core.autocrlf=true`."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
DIGEST_CHECKED_DIRECTORIES = ("artifacts/agency-packs", "release", "schemas")
PINNED_PAYLOAD = b'{\n  "schema_version": "1.0"\n}\n'
PINNED_PATHS = (
    "artifacts/agency-packs/clicks-and-mortars/packs/9.9.9.json",
    "release/example-policy.json",
    "schemas/release/example.schema.json",
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _git(cwd: Path, *args: str, stdin: bytes | None = None) -> bytes:
    completed = subprocess.run(
        [
            "git",
            "-c",
            "core.autocrlf=true",
            "-c",
            "user.name=tester",
            "-c",
            "user.email=tester@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=cwd,
        input=stdin,
        capture_output=True,
        check=True,
    )
    return completed.stdout


def test_every_tracked_digest_checked_json_file_is_pinned_to_lf() -> None:
    try:
        listing = _git(ROOT, "ls-files", "-z", "--", *DIGEST_CHECKED_DIRECTORIES)
    except (subprocess.CalledProcessError, OSError):
        pytest.skip("not running inside a git checkout")
    paths = [
        path for path in listing.decode("utf-8").split("\0") if path.endswith(".json")
    ]
    assert paths, "expected tracked JSON under the digest-checked directories"

    attributes = _git(ROOT, "check-attr", "-z", "text", "eol", "--stdin", stdin=listing)
    fields = attributes.decode("utf-8").split("\0")
    observed = {
        (path, attribute): value
        for path, attribute, value in zip(fields[0::3], fields[1::3], fields[2::3])
    }

    unpinned = [
        path
        for path in paths
        if observed.get((path, "text")) != "set" or observed.get((path, "eol")) != "lf"
    ]
    assert unpinned == []


def test_pinned_json_keeps_lf_bytes_on_checkout_and_commit_under_autocrlf(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "--quiet")
    shutil.copyfile(ROOT / ".gitattributes", tmp_path / ".gitattributes")
    control = tmp_path / "unpinned.txt"
    for relative in (*PINNED_PATHS, "unpinned.txt"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(PINNED_PAYLOAD)
    _git(tmp_path, "add", "--all")
    _git(tmp_path, "commit", "--quiet", "--message", "fixture")

    for relative in (*PINNED_PATHS, "unpinned.txt"):
        (tmp_path / relative).unlink()
    _git(tmp_path, "checkout", "--quiet", "--", ".")

    # The unpinned control proves autocrlf is really rewriting checkouts here.
    assert control.read_bytes() == PINNED_PAYLOAD.replace(b"\n", b"\r\n")
    for relative in PINNED_PATHS:
        assert (tmp_path / relative).read_bytes() == PINNED_PAYLOAD

    edited = tmp_path / PINNED_PATHS[0]
    edited.write_bytes(PINNED_PAYLOAD.replace(b"\n", b"\r\n"))
    _git(tmp_path, "add", "--", PINNED_PATHS[0])
    assert _git(tmp_path, "cat-file", "blob", f":{PINNED_PATHS[0]}") == PINNED_PAYLOAD
