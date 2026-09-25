"""Block template resolution, slot enumeration, and content override application."""

from __future__ import annotations

import copy
import json
import os
import re
import uuid
from pathlib import Path
from typing import Generator
from urllib.parse import urlsplit

from vanjaro_cli.utils.color import parse_color
from vanjaro_cli.utils.image_links import (
    apply_image_link,
    collect_component_ids,
    is_generated_image_link_wrapper,
    is_image_link_wrapper,
)
from vanjaro_cli.utils.theme_palette import nearest_palette_slot

__all__ = [
    "TemplateNotFoundError",
    "apply_overrides",
    "apply_overrides_with_owners",
    "apply_section_background",
    "attach_form_placeholder",
    "check_overflow",
    "enumerate_slots",
    "expand_button_slots",
    "expand_column_units",
    "expand_heading_slots",
    "expand_image_slots",
    "expand_list_slots",
    "expand_text_slots",
    "find_template",
    "get_templates_dir",
    "parse_color",
    "promote_background_images",
    "prune_unfilled_images",
]

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_TEMPLATES_DIR = _PACKAGE_ROOT / "artifacts" / "block-templates"

# Component types whose `content` field can be overridden
CONTENT_TYPES = frozenset({"heading", "text", "button", "link", "list-item"})

# Component types with overridable attributes beyond content
ATTRIBUTE_SLOTS: dict[str, list[tuple[str, str]]] = {
    "button": [("href", "href")],
    "link": [("href", "href")],
    "image": [("src", "src"), ("alt", "alt")],
}


class TemplateNotFoundError(Exception):
    """Raised when a template name doesn't match any file in the library."""

    def __init__(self, name: str, available: list[str]) -> None:
        self.name = name
        self.available = available
        available_str = ", ".join(available) if available else "none found"
        super().__init__(f"Template '{name}' not found. Available: {available_str}")


def get_templates_dir() -> Path:
    """Return the block templates directory, checking env var override first."""
    override = os.environ.get("VANJARO_TEMPLATES_DIR")
    if override:
        return Path(override)
    return _DEFAULT_TEMPLATES_DIR


