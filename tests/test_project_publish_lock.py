"""Cross-process authority-lock and stale-recovery contracts."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import socket
import threading

import pytest

import vanjaro_cli.project.publish_lock as publish_lock
from tests.test_project_publish import _patch_portal, _publish_workspace
from vanjaro_cli.commands.project_cmd import project
from vanjaro_cli.orchestration.project_publish import prepare_project_publish
from vanjaro_cli.project import ApprovalGate, ProjectApprovalError, request_approval
from vanjaro_cli.project.publish_lock import (
    PUBLISH_GATE_PATH,
    PUBLISH_LOCK_PATH,
    PublishLockError,
    clear_stale_publish_lock,
    publish_operation_lock,
)


def _stale_lock(root: Path, *, token: str = "a" * 32) -> Path:
    path = root / PUBLISH_LOCK_PATH
    path.write_text(
        json.dumps(
            {
                "schema_version": "agency-publish-lock-v1",
                "owner_token": token,
                "pid": 2_000_000_000,
                "host": socket.gethostname(),
                "process_started": "definitely-not-live",
                "created_at": "2026-08-30T15:00:00Z",
                "operation": "apply",
                "receipt_fingerprint": "b" * 64,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_live_owner_cannot_be_cleared(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    with publish_operation_lock(root, operation="test") as owner:
        with pytest.raises(PublishLockError, match="lock_owner_alive"):
            clear_stale_publish_lock(
                root,
                owner_token=owner["owner_token"],
                confirmation=owner["owner_token"],
            )
        assert (root / PUBLISH_LOCK_PATH).exists()
        assert owner["pid"] == os.getpid()
    assert not (root / PUBLISH_LOCK_PATH).exists()


def test_stale_recovery_requires_exact_token_twice(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    path = _stale_lock(root)

    with pytest.raises(PublishLockError, match="lock_confirmation_mismatch"):
        clear_stale_publish_lock(
            root, owner_token="a" * 32, confirmation="c" * 32
        )

    assert path.exists()


def test_proven_dead_lock_is_cleared_without_portal_access(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    token = "a" * 32
    path = _stale_lock(root, token=token)

    owner = clear_stale_publish_lock(
        root, owner_token=token, confirmation=token
    )

    assert owner["operation"] == "apply"
    assert not path.exists()


def test_recovery_cannot_remove_a_new_lock_created_at_the_replace_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    stale_token = "a" * 32
    _stale_lock(root, token=stale_token)
    replace_entered = threading.Event()
    contender_attempted = threading.Event()
    contender_acquired = threading.Event()
    release_contender = threading.Event()
    contender_owner: dict[str, object] = {}
    original_replace = Path.replace

    def contend() -> None:
        assert replace_entered.wait(2)
        contender_attempted.set()
        with publish_operation_lock(root, operation="new-owner") as owner:
            contender_owner.update(owner)
            contender_acquired.set()
            assert release_contender.wait(2)

    contender = threading.Thread(target=contend)
    contender.start()

    def guarded_replace(path: Path, target: Path) -> Path:
        if path == root / PUBLISH_LOCK_PATH:
            replace_entered.set()
            assert contender_attempted.wait(2)
            assert not contender_acquired.is_set()
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", guarded_replace)
    cleared = clear_stale_publish_lock(
        root, owner_token=stale_token, confirmation=stale_token
    )

    assert cleared["owner_token"] == stale_token
    assert contender_acquired.wait(2)
    current = json.loads((root / PUBLISH_LOCK_PATH).read_text(encoding="utf-8"))
    assert current["owner_token"] == contender_owner["owner_token"]
    assert current["owner_token"] != stale_token
    assert (root / PUBLISH_GATE_PATH).is_file()
    release_contender.set()
    contender.join(2)
    assert not contender.is_alive()
    assert not (root / PUBLISH_LOCK_PATH).exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows byte-lock retry contract")
@pytest.mark.parametrize("contention_errno", [errno.EACCES, errno.EDEADLK])
def test_windows_gate_waits_past_msvcrt_builtin_retry_horizon(
    monkeypatch: pytest.MonkeyPatch,
    contention_errno: int,
) -> None:
    import msvcrt

    attempts = 0
    sleeps: list[float] = []

    def locking(descriptor: int, mode: int, count: int) -> None:
        nonlocal attempts
        assert descriptor == 123
        assert mode == msvcrt.LK_NBLCK
        assert count == 1
        attempts += 1
        if attempts <= 12:
            raise OSError(contention_errno, "gate is held")

    monkeypatch.setattr(msvcrt, "locking", locking)
    monkeypatch.setattr(publish_lock.time, "sleep", sleeps.append)
    monkeypatch.setattr(publish_lock.os, "lseek", lambda *args: 0)

    publish_lock._lock_windows_byte(123)

    assert attempts == 13
    assert sleeps == [0.05] * 12


@pytest.mark.skipif(os.name != "nt", reason="Windows byte-lock error contract")
def test_windows_gate_does_not_retry_undocumented_errno(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import msvcrt

    attempts = 0

    def locking(*args) -> None:
        nonlocal attempts
        attempts += 1
        raise OSError(errno.EAGAIN, "not documented lock contention")

    monkeypatch.setattr(msvcrt, "locking", locking)
    monkeypatch.setattr(
        publish_lock.time,
        "sleep",
        lambda delay: pytest.fail("unexpected retry sleep"),
    )
    monkeypatch.setattr(publish_lock.os, "lseek", lambda *args: 0)

    with pytest.raises(OSError) as captured:
        publish_lock._lock_windows_byte(123)

    assert captured.value.errno == errno.EAGAIN
    assert attempts == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows gate acquisition contract")
def test_windows_failed_gate_acquisition_skips_unlock_and_closes_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import msvcrt

    closed: list[int] = []
    original_close = os.close

    def fail_acquisition(descriptor: int) -> None:
        raise OSError(errno.EINVAL, "acquisition failed")

    monkeypatch.setattr(publish_lock, "_lock_windows_byte", fail_acquisition)
    monkeypatch.setattr(
        msvcrt,
        "locking",
        lambda *args: pytest.fail("unlock called without acquired gate"),
    )

    def close(descriptor: int) -> None:
        closed.append(descriptor)
        original_close(descriptor)

    monkeypatch.setattr(publish_lock.os, "close", close)

    with pytest.raises(OSError, match="acquisition failed") as captured:
        with publish_lock._authority_gate(tmp_path):
            pytest.fail("gate body ran after failed acquisition")

    assert captured.value.errno == errno.EINVAL
    assert len(closed) == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows gate cleanup contract")
def test_windows_gate_unlock_failure_still_closes_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import msvcrt

    closed: list[int] = []
    original_close = os.close

    monkeypatch.setattr(publish_lock, "_lock_windows_byte", lambda descriptor: None)
    monkeypatch.setattr(
        msvcrt,
        "locking",
        lambda *args: (_ for _ in ()).throw(OSError(errno.EBADF, "unlock failed")),
    )

    def close(descriptor: int) -> None:
        closed.append(descriptor)
        original_close(descriptor)

    monkeypatch.setattr(publish_lock.os, "close", close)

    with pytest.raises(OSError, match="unlock failed"):
        with publish_lock._authority_gate(tmp_path):
            pass

    assert len(closed) == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows gate cleanup contract")
def test_windows_gate_cleanup_does_not_mask_body_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import msvcrt

    closed: list[int] = []
    original_close = os.close

    monkeypatch.setattr(publish_lock, "_lock_windows_byte", lambda descriptor: None)
    monkeypatch.setattr(
        msvcrt,
        "locking",
        lambda *args: (_ for _ in ()).throw(OSError(errno.EBADF, "unlock failed")),
    )

    def close(descriptor: int) -> None:
        closed.append(descriptor)
        original_close(descriptor)

    monkeypatch.setattr(publish_lock.os, "close", close)

    with pytest.raises(RuntimeError, match="body failed") as captured:
        with publish_lock._authority_gate(tmp_path):
            raise RuntimeError("body failed")

    assert len(closed) == 1
    assert any("cleanup also failed" in note for note in captured.value.__notes__)


def test_publish_approval_uses_the_same_authority_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, client, portal = _publish_workspace(tmp_path)
    _patch_portal(monkeypatch, client, portal)
    prepare_project_publish(root)

    with publish_operation_lock(root, operation="test-contention"):
        with pytest.raises(ProjectApprovalError, match="publish_locked"):
            request_approval(
                root,
                gate=ApprovalGate.PUBLISH,
                requested_by="reviewer",
            )

    assert client.posts == []


def test_recover_lock_cli_requires_confirmation_and_reports_zero_portal_write(
    tmp_path: Path, runner
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    token = "a" * 32
    _stale_lock(root, token=token)

    result = runner.invoke(
        project,
        [
            "publish",
            "recover-lock",
            str(root),
            "--token",
            token,
            "--confirm-clear",
            token,
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "stale_lock_cleared"
    assert payload["portal_mutated"] is False
