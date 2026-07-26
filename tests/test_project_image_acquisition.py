"""Local raster/evidence acquisition tests for project image sources."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from vanjaro_cli.design.models import BreakpointName, SourceKind, Viewport
from vanjaro_cli.orchestration.image_acquisition import (
    ImageAcquisitionError,
    acquire_reference_image,
    resolve_evidence_file,
    validate_evidence_identity,
)
from vanjaro_cli.project import ProjectSource


def _source(reference: str, evidence: str | None = None) -> ProjectSource:
    return ProjectSource(
        id="image-1",
        kind=SourceKind.IMAGE,
        reference=reference,
        evidence_reference=evidence,
        page_reference="home",
        breakpoint=BreakpointName.DESKTOP,
        viewport=Viewport(width=1440, height=900),
    )


def _png(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0dIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
    )


def _jpeg(width: int, height: int) -> bytes:
    return (
        b"\xff\xd8\xff\xc0\x00\x11\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00\xff\xd9"
    )


def _webp(width: int, height: int) -> bytes:
    data = b"\x00\x00\x00\x00" + (width - 1).to_bytes(3, "little") + (
        height - 1
    ).to_bytes(3, "little")
    payload = b"WEBPVP8X" + len(data).to_bytes(4, "little") + data
    return b"RIFF" + len(payload).to_bytes(4, "little") + payload


@pytest.mark.parametrize(
    ("name", "payload", "mime"),
    [
        ("reference.png", _png(390, 844), "image/png"),
        ("reference.jpg", _jpeg(1440, 900), "image/jpeg"),
        ("reference.webp", _webp(768, 1024), "image/webp"),
    ],
)
def test_acquire_reference_image_dimensions_type_and_hash(
    tmp_path: Path, name: str, payload: bytes, mime: str
) -> None:
    path = tmp_path / "sources" / name
    path.parent.mkdir()
    path.write_bytes(payload)

    acquired = acquire_reference_image(tmp_path, _source(f"sources/{name}"))

    assert acquired.mime_type == mime
    assert acquired.width > 0 and acquired.height > 0
    assert acquired.relative_path == Path("sources") / name
    assert len(acquired.sha256) == 64


def test_acquire_rejects_signature_extension_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "sources" / "wrong.jpg"
    path.parent.mkdir()
    path.write_bytes(_png(10, 10))

    with pytest.raises(ImageAcquisitionError) as caught:
        acquire_reference_image(tmp_path, _source("sources/wrong.jpg"))

    assert caught.value.code == "image_extension_mismatch"


def test_acquire_rejects_remote_directory_and_workspace_escape(tmp_path: Path) -> None:
    with pytest.raises(ImageAcquisitionError) as remote:
        acquire_reference_image(tmp_path, _source("https://example.test/home.png"))
    assert remote.value.code == "remote_image_unsupported"

    directory = tmp_path / "sources" / "capture.png"
    directory.mkdir(parents=True)
    with pytest.raises(ImageAcquisitionError) as not_file:
        acquire_reference_image(tmp_path, _source("sources/capture.png"))
    assert not_file.value.code == "image_not_file"

    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(_png(1, 1))
    with pytest.raises(ImageAcquisitionError) as escaped:
        acquire_reference_image(tmp_path, _source(str(outside)))
    assert escaped.value.code == "image_outside_workspace"


def test_evidence_sidecar_is_optional_in_manifest_but_required_for_analysis(
    tmp_path: Path,
) -> None:
    with pytest.raises(ImageAcquisitionError) as missing:
        resolve_evidence_file(tmp_path, _source("sources/home.png"))
    assert missing.value.code == "image_evidence_missing"
    assert "--image-evidence image-1=" in missing.value.recommended_action

    sidecar = tmp_path / "sources" / "home.evidence.json"
    sidecar.parent.mkdir()
    sidecar.write_text("{}", encoding="utf-8")
    absolute, relative = resolve_evidence_file(
        tmp_path,
        _source("sources/home.png", "sources/home.evidence.json"),
    )
    assert absolute == sidecar
    assert relative == Path("sources/home.evidence.json")


def test_evidence_identity_reports_hash_and_dimension_mismatch(tmp_path: Path) -> None:
    image_path = tmp_path / "sources" / "home.png"
    image_path.parent.mkdir()
    image_path.write_bytes(_png(1440, 900))
    source = _source("sources/home.png")
    image = acquire_reference_image(tmp_path, source)
    ownership = {
        "page_slug": "home",
        "breakpoint": BreakpointName.DESKTOP,
        "viewport": Viewport(width=1440, height=900),
        "image_width": 1440,
        "image_height": 900,
    }
    wrong_hash = SimpleNamespace(
        observations=[SimpleNamespace(source_sha256="0" * 64, **ownership)]
    )
    with pytest.raises(ImageAcquisitionError) as hash_error:
        validate_evidence_identity(wrong_hash, source, image)
    assert hash_error.value.code == "image_evidence_hash_mismatch"

    wrong_dimensions = SimpleNamespace(
        observations=[
            SimpleNamespace(
                source_sha256=image.sha256,
                **{**ownership, "image_width": 720},
            )
        ]
    )
    with pytest.raises(ImageAcquisitionError) as dimension_error:
        validate_evidence_identity(wrong_dimensions, source, image)
    assert dimension_error.value.code == "image_evidence_dimension_mismatch"