def find_template(name: str, templates_dir: Path | None = None) -> dict:
    """Find and load a template by name (case-insensitive exact match).

    Raises TemplateNotFoundError with a list of available names if not found.
    """
    if templates_dir is None:
        templates_dir = get_templates_dir()
    if not templates_dir.is_dir():
        raise TemplateNotFoundError(name, [])

    available: list[str] = []
    for json_file in sorted(templates_dir.rglob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        tpl_name = data.get("name", json_file.stem)
        if tpl_name.lower() == name.lower():
            return data
        available.append(tpl_name)

    raise TemplateNotFoundError(name, available)


def _walk_overridable(
    component: dict,
    counters: dict[str, int] | None = None,
) -> Generator[tuple[dict, str, int], None, None]:
    """Yield (component, type, index) for each overridable component in document order.

    Counters are per-type and 1-based, shared across the entire tree walk.
    Every ``link``/``button`` counts here regardless of content shape --
    wraps a single image, wraps text, or is a bare authored placeholder --
    with one exception: a link this code itself generated as an image's
    ``image_N_href`` destination wrapper (see
    ``image_links.is_generated_image_link_wrapper``) is never counted or
    yielded. Such a wrapper is addressed only through its owning image's
    ``image_N_href`` slot; letting it also consume a ``link_N`` slot would
    make that numbering drift across repeated composition rounds as wrappers
    come and go. An authored link that merely has the same content-free,
    single-image shape is not mistaken for one of ours: only an explicit
    creation marker excludes a wrapper, so an unmarked authored link keeps
    its ordinary ``link_N``/``link_N_href`` slot.
    """
    if counters is None:
        counters = {}

    comp_type = component.get("type", "")
    if comp_type in CONTENT_TYPES or comp_type in ATTRIBUTE_SLOTS:
        if not (comp_type == "link" and is_generated_image_link_wrapper(component)):
            counters[comp_type] = counters.get(comp_type, 0) + 1
            yield component, comp_type, counters[comp_type]

    for child in component.get("components", []):
        yield from _walk_overridable(child, counters)


def _current_image_href(image: dict, ancestors: list[dict]) -> str:
    """The href an image's native owner currently carries, or "" if unlinked."""
    if not ancestors:
        return ""
    parent = ancestors[-1]
    if is_image_link_wrapper(parent) and parent.get("components", [None])[0] is image:
        href = parent.get("attributes", {}).get("href", "")
        return href if isinstance(href, str) else ""
    return ""


def enumerate_slots(template_component: dict) -> list[dict]:
    """List all override slots for a template's component tree.

    Returns a list of dicts with keys: key, type, field, value.
    Slot keys follow the pattern: {type}_{n} for content,
    {type}_{n}_{attr} for attributes (e.g. button_1_href).

    Section-rooted templates also expose a ``background_image`` slot: a
    section-level URL applied as a cover background (see ``apply_overrides``),
    so full-bleed photo bands work on any template without a dedicated image
    component.

    Every image also exposes an ``image_N_href`` slot -- the image's native
    clickable destination, applied by wrapping the image in a ``link``
    component rather than by writing an attribute onto the image itself (see
    ``apply_overrides``). It is a distinct slot type from ``link_N``/
    ``link_N_href``: those number editable text links, this numbers image
    destinations, and the two must never collide or shift one another.
    """
    slots: list[dict] = []
    for comp, ancestors, comp_type, n in _walk_overridable_with_ancestors(template_component):
        if comp_type in CONTENT_TYPES:
            slots.append({
                "key": f"{comp_type}_{n}",
                "type": comp_type,
                "field": "content",
                "value": comp.get("content", ""),
            })
        for suffix, attr_name in ATTRIBUTE_SLOTS.get(comp_type, []):
            slots.append({
                "key": f"{comp_type}_{n}_{suffix}",
                "type": comp_type,
                "field": f"attributes.{attr_name}",
                "value": comp.get("attributes", {}).get(attr_name, ""),
            })
        if comp_type == "image":
            slots.append({
                "key": f"image_{n}_href",
                "type": "image",
                "field": "link.href",
                "value": _current_image_href(comp, ancestors),
            })
    if template_component.get("type") == "section":
        slots.append({
            "key": "background_image",
            "type": "section",
            "field": "style.background-image",
            "value": "",
        })
    return slots


_HEADING_OVERRIDE_KEY = re.compile(r"^heading_(\d+)$")
_TEXT_OVERRIDE_KEY = re.compile(r"^text_(\d+)$")
_IMAGE_SRC_OVERRIDE_KEY = re.compile(r"^image_(\d+)_src$")
_LIST_ITEM_OVERRIDE_KEY = re.compile(r"^list-item_(\d+)$")
_BUTTON_OVERRIDE_KEY = re.compile(r"^button_(\d+)$")


def _max_requested_heading_slot(overrides: dict[str, str]) -> int:
    indices = [
        int(match.group(1))
        for key in overrides
        if (match := _HEADING_OVERRIDE_KEY.match(key))
    ]
    return max(indices, default=0)


def _max_requested_text_slot(overrides: dict[str, str]) -> int:
    indices = [
        int(match.group(1))
        for key in overrides
        if (match := _TEXT_OVERRIDE_KEY.match(key))
    ]
    return max(indices, default=0)


def _max_requested_image_slot(overrides: dict[str, str]) -> int:
    indices = [
        int(match.group(1))
        for key in overrides
        if (match := _IMAGE_SRC_OVERRIDE_KEY.match(key)) and overrides[key]
    ]
    return max(indices, default=0)


def _max_requested_button_slot(overrides: dict[str, str]) -> int:
    indices = [
        int(match.group(1))
        for key in overrides
        if (match := _BUTTON_OVERRIDE_KEY.match(key)) and overrides[key]
    ]
    return max(indices, default=0)


def _max_requested_list_slot(overrides: dict[str, str]) -> int:
    indices = [
        int(match.group(1))
        for key in overrides
        if (match := _LIST_ITEM_OVERRIDE_KEY.match(key)) and overrides[key]
    ]
    return max(indices, default=0)


def _rewrite_component_ids(component: dict, suffix: str) -> None:
    attributes = component.get("attributes")
    if attributes and attributes.get("id"):
        attributes["id"] = f"{attributes['id']}{suffix}"
    for child in component.get("components", []):
        _rewrite_component_ids(child, suffix)


def _find_last_of_type(
    component: dict, comp_type: str, parent: dict | None = None
) -> tuple[dict, dict] | None:
    """Return (component, parent) for the last component of ``comp_type``."""
    found = (component, parent) if component.get("type") == comp_type else None
    for child in component.get("components", []):
        child_found = _find_last_of_type(child, comp_type, component)
        if child_found is not None:
            found = child_found
    return found


_CONTENT_OVERRIDE_KEY = re.compile(r"^([a-z-]+)_(\d+)$")


def _requested_slot_counts(overrides: dict[str, str]) -> dict[str, int]:
    """Max requested slot index per component type, counting non-empty values only."""
    requested: dict[str, int] = {}
    for key, value in overrides.items():
        if not value:
            continue
        if match := _IMAGE_SRC_OVERRIDE_KEY.match(key):
            comp_type, index = "image", int(match.group(1))
        elif (match := _CONTENT_OVERRIDE_KEY.match(key)) and match.group(1) in CONTENT_TYPES:
            comp_type, index = match.group(1), int(match.group(2))
        else:
            continue
        requested[comp_type] = max(requested.get(comp_type, 0), index)
    return requested


def _leaf_slot_counts(component: dict) -> dict[str, int]:
    """Count overridable components by type within a subtree."""
    counts: dict[str, int] = {}
    for _, comp_type, _ in _walk_overridable(component):
        counts[comp_type] = counts.get(comp_type, 0) + 1
    return counts


def _find_repeating_groups(
    component: dict, depth: int = 0
) -> Generator[tuple[dict, list[dict], dict[str, int], int], None, None]:
    """Yield (parent, members, per_unit_counts, depth) for repeating wrapper groups.

    A group is two or more sibling wrapper components (not overridable leaves
    themselves) with the same type and the same overridable-leaf makeup —
    the structural shape of a card grid's columns.
    """
    groups: dict[tuple, list[dict]] = {}
    for child in component.get("components", []):
        child_type = child.get("type", "")
        if child_type in CONTENT_TYPES or child_type in ATTRIBUTE_SLOTS:
            continue
        leaf_counts = _leaf_slot_counts(child)
        if not leaf_counts:
            continue
        signature = (child_type, tuple(sorted(leaf_counts.items())))
        groups.setdefault(signature, []).append(child)

    for (_, leaf_items), members in groups.items():
        if len(members) >= 2:
            yield component, members, dict(leaf_items), depth

    for child in component.get("components", []):
        yield from _find_repeating_groups(child, depth + 1)


def expand_column_units(template_data: dict, overrides: dict[str, str]) -> dict:
    """Clone whole column/card units when overrides exceed template capacity.

    A 3-up card template fed 9 cards' worth of overrides must grow by cloning
    the repeating COLUMN unit inside the row — cloning text/image leaves
    collapses the grid into one stacked column. Runs before leaf expansion;
    leaf expansion then absorbs any residue the units don't cover.
    """
    requested = _requested_slot_counts(overrides)
    if not requested:
        return template_data

    existing = _leaf_slot_counts(template_data["template"])
    deficits = {
        comp_type: count - existing.get(comp_type, 0)
        for comp_type, count in requested.items()
        if count > existing.get(comp_type, 0)
    }
    if not deficits:
        return template_data

    result = copy.deepcopy(template_data)
    best: tuple[tuple[int, int], dict, list[dict], dict[str, int], list[str]] | None = None
    for parent, members, unit_counts, depth in _find_repeating_groups(result["template"]):
        covered = [t for t in deficits if unit_counts.get(t)]
        if not covered:
            continue
        rank = (len(covered), depth)
        if best is None or rank > best[0]:
            best = (rank, parent, members, unit_counts, covered)
    if best is None:
        return template_data

    _, parent, members, unit_counts, covered = best
    units_needed = max(
        (deficits[t] + unit_counts[t] - 1) // unit_counts[t] for t in covered
    )
    last_unit = members[-1]
    insert_at = parent["components"].index(last_unit) + 1
    for clone_number in range(units_needed):
        clone = copy.deepcopy(last_unit)
        _rewrite_component_ids(clone, f"-u{clone_number + 2}")
        parent["components"].insert(insert_at + clone_number, clone)
    return result


def expand_heading_slots(template_data: dict, overrides: dict[str, str]) -> dict:
    """Clone the last heading slot until every ``heading_N`` override has a home.

    Crawled content sections carry one heading per subsection while generic
    templates ship a single title slot (Rich Text Block) — before expansion
    every heading past the slot count was dropped, losing real section titles
    even though the surrounding paragraphs were absorbed. Clones land directly
    after the template's last heading — same parent, so they inherit its
    column/styling — with ``-xN`` id suffixes to keep ids unique.
    """
    requested = _max_requested_heading_slot(overrides)
    if requested == 0:
        return template_data

    existing = sum(
        1 for _, comp_type, _ in _walk_overridable(template_data["template"])
        if comp_type == "heading"
    )
    if existing == 0 or requested <= existing:
        return template_data

    result = copy.deepcopy(template_data)
    located = _find_last_of_type(result["template"], "heading")
    if located is None or located[1] is None:
        return template_data
    last_heading, parent = located

    insert_at = parent["components"].index(last_heading) + 1
    for clone_number in range(requested - existing):
        clone = copy.deepcopy(last_heading)
        _rewrite_component_ids(clone, f"-x{clone_number + 2}")
        parent["components"].insert(insert_at + clone_number, clone)
    return result


def expand_text_slots(template_data: dict, overrides: dict[str, str]) -> dict:
    """Clone the last text slot until every ``text_N`` override has a home.

    Crawled pages routinely carry more paragraphs than a template ships slots
    for (a blog post body vs. Rich Text Block's four). Clones land directly
    after the template's last text component — same parent, so they inherit
    its column/styling — with ``-xN`` id suffixes to keep ids unique.
    """
    requested = _max_requested_text_slot(overrides)
    if requested == 0:
        return template_data

    existing = sum(
        1 for _, comp_type, _ in _walk_overridable(template_data["template"])
        if comp_type == "text"
    )
    if existing == 0 or requested <= existing:
        return template_data

    result = copy.deepcopy(template_data)
    located = _find_last_of_type(result["template"], "text")
    if located is None or located[1] is None:
        return template_data
    last_text, parent = located

    insert_at = parent["components"].index(last_text) + 1
    for clone_number in range(requested - existing):
        clone = copy.deepcopy(last_text)
        _rewrite_component_ids(clone, f"-x{clone_number + 2}")
        parent["components"].insert(insert_at + clone_number, clone)
    return result


def expand_image_slots(template_data: dict, overrides: dict[str, str]) -> dict:
    """Make room for every ``image_N_src`` override.

    Clones the template's last image component in place when slots run out.
    Templates with no image component at all (e.g. Rich Text Block) get a
    plain responsive image appended next to their last text component —
    dropping page imagery on the floor is worse than a generic placement.
    """
    requested = _max_requested_image_slot(overrides)
    if requested == 0:
        return template_data

    existing = sum(
        1 for _, comp_type, _ in _walk_overridable(template_data["template"])
        if comp_type == "image"
    )
    if 0 < existing >= requested:
        return template_data

    result = copy.deepcopy(template_data)
    located = _find_last_of_type(result["template"], "image")
    if located is not None and located[1] is not None:
        last_image, parent = located
        insert_at = parent["components"].index(last_image) + 1
        for clone_number in range(requested - existing):
            clone = copy.deepcopy(last_image)
            _rewrite_component_ids(clone, f"-x{clone_number + 2}")
            parent["components"].insert(insert_at + clone_number, clone)
        return result

    # A single synthesized image is an article's featured image: float it
    # right of the first text block so the body wraps around it, the way the
    # source lays it out. Appending at the end (the multi-image gallery case)
    # would strand it full-width below the article.
    if requested == 1:
        heading = _find_last_of_type(result["template"], "heading")
        text = _find_last_of_type(result["template"], "text")
        anchor = text or heading
        if anchor is None or anchor[1] is None:
            return template_data
        anchor_component, parent = (heading or text)
        insert_at = parent["components"].index(anchor_component) + 1
        parent["components"].insert(insert_at, {
            "type": "image",
            "tagName": "img",
            "classes": [{"name": "img-fluid", "active": False}],
            "attributes": {
                "id": "tpl-auto-img1",
                "src": "",
                "alt": "",
                "style": "float:right;max-width:42%;margin:0 0 1rem 1.5rem;",
            },
        })
        return result

    anchor = _find_last_of_type(result["template"], "text") or _find_last_of_type(
        result["template"], "heading"
    )
    if anchor is None or anchor[1] is None:
        return template_data
    _, parent = anchor
    for slot_number in range(1, requested + 1):
        parent["components"].append({
            "type": "image",
            "tagName": "img",
            "classes": [{"name": "img-fluid", "active": False}],
            "attributes": {"id": f"tpl-auto-img{slot_number}", "src": "", "alt": ""},
        })
    return result


def expand_list_slots(template_data: dict, overrides: dict[str, str]) -> dict:
    """Make room for every ``list-item_N`` override.

    Clones the template's last list-item in place when slots run out.
    Templates with no list at all (e.g. Feature Cards fed a checklist
    section) get a plain list appended next to their last text component —
    checklists and feature lists must ship, not drop.
    """
    requested = _max_requested_list_slot(overrides)
    if requested == 0:
        return template_data

    existing = sum(
        1 for _, comp_type, _ in _walk_overridable(template_data["template"])
        if comp_type == "list-item"
    )
    if 0 < existing >= requested:
        return template_data

    result = copy.deepcopy(template_data)
    located = _find_last_of_type(result["template"], "list-item")
    if located is not None and located[1] is not None:
        last_item, parent = located
        insert_at = parent["components"].index(last_item) + 1
        for clone_number in range(requested - existing):
            clone = copy.deepcopy(last_item)
            _rewrite_component_ids(clone, f"-x{clone_number + 2}")
            parent["components"].insert(insert_at + clone_number, clone)
        return result

    anchor = _find_last_of_type(result["template"], "text") or _find_last_of_type(
        result["template"], "heading"
    )
    if anchor is None or anchor[1] is None:
        return template_data
    _, parent = anchor
    parent["components"].append({
        "type": "list",
        "classes": [{"name": "list", "active": False}],
        "attributes": {"id": "tpl-auto-list"},
        "components": [
            {
                "type": "list-item",
                "content": "",
                "classes": [{"name": "list-item", "active": False}],
                "attributes": {"id": f"tpl-auto-li{slot_number}"},
            }
            for slot_number in range(1, requested + 1)
        ],
    })
    return result


def expand_button_slots(template_data: dict, overrides: dict[str, str]) -> dict:
    """Make room for every ``button_N`` override.

    Clones the template's last button in place when slots run out. Templates
    with no button at all (Rich Text Block fed a section whose call-to-action
    the source styles as a button) get a button-styled link appended after
    the last text component — a section's CTA must ship, not drop.
    """
    requested = _max_requested_button_slot(overrides)
    if requested == 0:
        return template_data

    existing = sum(
        1 for _, comp_type, _ in _walk_overridable(template_data["template"])
        if comp_type == "button"
    )
    if 0 < existing >= requested:
        return template_data

    result = copy.deepcopy(template_data)
    located = _find_last_of_type(result["template"], "button")
    if located is not None and located[1] is not None:
        last_button, parent = located
        insert_at = parent["components"].index(last_button) + 1
        for clone_number in range(requested - existing):
            clone = copy.deepcopy(last_button)
            _rewrite_component_ids(clone, f"-x{clone_number + 2}")
            parent["components"].insert(insert_at + clone_number, clone)
        return result

    # Sections carry one CTA, occasionally a pair — a higher request against
    # a buttonless template is card-grid content that belongs to column-unit
    # expansion, not a row of synthesized buttons. Leave it to overflow
    # reporting instead.
    if requested > 2:
        return template_data
    anchor = _find_last_of_type(result["template"], "text") or _find_last_of_type(
        result["template"], "heading"
    )
    if anchor is None or anchor[1] is None:
        return template_data
    _, parent = anchor
    for slot_number in range(1, requested + 1):
        parent["components"].append({
            "type": "button",
            "tagName": "a",
            "classes": [
                {"name": "btn", "active": False},
                {"name": "btn-primary", "active": False},
                {"name": "button-style-1", "active": False},
                {"name": "mt-4", "active": False},
            ],
            "attributes": {"id": f"tpl-auto-btn{slot_number}", "role": "button", "href": "#"},
        })
    return result


def attach_form_placeholder(section: dict, fields: list[dict]) -> None:
    """Append a visible placeholder where the source page had a form.

    Migrated pages deliberately carry NO working or lookalike form: forms on
    the target platform are built with the site's forms plugin and need
    manual setup in the editor, and a rendered ``<form>`` that silently
    drops submissions is worse than an honest marker. The placeholder lists
    the detected fields (required ones starred) so whoever rebuilds the form
    knows exactly what to configure.
    """
    if not fields:
        return
    located = _find_last_of_type(section, "text") or _find_last_of_type(section, "heading")
    parent = located[1] if located is not None and located[1] is not None else section

    field_labels: list[str] = []
    for index, field in enumerate(fields, start=1):
        if not isinstance(field, dict):
            continue
        label = str(field.get("label") or field.get("name") or f"Field {index}")
        field_labels.append(f"{label}*" if field.get("required") else label)

    parent.setdefault("components", []).append({
        "type": "default",
        "tagName": "div",
        "classes": [
            {"name": "form-placeholder", "active": False},
            {"name": "border", "active": False},
            {"name": "rounded", "active": False},
            {"name": "p-4", "active": False},
            {"name": "my-3", "active": False},
            {"name": "text-center", "active": False},
        ],
        "attributes": {
            "id": "tpl-form-placeholder",
            "style": "border:2px dashed #999 !important;",
        },
        "components": [
            {
                "type": "heading",
                "tagName": "h4",
                "content": "[ Contact form goes here ]",
                "attributes": {"id": "tpl-form-placeholder-title"},
            },
            {
                "type": "text",
                "content": (
                    "Rebuild this form with the forms plugin. Detected fields: "
                    + ", ".join(field_labels)
                    + " (* = required)"
                ),
                "attributes": {"id": "tpl-form-placeholder-fields"},
            },
        ],
    })


def _walk_overridable_with_ancestors(
    component: dict,
    ancestors: list[dict] | None = None,
    counters: dict[str, int] | None = None,
) -> Generator[tuple[dict, list[dict], str, int], None, None]:
    """Like ``_walk_overridable`` but also yields each component's ancestor chain.

    The chain (root-to-parent order) lets a caller splice a component out of
    its parent's children and walk back up pruning any wrapper the removal
    leaves empty. Applies the same generated-image-link-wrapper exclusion as
    ``_walk_overridable`` (see its docstring) so every caller -- including
    ``enumerate_slots`` -- reports the same ``link_N`` numbering that
    ``apply_overrides`` actually honors.
    """
    if ancestors is None:
        ancestors = []
    if counters is None:
        counters = {}

    comp_type = component.get("type", "")
    if comp_type in CONTENT_TYPES or comp_type in ATTRIBUTE_SLOTS:
        if not (comp_type == "link" and is_generated_image_link_wrapper(component)):
            counters[comp_type] = counters.get(comp_type, 0) + 1
            yield component, ancestors, comp_type, counters[comp_type]

    for child in component.get("components", []):
        yield from _walk_overridable_with_ancestors(child, ancestors + [component], counters)


def _remove_child(parent: dict, child: dict) -> None:
    """Remove ``child`` from ``parent``'s components list by identity."""
    children = parent.get("components")
    if not isinstance(children, list):
        return
    for index, candidate in enumerate(children):
        if candidate is child:
            del children[index]
            return


def prune_unfilled_images(section: dict, overrides: dict[str, str]) -> None:
    """Remove image components an unfilled crawled override left at the template default.

    ``apply_overrides`` only writes an image's ``src`` when the override map
    supplies ``image_N_src`` — an image slot the crawl never filled keeps the
    template's placeholder ``src`` (a placehold.co URL), which renders as a
    gray placeholder frame on the migrated page. A dropped ``<img>`` is a
    better outcome than a broken-image icon, so the component is removed
    entirely rather than blanked. Any wrapper (column, figure, ...) the
    removal leaves childless is removed in turn, walking up the tree until a
    still-populated ancestor or the section root is reached — the section
    itself is never removed.

    Only meaningful for crawler-content sections: manual ``--overrides`` mode
    supplies every value deliberately, so it never calls this function.
    Mutates ``section`` in place.

    An unfilled image whose src is a real URL rather than a placeholder is
    template chrome (a decorative graphic the template ships on purpose) and
    is kept.
    """
    to_remove: list[tuple[dict, list[dict]]] = []
    for component, ancestors, comp_type, index in _walk_overridable_with_ancestors(section):
        if comp_type != "image":
            continue
        if overrides.get(f"image_{index}_src"):
            continue
        src = (component.get("attributes") or {}).get("src", "")
        if src and "placehold" not in src:
            continue
        to_remove.append((component, ancestors))

    for component, ancestors in to_remove:
        chain = [*ancestors, component]
        for depth in range(len(chain) - 1, 0, -1):
            child, parent = chain[depth], chain[depth - 1]
            _remove_child(parent, child)
            if parent.get("type") == "section" or parent.get("components") or parent.get("content"):
                break


def _prune_explicitly_empty_slots(section: dict, overrides: dict[str, str]) -> None:
    """Remove template chrome for slots the composition plan explicitly cleared."""

    to_remove: list[tuple[dict, list[dict]]] = []
    for component, ancestors, comp_type, index in _walk_overridable_with_ancestors(section):
        content_key = f"{comp_type}_{index}"
        cleared_content = (
            comp_type in CONTENT_TYPES
            and content_key in overrides
            and overrides[content_key] == ""
        )
        source_key = f"image_{index}_src"
        cleared_image = (
            comp_type == "image"
            and source_key in overrides
            and overrides[source_key] == ""
        )
        if cleared_content or cleared_image:
            to_remove.append((component, ancestors))

    for component, ancestors in to_remove:
        chain = [*ancestors, component]
        for depth in range(len(chain) - 1, 0, -1):
            child, parent = chain[depth], chain[depth - 1]
            _remove_child(parent, child)
            if parent.get("type") == "section" or parent.get("components") or parent.get("content"):
                break


def _apply_image_link_overrides(section: dict, overrides: dict[str, str]) -> None:
    """Apply every requested ``image_N_href`` to the image it actually owns.

    Runs before ``_prune_explicitly_empty_slots``: image indices number the
    physical components as they exist right after expansion, the same shape
    ``image_N_src``/``image_N_alt`` were assigned against. Pruning removes
    components, and numbering a later pass against the pruned tree would let
    a removed leading image silently shift every later image's href onto the
    wrong picture.

    Targets are collected before any mutation (matching the pattern used by
    ``prune_unfilled_images``/``_prune_explicitly_empty_slots`` above): wrapping
    an image in place, in the middle of the same tree walk that found it, would
    make the walk's own live ancestor lists inconsistent mid-traversal.
    """
    targets: list[tuple[dict, dict, list[dict], str]] = []
    for component, ancestors, comp_type, index in _walk_overridable_with_ancestors(section):
        if comp_type != "image" or not ancestors:
            continue
        key = f"image_{index}_href"
        if key not in overrides:
            continue
        targets.append((component, ancestors[-1], ancestors, overrides[key]))

    if not targets:
        return
    existing_ids = collect_component_ids(section)
    for image, parent, ancestors, href in targets:
        apply_image_link(image, parent, ancestors, href, existing_ids)


def _expand_slots(template_data: dict, overrides: dict[str, str]) -> dict:
    """Run unit expansion, then leaf expansion for any residue units don't cover."""
    expanded = expand_column_units(template_data, overrides)
    expanded = expand_text_slots(expand_heading_slots(expanded, overrides), overrides)
    return expand_button_slots(
        expand_list_slots(expand_image_slots(expanded, overrides), overrides), overrides
    )


def _apply_content_overrides(template_root: dict, overrides: dict[str, str]) -> None:
    """Write every content/attribute override onto its matching slot, in place.

    Shared by ``apply_overrides`` and ``apply_overrides_with_owners`` so both
    walk the tree with the exact same numbering rules exactly once.
    """
    for comp, comp_type, n in _walk_overridable(template_root):
        # A link this code generated as an image's destination wrapper is
        # never yielded here at all (see _walk_overridable) -- it is
        # addressed only through the owning image's image_N_href, handled
        # by _apply_image_link_overrides below. Anything that does reach
        # this loop, including an authored content-free single-image
        # wrapper, is a legitimate link_N/link_N_href slot like any other.
        content_key = f"{comp_type}_{n}"
        if content_key in overrides and comp_type in CONTENT_TYPES:
            comp["content"] = overrides[content_key]
        for suffix, attr_name in ATTRIBUTE_SLOTS.get(comp_type, []):
            attr_key = f"{comp_type}_{n}_{suffix}"
            if attr_key in overrides:
                comp.setdefault("attributes", {})[attr_name] = overrides[attr_key]


def apply_overrides(template_data: dict, overrides: dict[str, str]) -> dict:
    """Deep-copy a template and apply content overrides to matching slots.

    Column units, then heading, text, and image slots, are expanded first so
    content beyond the template's capacity is absorbed instead of dropped.

    Returns the full template dict (name, category, description, template, styles)
    with the component tree modified according to the overrides.
    """
    expanded = _expand_slots(template_data, overrides)
    result = copy.deepcopy(expanded)
    _apply_content_overrides(result["template"], overrides)
    background_image = overrides.get("background_image")
    if background_image and result["template"].get("type") == "section":
        apply_section_background(result["template"], {"background_image": background_image})
    _apply_image_link_overrides(result["template"], overrides)
    _prune_explicitly_empty_slots(result["template"], overrides)
    _balance_card_rows(result["template"])
    return result


def _capture_owners(template_root: dict) -> dict[str, dict]:
    """Map every current override slot key to its physical component, by identity.

    Uses the exact same numbering ``_walk_overridable``/``enumerate_slots``
    produce, at the exact tree shape ``apply_overrides`` itself walks right
    after expansion -- before any content is written, image is wrapped, or
    empty slot is pruned. This is the "stable owner reference" a later
    ``image_N_href`` wrap or an earlier slot's pruning must never invalidate.
    """
    owners: dict[str, dict] = {}
    for comp, comp_type, n in _walk_overridable(template_root):
        owners[f"{comp_type}_{n}"] = comp
        for suffix, _attr_name in ATTRIBUTE_SLOTS.get(comp_type, []):
            owners[f"{comp_type}_{n}_{suffix}"] = comp
    return owners


def _capture_image_href_owners(template_root: dict, owners: dict[str, dict]) -> None:
    """Record each linked image's wrapper as the owner of its ``image_N_href`` slot.

    Must run after ``_apply_image_link_overrides`` so a wrapper that call just
    created or adopted is present in the tree. An image with no clickable
    wrapper simply gets no ``image_N_href`` entry -- there is no owner for that
    slot, not a fallback to the image itself or a sibling.
    """
    for comp, ancestors, comp_type, n in _walk_overridable_with_ancestors(template_root):
        if comp_type != "image" or not ancestors:
            continue
        parent = ancestors[-1]
        if is_image_link_wrapper(parent) and parent.get("components", [None])[0] is comp:
            owners[f"image_{n}_href"] = parent


def _collect_identities(component: dict, seen: set[int]) -> None:
    seen.add(id(component))
    for child in component.get("components", []) or []:
        if isinstance(child, dict):
            _collect_identities(child, seen)


def _drop_removed_owners(template_root: dict, owners: dict[str, dict]) -> None:
    """Remove any owner reference pruning left outside the final tree.

    A pruned slot's owner is simply absent from ``owners`` afterward -- never
    silently repointed at whatever component ended up at its old numeric
    position, which pruning can and does renumber.
    """
    present: set[int] = set()
    _collect_identities(template_root, present)
    for key in [key for key, comp in owners.items() if id(comp) not in present]:
        del owners[key]


def apply_overrides_with_owners(
    template_data: dict, overrides: dict[str, str]
) -> tuple[dict, dict[str, dict]]:
    """Like ``apply_overrides``, but also return each surviving slot's owner component.

    The returned mapping's keys are the same slot-key vocabulary
    ``enumerate_slots``/``SemanticBinding.slot`` use (``heading_2``,
    ``button_1``, ``image_3_src``, ``image_3_href`` ...). A slot removed by
    ``_prune_explicitly_empty_slots`` -- or an image never given a clickable
    wrapper -- is simply absent; callers must treat a missing key as a removed
    or nonexistent owner, never fall back to a sibling or a stale position.
    """
    expanded = _expand_slots(template_data, overrides)
    result = copy.deepcopy(expanded)
    owners = _capture_owners(result["template"])
    _apply_content_overrides(result["template"], overrides)
    background_image = overrides.get("background_image")
    if background_image and result["template"].get("type") == "section":
        apply_section_background(result["template"], {"background_image": background_image})
    _apply_image_link_overrides(result["template"], overrides)
    _capture_image_href_owners(result["template"], owners)
    _prune_explicitly_empty_slots(result["template"], overrides)
    _drop_removed_owners(result["template"], owners)
    _balance_card_rows(result["template"])
    return result, owners


_COL_WIDTH_CLASS = re.compile(r"^col(?:-(?:sm|md|lg|xl))?-\d+$")


def _columns_per_row_for(count: int) -> int:
    """Pick a per-row column count that divides ``count`` evenly when possible.

    Prefers wider rows (4 → 3 → 2) so a grid balances instead of orphaning a
    trailing item (4 images at 3-per-row = 3 + 1). Falls back to 3 when no
    small divisor fits (e.g. 7, 35), matching the templates' default.
    """
    for per_row in (4, 3, 2):
        if count % per_row == 0:
            return per_row
    return 3


def _balance_card_rows(component: dict) -> None:
    """Rebalance a row of ≥4 uniform card columns to an even per-row count.

    Column expansion clones the template's card column to fit the content, but
    the cloned width (e.g. col-md-4 = 3 per row) can leave an orphan when the
    final count doesn't divide by 3. Rewrites every column's responsive width
    so rows divide evenly; leaves small/odd grids on the template default.
    """
    for child in component.get("components", []):
        _balance_card_rows(child)

    columns = [c for c in component.get("components", []) if c.get("type") == "column"]
    if len(columns) < 4:
        return
    per_row = _columns_per_row_for(len(columns))
    width = 12 // per_row
    for column in columns:
        kept = [
            cls for cls in column.get("classes", [])
            if not _COL_WIDTH_CLASS.match(cls.get("name", ""))
        ]
        kept.append({"name": f"col-md-{width}", "active": False})
        kept.append({"name": "col-sm-6", "active": False})
        kept.append({"name": "col-12", "active": False})
        column["classes"] = kept


def _luminance(value: str) -> float | None:
    """Perceptual luminance (0–255) of a hex/rgb color, or None if unparsable."""
    rgb = parse_color(value)
    if rgb is None:
        return None
    red, green, blue = rgb
    return 0.299 * red + 0.587 * green + 0.114 * blue


def _is_dark_color(value: str) -> bool:
    luminance = _luminance(value)
    return luminance is not None and luminance < 128


# Minimum luminance gap between text and band for the text to stay legible.
# Source-captured text colors are designed for the element's *own* background,
# which often differs from the band color the crawl pairs it with (e.g. gray
# nav text meant for a white area landing on an olive band).
_MIN_CONTRAST = 80


def _resolve_band_text_color(
    background: str, has_color: bool, has_image: bool, captured: str | None
) -> str | None:
    """Pick the text color a band should aim for given any captured color.

    A captured text color designed for a different background can land on this
    band with too little contrast (gray nav text on an olive band). When the
    gap is too small — or no color was captured at all — fall to the readable
    extreme for the band's brightness. Light bands with no capture keep the
    page default (already dark on light), so this can still return None.
    """
    band_luminance = _luminance(background) if has_color else None
    captured_luminance = _luminance(captured) if captured else None
    poor_contrast = (
        band_luminance is not None
        and captured_luminance is not None
        and abs(band_luminance - captured_luminance) < _MIN_CONTRAST
    )
    if poor_contrast:
        return "#111111" if band_luminance >= 128 else "#ffffff"
    if captured is None and (
        (has_color and _is_dark_color(background)) or (has_image and not has_color)
    ):
        return "#ffffff"
    return captured


# Sections whose background-role images are promoted to the band background.
# Card/content sections keep them inline — there a CSS background is often
# the card's own visual, not the band's.
_BACKGROUND_PROMOTED_SECTION_TYPES = frozenset({"hero", "cta"})

# Full-bleed band photos are almost always photographic formats; transparent
# slants, waves, and pattern overlays ship as png/svg.
_PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".webp", ".avif")


