"""Cross-process lock and guarded stale-lock recovery for publication authority."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
import ctypes
import errno
import json
import os
from pathlib import Path
import socket
import sys
import time
import uuid
from typing import Any

from vanjaro_cli.reliability.contracts import PUBLISH_LOCK_SCHEMA
from vanjaro_cli.reliability.artifacts import ArtifactContractError, load_strict_json


PUBLISH_LOCK_PATH = Path(".project-publish.lock")
PUBLISH_GATE_PATH = Path(".project-publish.gate")


class PublishLockError(ValueError):
    """A live, malformed, or ambiguously stale publication lock."""

    def __init__(self, code: str, message: str, recommended_action: str) -> None:
        self.code = code
        self.message = message
        self.recommended_action = recommended_action
        super().__init__(f"[{code}] {message} Recommended action: {recommended_action}")


@contextmanager
def publish_operation_lock(
    root: Path,
    *,
    operation: str,
    receipt_fingerprint: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Own the project publication authority lock for one bounded operation."""

    workspace = root.expanduser().resolve()
    path = workspace / PUBLISH_LOCK_PATH
    owner = {
        "schema_version": PUBLISH_LOCK_SCHEMA,
        "owner_token": uuid.uuid4().hex,
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "process_started": _process_started(os.getpid()),
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "operation": operation,
        "receipt_fingerprint": receipt_fingerprint,
    }
    descriptor: int | None = None
    with _authority_gate(workspace):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            existing = _read_lock(path)
            token = existing.get("owner_token", "unknown")
            raise PublishLockError(
                "publish_locked",
                "another publication operation owns the workspace lock "
                f"(operation={existing.get('operation', 'unknown')}, token={token})",
                "Wait for it to finish. If it crashed, inspect the journal and run "
                "`vanjaro project publish recover-lock --token TOKEN --confirm-clear TOKEN`.",
            ) from exc
        try:
            raw = _json_text(owner).encode("utf-8")
            offset = 0
            while offset < len(raw):
                offset += os.write(descriptor, raw[offset:])
            os.fsync(descriptor)
        except Exception:
            os.close(descriptor)
            descriptor = None
            path.unlink(missing_ok=True)
            raise
    try:
        yield owner
    finally:
        if descriptor is not None:
            os.close(descriptor)
        with _authority_gate(workspace):
            try:
                current = _read_lock(path)
            except PublishLockError:
                current = None
            if current is not None and current.get("owner_token") == owner["owner_token"]:
                path.unlink(missing_ok=True)


def inspect_publish_lock(root: Path) -> dict[str, Any]:
    """Return strict, non-secret lock ownership evidence."""

    return _read_lock(root.expanduser().resolve() / PUBLISH_LOCK_PATH)


def clear_stale_publish_lock(
    root: Path,
    *,
    owner_token: str,
    confirmation: str,
) -> dict[str, Any]:
    """Clear only an exact lock whose recorded process instance is proven dead."""

    workspace = root.expanduser().resolve()
    path = workspace / PUBLISH_LOCK_PATH
    with _authority_gate(workspace):
        owner = _read_lock(path)
        expected = owner.get("owner_token")
        if not owner_token or owner_token != expected or confirmation != expected:
            raise PublishLockError(
                "lock_confirmation_mismatch",
                "lock token and action-time confirmation must match the current owner token",
                "Inspect the current lock and repeat with its exact token twice.",
            )
        if owner.get("host") != socket.gethostname():
            raise PublishLockError(
                "lock_host_ambiguous",
                "the lock belongs to a different host and liveness cannot be proven locally",
                "Confirm the other host is offline before performing a supervised recovery.",
            )
        pid = owner.get("pid")
        started = owner.get("process_started")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
            raise PublishLockError(
                "lock_invalid", "the lock PID is invalid", "Preserve the file for manual review."
            )
        live_started = _process_started(pid)
        if live_started is not None and (started is None or live_started == started):
            raise PublishLockError(
                "lock_owner_alive",
                f"process {pid} still matches the recorded lock owner",
                "Wait for the active publication operation to finish.",
            )
        if live_started is None and _process_exists(pid) is not False:
            raise PublishLockError(
                "lock_liveness_ambiguous",
                f"cannot prove that process {pid} is no longer running",
                "Do not clear the lock until process liveness can be verified.",
            )
        # All normal lock acquisition and recovery holds this gate. Re-read the
        # exact owner immediately before replacement so an out-of-band writer
        # cannot turn stale-owner evidence into authority over a newer lock.
        if _read_lock(path) != owner:
            raise PublishLockError(
                "lock_changed", "the lock changed during recovery", "Inspect the current lock again."
            )
        tombstone = path.with_name(f".{path.name}.{owner_token}.cleared")
        try:
            path.replace(tombstone)
        except FileNotFoundError as exc:
            raise PublishLockError(
                "lock_changed", "the lock changed during recovery", "Inspect the current lock again."
            ) from exc
        tombstone.unlink(missing_ok=True)
    return owner


