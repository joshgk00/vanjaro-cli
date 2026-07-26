"""Physical GrapesJS ownership contracts for semantic template fields.

The explicit map embedded in a template is authoritative.  Inference exists
only to bootstrap audited repository templates; runtime validation never
silently reconstructs a missing or drifting map.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping
import argparse
import json
from pathlib import Path
import re
from typing import Any

from vanjaro_cli.design.semantics import semantic_slot_types
from vanjaro_cli.utils.block_compose import enumerate_slots


_MULTIPLICITY: dict[str, int] = {
    "Cards/pricing-cards-3up.json:item.features": 3,
    "Content/contact-section.json:contact_items": 3,
    "Content/rich-text.json:body": 4,
    "Navigation/footer-3col.json:column.links": 6,
    "Navigation/footer-3col.json:contact_items": 6,
    "Navigation/footer-4col.json:column.links": 6,
    "Navigation/footer-4col.json:contact_items": 6,
}

_EXPLICIT: dict[str, dict[str, tuple[str, tuple[str, ...]]]] = {
    "Navigation/footer-3col.json": {
        "brand.title": ("heading", ("heading_1",)),
        "brand.body": ("text", ("text_1",)),
        "column.title": ("heading", ("heading_2",)),
        "column.links": (
            "list-item",
            tuple(f"list-item_{index}" for index in range(1, 7)),
        ),
        "contact_title": ("heading", ("heading_3",)),
        "contact_items": (
            "list-item",
            tuple(f"list-item_{index}" for index in range(7, 13)),
        ),
    },
    "Navigation/footer-4col.json": {
        "brand.title": ("heading", ("heading_1",)),
        "brand.body": ("text", ("text_1",)),
        "column.title": ("heading", ("heading_2", "heading_3")),
        "column.links": (
            "list-item",
            tuple(f"list-item_{index}" for index in range(1, 13)),
        ),
        "contact_title": ("heading", ("heading_4",)),
        "contact_items": (
            "list-item",
            tuple(f"list-item_{index}" for index in range(13, 19)),
        ),
    },
}


def primary_slots(template_component: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return independently owned slots, excluding paired alt/href attributes."""

    return tuple(
        slot
        for slot in enumerate_slots(dict(template_component))
        if not slot["key"].endswith(("_alt", "_href"))
    )


def infer_physical_fields(
    relative_path: str,
    template_component: Mapping[str, Any],
    fields: Mapping[str, str],
    repeat_default: int | None,
) -> dict[str, dict[str, Any]]:
    """Bootstrap an explicit map from audited field order and real slots.

    Ambiguous layouts have exact overrides above.  Any unaccounted slot or
    missing semantic type fails instead of being guessed.
    """

    if relative_path in _EXPLICIT:
        exact = _EXPLICIT[relative_path]
        if set(exact) != set(fields):
            raise ValueError(f"{relative_path}: explicit physical map fields drifted")
        return {
            field: _contract(
                field,
                slot_type,
                slots,
                repeat_default,
                _slots_per_owner(relative_path, field),
            )
            for field, (slot_type, slots) in exact.items()
        }

    queues: dict[str, deque[str]] = defaultdict(deque)
    for slot in primary_slots(template_component):
        if slot["key"] != "background_image":
            queues[slot["type"]].append(slot["key"])
    result: dict[str, dict[str, Any]] = {}
    section_fields = [
        field
        for field in fields
        if not _is_repeat(field) and field != "background_media"
    ]
    repeat_fields = [field for field in fields if _is_repeat(field)]
    for field in section_fields:
        result[field] = _allocate(
            relative_path, field, queues, owners=1, repeat_default=repeat_default
        )
    for _owner in range(repeat_default or 0):
        for field in repeat_fields:
            allocation = _allocate(
                relative_path, field, queues, owners=1, repeat_default=repeat_default
            )
            if field in result:
                result[field]["slots"].extend(allocation["slots"])
            else:
                result[field] = allocation
    if "background_media" in fields:
        result["background_media"] = _contract(
            "background_media", "section", ("background_image",), repeat_default, 1
        )
    leftovers = {
        slot_type: tuple(queue)
        for slot_type, queue in queues.items()
        if queue
    }
    if leftovers:
        raise ValueError(f"{relative_path}: unowned primary slots after inference: {leftovers}")
    return result