def _most_photographic(urls: list[str]) -> str:
    """Return the first URL with a photographic extension, else the first URL."""
    for url in urls:
        if urlsplit(url).path.lower().endswith(_PHOTO_EXTENSIONS):
            return url
    return urls[0]


def promote_background_images(content: dict, section_type: str | None) -> None:
    """Route background-role images into the section background for hero/cta bands.

    The crawler tags CSS-derived backgrounds it finds inside a section as
    ``role: "background"`` in ``content.images``. For hero/cta sections that
    photo is the band's dominant visual: left in the inline list it renders
    as a stray floating ``<img>``, while a decorative outer background (a
    transparent slant/wave PNG captured as ``content.background_image``)
    wins the band instead. Move background-role images out of the inline
    list and put the most photo-like candidate in ``content.background_image``
    so ``apply_section_background`` renders it full-bleed.
    """
    if section_type not in _BACKGROUND_PROMOTED_SECTION_TYPES:
        return
    images = content.get("images")
    if not isinstance(images, list):
        return
    background_urls = [
        image["src"]
        for image in images
        if isinstance(image, dict)
        and image.get("role") == "background"
        and isinstance(image.get("src"), str)
        and image["src"]
    ]
    if not background_urls:
        return
    content["images"] = [
        image
        for image in images
        if not (isinstance(image, dict) and image.get("role") == "background")
    ]
    existing = content.get("background_image")
    if isinstance(existing, str) and existing:
        background_urls.append(existing)
    content["background_image"] = _most_photographic(background_urls)