@contextmanager
def _authority_gate(workspace: Path) -> Iterator[None]:
    """Serialize lock creation and recovery across processes.

    The gate file is intentionally persistent. OS advisory locks disappear when
    a process exits, so a crash cannot strand this second-level authority gate.
    """

    path = workspace / PUBLISH_GATE_PATH
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    windows = os.name == "nt"
    locked = False
    try:
        if windows:
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            _lock_windows_byte(descriptor)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
        locked = True
        yield
    finally:
        active_error = sys.exc_info()[1]
        cleanup_error: BaseException | None = None
        try:
            if locked:
                if windows:
                    import msvcrt

                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_UN)
        except BaseException as exc:
            cleanup_error = exc
        try:
            os.close(descriptor)
        except BaseException as exc:
            if cleanup_error is None:
                cleanup_error = exc
        if cleanup_error is not None:
            if active_error is None:
                raise cleanup_error
            if hasattr(active_error, "add_note"):
                active_error.add_note(
                    f"authority-gate cleanup also failed: {type(cleanup_error).__name__}"
                )


def _lock_windows_byte(descriptor: int) -> None:
    """Wait indefinitely for the one-byte Windows authority gate.

    ``LK_LOCK`` itself gives up after ten one-second retries. A nonblocking
    attempt with an explicit contention-only loop preserves the gate's true
    serialization contract while still surfacing unexpected OS failures.
    """

    import msvcrt

    contention = {errno.EACCES, errno.EDEADLK}
    if hasattr(errno, "EDEADLOCK"):
        contention.add(errno.EDEADLOCK)
    while True:
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            return
        except OSError as exc:
            if exc.errno not in contention:
                raise
            time.sleep(0.05)


def _read_lock(path: Path) -> dict[str, Any]:
    try:
        value = load_strict_json(path)
    except ArtifactContractError as exc:
        if not path.exists():
            raise PublishLockError(
                "lock_missing", "no publication lock exists", "No lock recovery is required."
            ) from exc
        raise PublishLockError(
            "lock_invalid", f"publication lock is unreadable: {exc}", "Preserve it for manual review."
        ) from exc
    if not isinstance(value, dict) or value.get("schema_version") != PUBLISH_LOCK_SCHEMA:
        raise PublishLockError(
            "lock_invalid", "publication lock schema is invalid", "Preserve it for manual review."
        )
    token = value.get("owner_token")
    if not isinstance(token, str) or len(token) != 32:
        raise PublishLockError(
            "lock_invalid", "publication lock owner token is invalid", "Preserve it for manual review."
        )
    return value


def _process_exists(pid: int) -> bool | None:
    if os.name == "nt":
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        error = ctypes.windll.kernel32.GetLastError()
        if error == 87:
            return False
        if error == 5:
            return True
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        if exc.errno == errno.EPERM:
            return True
        return None
    return True


def _process_started(pid: int) -> str | None:
    if os.name == "nt":
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            creation = ctypes.c_ulonglong()
            exit_time = ctypes.c_ulonglong()
            kernel = ctypes.c_ulonglong()
            user = ctypes.c_ulonglong()
            ok = ctypes.windll.kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel),
                ctypes.byref(user),
            )
            return str(creation.value) if ok else None
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    stat = Path(f"/proc/{pid}/stat")
    try:
        fields = stat.read_text(encoding="utf-8").split()
    except OSError:
        return None
    return fields[21] if len(fields) > 21 else None


def _json_text(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"


__all__ = [
    "PUBLISH_GATE_PATH",
    "PUBLISH_LOCK_PATH",
    "PublishLockError",
    "clear_stale_publish_lock",
    "inspect_publish_lock",
    "publish_operation_lock",
]
