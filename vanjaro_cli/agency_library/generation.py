"""Deterministic generator for the repository's governed agency pack."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from vanjaro_cli.agency_library.models import (
    AgencyPackManifest,
    PackPayloadReference,
    PackUpgradeRule,
    TemplateContract,
    TemplateLibraryPayload,
)
from vanjaro_cli.design.template_catalog import (
    TemplateCatalogEntry,
    load_template_catalog,
    load_template_data,
)


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_REGISTRY = _PROJECT_ROOT / "artifacts" / "agency-packs"
_PACK_NAME = "clicks-and-mortars"
_TEMPLATE_VERSION = "1.4.0"
_MODIFIER_VERSION = "1.0.0"
_PACK_VERSION = "1.4.0"
_HISTORICAL_DIGESTS = {
    "templates/1.0.0.json": "c4e1316345e4c275ae9fb99312a3c2014de1ce39781a547b6a2d8685f42c8a73",
    "modifiers/1.0.0.json": "331b7c14af6ae87ac9d04a6559ff9ae3ed4c252a21be80c6fa5159c1f720f087",
    "packs/1.0.0.json": "6fd9eff9da5767d088cfc462ec9925fef3d16168b4c060f6cd83e99efc88b225",
    "packs/1.0.1.json": "4fb2524b0ff1489381e59807831cb26318c903232c3789422027f500c7806f6a",
    "templates/1.1.0.json": "10214b4da51feeabdccac7e4257a829e9750ed3692381a356cde7694fba76ebf",
    "packs/1.1.0.json": "4b7f293560e30839cecc1f680f46ef0e37b5c197dab1a0adec489a97698d7893",
    "templates/1.2.0.json": "3999dc0f9ec3848b150fc11738269b4062818a42dc5390626ce769105da8cd40",
    "packs/1.2.0.json": "88a092ce6413f0197b0f16aafd311539252fe699453ffb19df114e29c6b6c86a",
    "packs/1.3.0.json": "e41111c7e6bd3d1bb84051489e8ede5536b789579529123872c6e80467938e2e",
    "templates/1.3.0.json": "50c3251ba82f73d40b954ddda9802291075e3b00e996d2ce079d777c5dcd0fe1",
}
_AUDITED_EXECUTABLE_DIGESTS = {
    "CTAs/cta-banner": "f1af9e60b5086e510411ac5548097bdcfc5530ee1d474caa55cb04f3c2fe3028",
    "CTAs/cta-split": "9a951ccf72d010820d9786cea8a03ae0f6ce816ef8b92095fc87b845c45372e5",
    "Cards/blog-post-cards-3up": "cffaad2e72b57141fedf16dab66348b9e8c574950a6852b7bbef64b3df935c71",
    "Cards/blog-post-cards-4up": "21e493ed02959946206a38e1de9b01d51664dda61bc171d185da50f3e6047761",
    "Cards/class-photo-cards-4up": "5ee0813e8e8ddc04e7aeb431910ebbd56965f1128eca518c774dbe1a8bd926d3",
    "Cards/feature-cards-3up": "3b3f799f7fc069f41f983f88cd6fb87409d00605b4cc033c66f43d2b97409acd",
    "Cards/feature-cards-4up": "5917950d191a1e3611393e3950492275e018f3c37ae62e6839f27c60a5bd3ae2",
    "Cards/gallery-3up": "949c1d7115e174518e75a74cde8665ec9dd071f61c6e463b6071714d9a53c109",
    "Cards/gallery-6up": "ed9d0cb2eba475cb071d917bea66e0685cf23e8e3acfd0db10b56ef941c26124",
    "Cards/pricing-cards-3up": "1a72cee2023bd6d5425faf789901d2b71e835ac96012a4622ea11d057b56a9ab",
    "Cards/team-member-grid-4up": "8d5bce9db723a1b0c3c2449f21294147b7b2c2103eae05916a93577091711b44",
    "Cards/testimonial-cards-3up": "fc77c2f35858d7f318027229d96dfb4727cfefa926260fb0338503ee4b45c206",
    "Content/bio-about": "4b34b25e232ce389b849b7268c2c378d503bb812a59482b03853e044be71424c",
    "Content/contact-section": "8ffe981b00ea04e6bb41925c7bb34c9a1dfd05ead5e22764aa947d3379802eb9",
    "Content/faq-accordion": "4e1874ebe907248daa8e0254e99f94550f85b7905a2950cd06e7dfe83d2addfe",
    "Content/logo-bar": "c3668e1828832aa2f5347b30c87fd5a019746b9836398b4dd9e695cfb3c1af95",
    "Content/ribbon-marquee": "3f1f833c30ab8e3ac9bce73654b4bafe259674677cc0d790d2f3d07af671a9a0",
    "Content/rich-text": "4af781b10e213f737e970bcba13a5a2b0ad810c7d96e9d3bf732dd167905ab1b",
    "Content/split-media": "49a66bbe5547189b2061abda52affaaaf4228dce6d64ab7edc0e370ef372ec8c",
    "Content/split-media-reverse": "6f8749863687410be0a6106a564a8817bc99e2ab01ab013e23145ce655726ceb",
    "Content/stats-band-3up": "4fd51ee2a3fdb665b418bef9785c7d854fba5ebbe2ebf3427b86e32ae33fe6f7",
    "Content/stats-grid-4up": "495a34d9c4d74c0ef65e8791661a22a2209522f6f3f999f0c6d3b25e97af7745",
    "Content/video-feature": "f67a7bb542e705ab2da6838e53111c85fa7cff4411cd1b96234ae72337bdcd72",
    "Heroes/centered-hero": "e523ecda49c5a3cb0fd43013ab0a2298d0fdaa44e50878154ea89ec55bbecaaa",
    "Heroes/photo-band": "e86fd5ed8de34657254283eef73177007c3e1d2c505c7a556692bd5a0f5bc910",
    "Heroes/split-hero": "2a8f8bc85e0fa2519641c270aac3940cee10345397bb421b3601c2b0514a46e6",
    "Lists/icon-feature-list": "e1749c56d50da2ecd0bc29f01e1ab92ac8e87985dab1d32e30642ef388aae3b7",
    "Navigation/footer-3col": "3a136c0341de8406a4c5a49c41c646a8b37fcdd2243e4ecf1e73908f2bc1e5ec",
    "Navigation/footer-4col": "d08141a70fd7756668d187e6a469a071f7ad587d7fa3177a5bedecf61305c9c1",
    "Navigation/navbar-brand-links": "8cbc596fa0fb8bf624c991d5b2c9650afca8c08d6429f46ae0ead9b22b414bfd",
    "Navigation/navbar-brand-links-cta": "abcdb46ee27f6ffd6642e8c3d4747e2c025ff3c07a736d517f6c4205ecf49e0f",
}
_REVIEWED_EXECUTABLE_CHANGES = (
    "Cards/gallery-3up",
    "Cards/gallery-6up",
    "Lists/icon-feature-list",
)
_CURRENT_RELEASE_DIGESTS = {
    "templates/1.4.0.json": "b9a32bb8c35eb87d3d45d45f034282bcb1f893738df6bdc80530bc029bbcfc91",
    "packs/1.4.0.json": "8d48806b62a7b87583b5737f4f8f526a906a1b04aeb47a228b8f7e319e963d53",
}


def render_repository_pack_artifacts(
    *,
    registry_root: Path = _DEFAULT_REGISTRY,
) -> dict[Path, bytes]:
    """Render only the current release; published history is never rebuilt."""

    catalog = load_template_catalog()
    _verify_audited_executable_catalog(catalog)
    templates = TemplateLibraryPayload(
        version=_TEMPLATE_VERSION,
        capability_schema_version="1.1",
        templates=tuple(
            TemplateContract(
                template_id=entry.template_id,
                template_sha256=_canonical_sha256(load_template_data(entry)),
                capability_sha256=_canonical_sha256(
                    entry.capabilities.model_dump(mode="json")
                ),
            )
            for entry in catalog
        ),
    )
    template_bytes = _render_model(templates)
    family = registry_root / _PACK_NAME
    template_path = family / "templates" / f"{_TEMPLATE_VERSION}.json"
    template_reference = PackPayloadReference(
        version=_TEMPLATE_VERSION,
        path=f"templates/{_TEMPLATE_VERSION}.json",
        sha256=hashlib.sha256(template_bytes).hexdigest(),
    )
    modifier_reference = PackPayloadReference(
        version=_MODIFIER_VERSION,
        path=f"modifiers/{_MODIFIER_VERSION}.json",
        sha256=_HISTORICAL_DIGESTS["modifiers/1.0.0.json"],
    )
    compatible_changes = tuple(entry.template_id for entry in catalog)
    physical_contract_release = AgencyPackManifest(
        name=_PACK_NAME,
        version=_PACK_VERSION,
        templates=template_reference,
        modifiers=modifier_reference,
        upgrade_rules=tuple(
            PackUpgradeRule(
                from_version=from_version,
                compatible_capability_schema_change=True,
                compatible_template_changes=compatible_changes,
                notes=(
                    "Adds validated physical slot ownership and cardinality metadata for all templates.",
                    "Reviewed executable fixes are limited to gallery placeholder copy and icon-list mobile columns: "
                    + ", ".join(_REVIEWED_EXECUTABLE_CHANGES),
                ),
            )
            for from_version in ("1.0.0", "1.0.1")
        ),
    )
    rendered = {
        template_path: template_bytes,
        family / "packs" / f"{_PACK_VERSION}.json": _render_model(
            physical_contract_release
        ),
    }
    for path, payload in rendered.items():
        relative = path.relative_to(family).as_posix()
        if hashlib.sha256(payload).hexdigest() != _CURRENT_RELEASE_DIGESTS[relative]:
            raise ValueError(
                f"published agency-pack release content drifted for {relative}; bump the version"
            )
    return rendered


def write_repository_pack_artifacts(
    *,
    registry_root: Path = _DEFAULT_REGISTRY,
) -> tuple[Path, ...]:
    rendered = render_repository_pack_artifacts(registry_root=registry_root)
    for path, payload in rendered.items():
        if path.exists():
            if path.read_bytes() != payload:
                raise ValueError(
                    f"refusing to rewrite published agency-pack version at {path}; bump the version"
                )
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(payload)
        temporary.replace(path)
    return tuple(rendered)


def _verify_audited_executable_catalog(
    catalog: tuple[TemplateCatalogEntry, ...],
) -> None:
    identifiers = {entry.template_id for entry in catalog}
    expected = set(_AUDITED_EXECUTABLE_DIGESTS)
    if identifiers != expected:
        raise ValueError(
            "audited executable template IDs drifted; publish a new agency-pack version"
        )
    for entry in catalog:
        data = load_template_data(entry)
        actual = _canonical_sha256(
            {"template": data["template"], "styles": data["styles"]}
        )
        expected_digest = _AUDITED_EXECUTABLE_DIGESTS[entry.template_id]
        if actual != expected_digest:
            raise ValueError(
                f"executable template drifted for {entry.template_id}; bump the agency-pack version"
            )


def check_repository_pack_artifacts(
    *,
    registry_root: Path = _DEFAULT_REGISTRY,
) -> tuple[str, ...]:
    drift: list[str] = []
    family = registry_root / _PACK_NAME
    for relative_path, expected_digest in _HISTORICAL_DIGESTS.items():
        path = family / relative_path
        try:
            actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            drift.append(f"missing immutable agency-pack artifact: {path}")
            continue
        if actual_digest != expected_digest:
            drift.append(f"immutable agency-pack artifact digest drifted: {path}")
    for path, expected in render_repository_pack_artifacts(
        registry_root=registry_root
    ).items():
        try:
            actual = path.read_bytes()
        except OSError:
            drift.append(f"missing generated agency-pack artifact: {path}")
            continue
        if actual != expected:
            drift.append(f"generated agency-pack artifact is stale: {path}")
    return tuple(drift)


def _render_model(value: object) -> bytes:
    payload = value.model_dump(mode="json")  # type: ignore[attr-defined]
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the governed agency pack.")
    parser.add_argument("--write", action="store_true", help="Write generated artifacts.")
    args = parser.parse_args(argv)
    if args.write:
        for path in write_repository_pack_artifacts():
            print(f"Wrote {path}")
        return 0
    drift = check_repository_pack_artifacts()
    for issue in drift:
        print(issue)
    return 1 if drift else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())


__all__ = [
    "check_repository_pack_artifacts",
    "render_repository_pack_artifacts",
    "write_repository_pack_artifacts",
]