def apply_section_background(
    section: dict,
    content: dict,
    palette: dict[str, tuple[int, int, int]] | None = None,
    styles: list | None = None,
) -> None:
    """Carry crawled band colors onto a composed component.

    Without a ``palette`` the colors are written as one inline ``style``
    string — the original behaviour. With a ``palette`` (slot -> rgb) the
    background and text colors that match a theme slot become ``bg-{slot}`` /
    ``text-{slot}`` classes so a theme change cascades through them; colors
    that match no slot, and background images, fall to a per-id rule appended
    to ``styles`` (the composed block's styles array). Dark backgrounds with
    no explicit text color get light text so the band stays readable.
    """
    background = content.get("background_color")
    background_image = content.get("background_image")
    has_color = isinstance(background, str) and background
    has_image = isinstance(background_image, str) and background_image
    if not has_color and not has_image:
        return

    captured = content.get("text_color")
    if not isinstance(captured, str) or not captured:
        captured = None
    text_color = _resolve_band_text_color(background, has_color, has_image, captured)

    if palette is None:
        _apply_inline_background(section, background, background_image, has_color, has_image, text_color)
        return

    _apply_palette_background(
        section, background, background_image, has_color, has_image, text_color, palette, styles
    )


def _apply_inline_background(
    section: dict,
    background: str,
    background_image: str,
    has_color: bool,
    has_image: bool,
    text_color: str | None,
) -> None:
    style = ""
    if has_color:
        style += f"background-color:{background};"
    if has_image:
        style += (
            f"background-image:url({background_image});"
            "background-size:cover;background-position:center;"
            f"text-shadow:{_IMAGE_BAND_TEXT_SHADOW};"
        )
    if text_color:
        style += f"color:{text_color};"

    attributes = section.setdefault("attributes", {})
    existing = attributes.get("style", "")
    attributes["style"] = f"{existing.rstrip(';')};{style}".lstrip(";") if existing else style


