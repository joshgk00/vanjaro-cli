"""Filesystem registry for immutable, digest-verified agency packs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from vanjaro_cli.agency_library.models import (
    AgencyPackManifest,
    ModifierLibraryPayload,
    PackPayloadReference,
    TemplateLibraryPayload,
)
from vanjaro_cli.agency_library.style_payload import AgencyStylePayload
from vanjaro_cli.utils.semver import validate_semver


_PACK_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_Payload = TypeVar("_Payload", bound=BaseModel)


class AgencyPackRegistryError(ValueError):
    """Categorized pack discovery or integrity failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        recommended_action: str,
    ) -> None:
        self.code = code
        self.recommended_action = recommended_action
        super().__init__(message)

    def as_dict(self) -> dict[str, str]:
        return {
            "category": self.code,
            "message": str(self),
            "recommended_action": self.recommended_action,
        }


@dataclass(frozen=True, slots=True)
class ResolvedAgencyPack:
    manifest: AgencyPackManifest
    templates: TemplateLibraryPayload
    modifiers: ModifierLibraryPayload
    manifest_path: Path
    digest: str
    # Additive and optional: absent for every schema_version 1.0 pack and for
    # any 1.1 pack that opted out, so existing keyword-argument callers built
    # before styles existed are unaffected.
    styles: AgencyStylePayload | None = None


class AgencyPackRegistry:
    """Resolve named/versioned packs without ambient template-directory state."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    def resolve(self, name: str, version: str) -> ResolvedAgencyPack:
        normalized_name = name.strip()
        if not _PACK_NAME.fullmatch(normalized_name):
            raise AgencyPackRegistryError(
                "agency_pack_name_invalid",
                f"invalid agency pack name: {name!r}",
                recommended_action="Use the lowercase pack name declared by the agency registry.",
            )
        try:
            normalized_version = validate_semver(version)
        except ValueError as exc:
            raise AgencyPackRegistryError(
                "agency_pack_version_invalid",
                str(exc),
                recommended_action="Use a published Semantic Version 2.0 pack version.",
            ) from exc
        manifest_path = (
            self.root / normalized_name / "packs" / f"{normalized_version}.json"
        ).resolve()
        try:
            manifest_path.relative_to(self.root)
        except ValueError as exc:
            raise AgencyPackRegistryError(
                "agency_pack_manifest_outside_registry",
                "agency pack manifest resolves outside the configured registry",
                recommended_action="Remove the escaping link and publish the pack inside the registry.",
            ) from exc
        if not manifest_path.is_file():
            raise AgencyPackRegistryError(
                "agency_pack_not_found",
                f"agency pack {normalized_name}@{normalized_version} was not found",
                recommended_action=(
                    "Install or publish the requested pack in the configured agency-pack registry."
                ),
            )
        manifest = _read_model(
            manifest_path,
            AgencyPackManifest,
            code="agency_pack_manifest_invalid",
        )
        if manifest.name != normalized_name or manifest.version != normalized_version:
            raise AgencyPackRegistryError(
                "agency_pack_identity_mismatch",
                f"pack path identifies {normalized_name}@{normalized_version}, but the manifest "
                f"declares {manifest.name}@{manifest.version}",
                recommended_action="Move or republish the pack under its declared identity.",
            )
        family_root = (self.root / normalized_name).resolve()
        templates = self._read_payload(
            family_root,
            manifest.templates,
            TemplateLibraryPayload,
            label="template",
        )
        modifiers = self._read_payload(
            family_root,
            manifest.modifiers,
            ModifierLibraryPayload,
            label="modifier",
        )
        styles = (
            self._read_payload(
                family_root,
                manifest.styles,
                AgencyStylePayload,
                label="style",
            )
            if manifest.styles is not None
            else None
        )
        digest = _canonical_sha256(manifest.model_dump(mode="json"))
        return ResolvedAgencyPack(
            manifest=manifest,
            templates=templates,
            modifiers=modifiers,
            manifest_path=manifest_path,
            digest=digest,
            styles=styles,
        )

    def _read_payload(
        self,
        family_root: Path,
        reference: PackPayloadReference,
        model: type[_Payload],
        *,
        label: str,
    ) -> _Payload:
        path = (family_root / reference.path).resolve()
        try:
            path.relative_to(family_root)
        except ValueError as exc:
            raise AgencyPackRegistryError(
                "agency_pack_payload_outside_registry",
                f"{label} payload escapes the pack family: {reference.path}",
                recommended_action="Use a payload path under the named pack directory.",
            ) from exc
        if not path.is_file():
            raise AgencyPackRegistryError(
                "agency_pack_payload_missing",
                f"{label} payload does not exist: {reference.path}",
                recommended_action="Publish the referenced payload and retry.",
            )
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise AgencyPackRegistryError(
                "agency_pack_payload_read_failed",
                f"cannot read {label} payload {reference.path}: {exc}",
                recommended_action="Check registry file permissions and retry.",
            ) from exc
        actual = hashlib.sha256(raw).hexdigest()
        if actual != reference.sha256:
            raise AgencyPackRegistryError(
                "agency_pack_payload_digest_mismatch",
                f"{label} payload digest differs from the immutable pack manifest",
                recommended_action="Restore the published payload or publish a new pack version.",
            )
        payload = _validate_bytes(
            raw,
            model,
            path,
            code="agency_pack_payload_invalid",
        )
        if payload.version != reference.version:
            raise AgencyPackRegistryError(
                "agency_pack_payload_version_mismatch",
                f"{label} payload declares {payload.version}, expected {reference.version}",
                recommended_action="Correct the payload reference or publish a new pack version.",
            )
        return payload


def _read_model(path: Path, model: type[_Payload], *, code: str) -> _Payload:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AgencyPackRegistryError(
            code,
            f"cannot read agency pack file {path}: {exc}",
            recommended_action="Check the registry file and permissions.",
        ) from exc
    return _validate_bytes(raw, model, path, code=code)


def _validate_bytes(
    raw: bytes,
    model: type[_Payload],
    path: Path,
    *,
    code: str,
) -> _Payload:
    try:
        return model.model_validate_json(raw)
    except ValidationError as exc:
        raise AgencyPackRegistryError(
            code,
            f"invalid agency pack file {path}: {exc}",
            recommended_action="Regenerate and republish the strict pack artifact.",
        ) from exc


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "AgencyPackRegistry",
    "AgencyPackRegistryError",
    "ResolvedAgencyPack",
]
