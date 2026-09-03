"""Repository-safe release evidence path and artifact validation."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import struct
from typing import Any
import zlib

from vanjaro_cli.release.gates import ReleaseVerificationError
from vanjaro_cli.release.models import ArtifactReference
from vanjaro_cli.reliability.artifacts import load_strict_json


def _verify_reference(
    root: Path, reference: ArtifactReference
) -> tuple[bool, str, Path | None]:
    unresolved = root / reference.path
    if _contains_link_or_reparse(unresolved):
        return False, "symlink", None
    path = _resolve_relative(root, reference.path)
    if path is None:
        return False, "path-escape", None
    if not path.is_file():
        return False, "artifact-unavailable", None
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return False, "artifact-unreadable", None
    if digest != reference.sha256:
        return False, "artifact-digest-mismatch", path
    return True, "artifact-current", path


def _resolve_repository_path(
    root: Path, relative: str, *, expected_type: str
) -> Path | None:
    """Resolve one lexical repository-relative path without links or escapes."""

    posix = PurePosixPath(relative)
    windows = PureWindowsPath(relative)
    if (
        not relative
        or posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or ".." in posix.parts
        or ".." in windows.parts
    ):
        return None
    candidate = root.joinpath(*posix.parts)
    if _contains_link_or_reparse(candidate):
        return None
    path = candidate.resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    if expected_type == "file" and not path.is_file():
        return None
    if expected_type == "directory" and not path.is_dir():
        return None
    if expected_type not in {"file", "directory"}:
        raise AssertionError(f"unknown expected path type: {expected_type}")
    return path


def _resolve_relative(root: Path, relative: str) -> Path | None:
    return _resolve_repository_path(root, relative, expected_type="file")


def _contains_link_or_reparse(candidate: Path) -> bool:
    """Reject links and Windows junctions in every existing lexical component."""

    absolute = candidate.expanduser().absolute()
    anchor = Path(absolute.anchor)
    current = anchor
    for part in absolute.parts[1:]:
        current = current / part
        try:
            metadata = os.lstat(current)
        except OSError:
            continue
        attributes = getattr(metadata, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if stat.S_ISLNK(metadata.st_mode) or (
            reparse_flag and attributes & reparse_flag
        ):
            return True
    return False


def _read_png_dimensions(path: Path) -> tuple[int, int]:
    """Validate the PNG chunk envelope and return the embedded IHDR dimensions."""

    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("capture is not a PNG")
    offset = 8
    dimensions: tuple[int, int] | None = None
    channels: int | None = None
    idat_payloads: list[bytes] = []
    saw_iend = False
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("truncated PNG chunk")
        payload = data[offset + 8 : offset + 8 + length]
        supplied_crc = struct.unpack(">I", data[offset + 8 + length : end])[0]
        if zlib.crc32(chunk_type + payload) & 0xFFFFFFFF != supplied_crc:
            raise ValueError("invalid PNG chunk CRC")
        if chunk_type == b"IHDR":
            if dimensions is not None or length != 13 or offset != 8:
                raise ValueError("invalid PNG IHDR")
            (
                width,
                height,
                bit_depth,
                color_type,
                compression,
                filtering,
                interlace,
            ) = struct.unpack(">IIBBBBB", payload)
            if (
                width <= 0
                or height <= 0
                or bit_depth != 8
                or color_type not in {0, 2, 3, 4, 6}
                or compression != 0
                or filtering != 0
                or interlace != 0
            ):
                raise ValueError("unsupported PNG IHDR")
            dimensions = (width, height)
            channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
        elif chunk_type == b"IDAT":
            idat_payloads.append(payload)
        elif chunk_type == b"IEND":
            if length != 0:
                raise ValueError("invalid PNG IEND")
            saw_iend = True
            offset = end
            break
        offset = end
    if (
        dimensions is None
        or channels is None
        or not idat_payloads
        or not saw_iend
        or offset != len(data)
    ):
        raise ValueError("incomplete PNG")
    width, height = dimensions
    try:
        pixels = zlib.decompress(b"".join(idat_payloads))
    except zlib.error as exc:
        raise ValueError("invalid PNG pixel stream") from exc
    row_size = 1 + width * channels
    if len(pixels) != height * row_size:
        raise ValueError("invalid PNG pixel stream length")
    if any(pixels[index] > 4 for index in range(0, len(pixels), row_size)):
        raise ValueError("invalid PNG row filter")
    return dimensions


def _json_object(path: Path) -> dict[str, Any]:
    value = load_strict_json(path)
    if not isinstance(value, dict):
        raise ReleaseVerificationError(f"JSON evidence must be an object: {path.name}")
    return value


__all__ = [
    "_contains_link_or_reparse",
    "_json_object",
    "_read_png_dimensions",
    "_resolve_repository_path",
    "_verify_reference",
]