# Soft dark shadow behind text on image-backed bands — legibility insurance
# for wherever the photo/pattern runs light under light text.
_IMAGE_BAND_TEXT_SHADOW = "0 1px 3px rgba(0,0,0,0.55)"

# Slot a near-white captured/derived text color resolves to. Reference sites
# use text-light for light text on dark bands rather than text-white.
_LIGHT_TEXT_SLOT = "light"
_DARK_TEXT_SLOT = "dark"
_NEAR_WHITE_LUMINANCE = 230
_NEAR_BLACK_LUMINANCE = 40


def _text_color_slot(
    text_color: str, palette: dict[str, tuple[int, int, int]]
) -> str | None:
    """Map a text color to a ``text-{slot}`` slot name, or None to inline it.

    Near-white text maps to ``light`` and near-black to ``dark`` (the slots
    reference sites use for band text) regardless of the exact palette hex;
    anything else falls back to nearest-slot matching.
    """
    luminance = _luminance(text_color)
    if luminance is not None and luminance >= _NEAR_WHITE_LUMINANCE:
        return _LIGHT_TEXT_SLOT
    if luminance is not None and luminance <= _NEAR_BLACK_LUMINANCE:
        return _DARK_TEXT_SLOT
    return nearest_palette_slot(text_color, palette)