def validate_physical_contract(
    template_component: Any,
    capabilities: Any,
) -> tuple[str, ...]:
    """Validate exact ownership, type compatibility, and default cardinality."""

    if not isinstance(template_component, dict):
        return ("template must be an object for physical contract validation",)
    slots = primary_slots(template_component)
    inventory = {slot["key"]: slot for slot in slots}
    owned: dict[str, str] = {}
    issues: list[str] = []
    for field, contract in capabilities.physical_fields.items():
        accepted = semantic_slot_types(field)
        if accepted is None or contract.slot_type not in accepted:
            issues.append(
                f"physical field {field!r} slot_type {contract.slot_type!r} "
                f"is incompatible with semantic types {accepted}"
            )
        for key in contract.slots:
            slot = inventory.get(key)
            if slot is None:
                issues.append(f"physical field {field!r} owns missing slot {key!r}")
                continue
            if slot["type"] != contract.slot_type:
                issues.append(
                    f"physical field {field!r} declares {contract.slot_type!r} "
                    f"for {key!r}, whose actual type is {slot['type']!r}"
                )
            previous = owned.setdefault(key, field)
            if previous != field:
                issues.append(
                    f"physical slot {key!r} is owned by both {previous!r} and {field!r}"
                )
        owners = (
            capabilities.repeat_group.default
            if contract.owner == "repeat_item" and capabilities.repeat_group
            else 1
        )
        expected = owners * contract.slots_per_owner
        if len(contract.slots) != expected:
            issues.append(
                f"physical field {field!r} owns {len(contract.slots)} slots; "
                f"expected {expected} ({owners} owners x {contract.slots_per_owner})"
            )
    expected_owned = {
        slot["key"]
        for slot in slots
        if slot["key"] != "background_image" or "background_media" in capabilities.fields
    }
    missing_owners = sorted(expected_owned - set(owned))
    if missing_owners:
        issues.append(f"primary visitor-content slots have no semantic owner: {missing_owners}")
    unexpected = sorted(set(owned) - expected_owned)
    if unexpected:
        issues.append(f"semantic fields own non-primary slots: {unexpected}")
    repeat = capabilities.repeat_group
    if repeat and not repeat.expandable and repeat.maximum is not None:
        if repeat.maximum > repeat.default:
            issues.append(
                "non-expandable repeat maximum exceeds its physical default capacity"
            )
    return tuple(issues)


def write_repository_physical_contracts(templates_dir: Path) -> tuple[Path, ...]:
    """Add audited v1.1 physical maps without reformatting template trees."""

    written: list[Path] = []
    for path in sorted(templates_dir.rglob("*.json"), key=lambda item: item.as_posix()):
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        capabilities = data["capabilities"]
        repeat = capabilities.get("repeat_group")
        mapping = infer_physical_fields(
            path.relative_to(templates_dir).as_posix(),
            data["template"],
            capabilities["fields"],
            repeat["default"] if repeat else None,
        )
        if "physical_fields" in capabilities:
            if capabilities["physical_fields"] != mapping:
                raise ValueError(f"{path}: existing physical_fields drifted from audited inference")
            continue
        raw = raw.replace(
            '"schema_version": "1.0"',
            '"schema_version": "1.1"',
            1,
        )
        match = re.search(r'(?m)^(\s*)"responsive": \{', raw)
        if match is None:
            raise ValueError(f"{path}: cannot locate responsive insertion point")
        indent = match.group(1)
        marker = match.group(0)
        rendered = json.dumps(mapping, ensure_ascii=False, indent=2)
        lines = rendered.splitlines()
        block = indent + '"physical_fields": ' + lines[0] + "\n"
        block += "\n".join(indent + line for line in lines[1:]) + ",\n"
        path.write_text(raw.replace(marker, block + marker, 1), encoding="utf-8")
        written.append(path)
    return tuple(written)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--templates-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "artifacts" / "block-templates",
    )
    args = parser.parse_args(argv)
    if not args.write:
        parser.error("--write is required; inference is an explicit authoring operation")
    for path in write_repository_physical_contracts(args.templates_dir):
        print(path)
    return 0


def _allocate(
    relative_path: str,
    field: str,
    queues: dict[str, deque[str]],
    *,
    owners: int,
    repeat_default: int | None,
) -> dict[str, Any]:
    count = owners * _slots_per_owner(relative_path, field)
    candidates = semantic_slot_types(field)
    if not candidates:
        raise ValueError(f"{relative_path}: semantic field {field!r} has no slot vocabulary")
    slot_type = next(
        (candidate for candidate in candidates if len(queues[candidate]) >= count),
        None,
    )
    if slot_type is None:
        raise ValueError(
            f"{relative_path}: semantic field {field!r} has no executable slot capacity"
        )
    selected = tuple(queues[slot_type].popleft() for _ in range(count))
    return _contract(
        field,
        slot_type,
        selected,
        repeat_default,
        _slots_per_owner(relative_path, field),
    )


def _contract(
    field: str,
    slot_type: str,
    slots: tuple[str, ...],
    repeat_default: int | None,
    slots_per_owner: int,
) -> dict[str, Any]:
    return {
        "owner": "repeat_item" if _is_repeat(field) else "section",
        "slot_type": slot_type,
        "slots": list(slots),
        "slots_per_owner": slots_per_owner,
    }


def _slots_per_owner(relative_path: str, field: str) -> int:
    return _MULTIPLICITY.get(f"{relative_path}:{field}", 1)


def _is_repeat(field: str) -> bool:
    return field.startswith(("item.", "column."))


__all__ = [
    "infer_physical_fields",
    "primary_slots",
    "validate_physical_contract",
    "write_repository_physical_contracts",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
