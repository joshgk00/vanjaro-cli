"""Intrinsic pixel size read from an image's own header."""

from __future__ import annotations

import struct

__all__ = ["image_dimensions"]


def _png(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    if data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _gif(data: bytes) -> tuple[int, int] | None:
    if len(data) < 10 or not data.startswith((b"GIF87a", b"GIF89a")):
        return None
    width, height = struct.unpack("<HH", data[6:10])
    return width, height


def _webp(data: bytes) -> tuple[int, int] | None:
    if len(data) < 30 or not data.startswith(b"RIFF") or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    if chunk == b"VP8 ":
        width, height = struct.unpack("<HH", data[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if chunk == b"VP8L":
        bits = struct.unpack("<I", data[21:25])[0]
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8X":
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    return None


def _jpeg(data: bytes) -> tuple[int, int] | None:
    """Walk JPEG segments to the frame header that carries the size.

    A JPEG's dimensions live in a start-of-frame marker whose position depends
    on how much metadata precedes it, so unlike the other formats there is no
    fixed offset to read.
    """

    if not data.startswith(b"\xff\xd8"):
        return None
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        length = int.from_bytes(data[index + 2 : index + 4], "big")
        # Start-of-frame markers, excluding the four that carry no frame.
        if 0xC0 <= marker <= 0xCF and marker not in {0xC4, 0xC8, 0xCC}:
            height, width = struct.unpack(">HH", data[index + 5 : index + 9])
            return width, height
        if length <= 0:
            return None
        index += 2 + length
    return None


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Return an image's intrinsic size, or None when it has none to read.

    The media fidelity dimension needs an aspect ratio, and an aspect ratio
    needs the image's own width and height — so without this, media scored
    nothing on every site even when every picture had been downloaded.

    Read from the header rather than by decoding: only the first few bytes are
    needed, and the alternative is a dependency for something four struct
    unpacks handle. An SVG has no intrinsic pixel size at all, so it honestly
    returns nothing rather than a guess.
    """

    for reader in (_png, _gif, _webp, _jpeg):
        size = reader(data)
        if size and size[0] > 0 and size[1] > 0:
            return size
    return None