def _apply_palette_background(
    section: dict,
    background: str,
    background_image: str,
    has_color: bool,
    has_image: bool,
    text_color: str | None,
    palette: dict[str, tuple[int, int, int]],
    styles: list | None,
) -> None:
    inline_rule: dict[str, str] = {}

    if has_color:
        slot = nearest_palette_slot(background, palette)
        if slot:
            _add_class(section, f"bg-{slot}")
        else:
            inline_rule["background-color"] = background

    if has_image:
        inline_rule["background-image"] = f"url({background_image})"
        inline_rule["background-size"] = "cover"
        inline_rule["background-position"] = "center"
        # Text over a photo/pattern has no guaranteed contrast anywhere the
        # image runs light (white hero text went invisible over the white
        # half of a striped pattern) — a soft dark shadow keeps any band
        # text legible without needing to know the image's brightness.
        inline_rule["text-shadow"] = _IMAGE_BAND_TEXT_SHADOW

    if text_color:
        slot = _text_color_slot(text_color, palette)
        if slot:
            _add_class(section, f"text-{slot}")
        else:
            inline_rule["color"] = text_color

    if inline_rule and styles is not None:
        section_id = _ensure_section_id(section)
        styles.append(_id_style_rule(section_id, inline_rule))


def _add_class(component: dict, class_name: str) -> None:
    """Add a class in {name, active: false} form, skipping duplicates."""
    classes = component.setdefault("classes", [])
    if any(isinstance(c, dict) and c.get("name") == class_name for c in classes):
        return
    classes.append({"name": class_name, "active": False})


