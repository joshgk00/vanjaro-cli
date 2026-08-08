"""Tests for reading an image's intrinsic size from its own header."""

from __future__ import annotations

import struct
import zlib

from vanjaro_cli.utils.image_size import image_dimensions


def _png(width: int, height: int) -> bytes:
    header = struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    chunk = b"IHDR" + header
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", len(header))
        + chunk
        + struct.pack(">I", zlib.crc32(chunk))
    )


def _gif(width: int, height: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00" * 4


def _jpeg(width: int, height: int) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    sof0 = b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", height, width)
    return b"\xff\xd8" + app0 + sof0 + b"\x00" * 8


def test_a_png_reports_its_size() -> None:
    assert image_dimensions(_png(1440, 900)) == (1440, 900)


def test_a_gif_reports_its_size() -> None:
    assert image_dimensions(_gif(64, 48)) == (64, 48)


def test_a_jpeg_is_found_past_its_metadata() -> None:
    """A JPEG's size sits in a frame marker whose position depends on how much
    metadata precedes it, so there is no fixed offset to read."""

    assert image_dimensions(_jpeg(800, 600)) == (800, 600)


def test_an_svg_has_no_intrinsic_size_and_says_so() -> None:
    assert image_dimensions(b"<svg viewBox='0 0 10 10'></svg>") is None


def test_a_truncated_file_reports_nothing_rather_than_guessing() -> None:
    assert image_dimensions(_png(10, 10)[:12]) is None


def test_empty_bytes_report_nothing() -> None:
    assert image_dimensions(b"") is None