def _ensure_section_id(component: dict) -> str:
    """Return the component's id attribute, generating a stable one if absent.

    Matches the ``i``-prefixed short-hex id shape templates and assemble use,
    so the per-id style rule's selector lines up with what the editor expects.
    """
    attributes = component.setdefault("attributes", {})
    section_id = attributes.get("id")
    if not section_id:
        section_id = f"i{uuid.uuid4().hex[:8]}"
        attributes["id"] = section_id
    return section_id


def _id_style_rule(section_id: str, style: dict[str, str]) -> dict:
    """Build a GrapesJS style rule targeting a component by its id attribute.

    Vanjaro serializes a per-element rule with a single class-type selector
    whose name equals the element's id (see the composed-page styles array).
    """
    return {
        "selectors": [
            {
                "name": section_id,
                "label": section_id,
                "type": 2,
                "active": True,
                "private": True,
                "protected": False,
            }
        ],
        "style": style,
    }


def check_overflow(template_data: dict, overrides: dict[str, str]) -> list[str]:
    """Return override keys that don't match any slot in the template.

    Useful for detecting silent data loss when a migration plan has more
    content items than a template can hold (e.g. 11 portfolio items mapped
    to a 3-up card template). Overflow that slot expansion absorbs (column
    units, headings, text, images) doesn't count.
    """
    expanded = _expand_slots(template_data, overrides)
    available_keys = {slot["key"] for slot in enumerate_slots(expanded["template"])}
    return sorted(key for key in overrides if key not in available_keys)
