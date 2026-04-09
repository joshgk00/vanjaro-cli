#!/usr/bin/env python3
"""Validate a Vanjaro block template JSON file against structural and semantic rules."""

import json
import sys
from pathlib import Path

VALID_CATEGORIES = {"Heroes", "Content", "Cards", "Testimonials", "CTAs", "Lists", "Media", "Navigation"}

REQUIRED_CLASSES = {
    "section": ["vj-section"],
    "grid": [],  # container OR container-fluid checked separately
    "row": ["row"],
    "heading": ["vj-heading"],
    "text": ["vj-text"],
    "button": ["btn"],
    "icon": ["icon-box", "vj-icon"],
    "image": ["image-box", "vj-image", "img-fluid"],
    "link": ["vj-link"],
    "list": ["list-box"],
    "spacer": ["spacer"],
    "divider": ["vj-divider"],
    "video": ["video-box"],
    "carousel": ["carousel"],
    "image-gallery": ["vj-image-gallery"],
}

STYLE_PRESETS = {
    "heading": "head-style-",
    "text": "paragraph-style-",
    "button": "button-style-",
}

LEAF_TYPES = {"heading", "text", "button", "icon", "image", "link", "list", "spacer", "divider", "video", "carousel", "image-gallery"}
CONTENT_TYPES = {"heading", "text", "button"}


def get_class_names(component):
    return [c["name"] for c in component.get("classes", [])]


def validate_class_format(component, path, errors):
    for i, cls in enumerate(component.get("classes", [])):
        if not isinstance(cls, dict):
            errors.append(f"{path}.classes[{i}]: Must be an object, got {type(cls).__name__}")
            continue
        if "name" not in cls:
            errors.append(f'{path}.classes[{i}]: Missing "name" field')
        if "active" not in cls:
            errors.append(f'{path}.classes[{i}]: Missing "active" field')
        elif cls["active"] is not False:
            errors.append(f'{path}.classes[{i}]: "active" must be false (boolean), got {cls["active"]!r}')

    names = get_class_names(component)
    seen = set()
    for name in names:
        if name in seen:
            errors.append(f"{path}: Duplicate class '{name}'")
        seen.add(name)


def validate_required_classes(component, path, errors):
    comp_type = component.get("type", "")
    names = get_class_names(component)

    if comp_type in REQUIRED_CLASSES:
        for req in REQUIRED_CLASSES[comp_type]:
            if req not in names:
                errors.append(f"{path}: type '{comp_type}' missing required class '{req}'")

    if comp_type == "grid":
        if "container" not in names and "container-fluid" not in names:
            errors.append(f"{path}: type 'grid' must have 'container' or 'container-fluid' class")

    if comp_type == "column":
        has_col = any(n.startswith("col-") or n == "col" for n in names)
        if not has_col:
            errors.append(f"{path}: type 'column' must have at least one col-* class")
        has_col_12 = "col-12" in names
        if not has_col_12:
            errors.append(f"{path}: type 'column' should include 'col-12' for mobile responsiveness")


def validate_style_presets(component, path, errors):
    comp_type = component.get("type", "")
    if comp_type not in STYLE_PRESETS:
        return
    prefix = STYLE_PRESETS[comp_type]
    names = get_class_names(component)
    preset_classes = [n for n in names if n.startswith(prefix)]
    if not preset_classes:
        errors.append(f"{path}: type '{comp_type}' missing style preset (e.g., '{prefix}1')")
    elif len(preset_classes) > 1:
        errors.append(f"{path}: type '{comp_type}' has multiple style presets: {preset_classes}")


def validate_attributes(component, path, errors):
    comp_type = component.get("type", "")
    attrs = component.get("attributes")
    if attrs is None:
        errors.append(f"{path}: type '{comp_type}' missing 'attributes' object (Vanjaro requires attributes.id on every component)")
    elif not isinstance(attrs, dict):
        errors.append(f"{path}: 'attributes' must be an object")
    elif "id" not in attrs or not attrs["id"]:
        errors.append(f"{path}: type '{comp_type}' missing 'attributes.id' (Vanjaro's renderer crashes on null reference without it)")

    if comp_type == "button":
        if attrs and attrs.get("role") != "button":
            errors.append(f"{path}: type 'button' should have attributes.role = 'button'")
        if attrs and "href" not in attrs:
            errors.append(f"{path}: type 'button' should have attributes.href (use '#' as default)")
        tag = component.get("tagName")
        if tag != "a":
            errors.append(f"{path}: type 'button' should have tagName 'a', got '{tag}'")


def validate_content_field(component, path, errors):
    comp_type = component.get("type", "")
    if comp_type in CONTENT_TYPES:
        content = component.get("content", "")
        if not content or not content.strip():
            errors.append(f"{path}: type '{comp_type}' must have non-empty 'content' field")


def validate_nesting(component, path, parent_type, errors):
    comp_type = component.get("type", "")

    if comp_type == "section" and parent_type is not None:
        errors.append(f"{path}: 'section' must be the root element, found nested under '{parent_type}'")

    if comp_type == "grid" and parent_type != "section":
        errors.append(f"{path}: 'grid' must be a direct child of 'section', found under '{parent_type}'")

    if comp_type == "row" and parent_type not in ("grid", "column"):
        errors.append(f"{path}: 'row' must be a direct child of 'grid' or 'column' (sub-grid), found under '{parent_type}'")

    if comp_type == "column" and parent_type != "row":
        errors.append(f"{path}: 'column' must be a direct child of 'row', found under '{parent_type}'")

    if comp_type in LEAF_TYPES and parent_type not in ("column", "link", None):
        # link can wrap leaves too
        if parent_type in ("section", "grid", "row"):
            errors.append(f"{path}: leaf type '{comp_type}' cannot be a direct child of '{parent_type}' (must be inside a column)")


def validate_component(component, path, parent_type, errors):
    if not isinstance(component, dict):
        errors.append(f"{path}: Component must be an object")
        return

    comp_type = component.get("type")
    if not comp_type:
        errors.append(f"{path}: Missing 'type' field")
        return

    validate_class_format(component, path, errors)
    validate_required_classes(component, path, errors)
    validate_style_presets(component, path, errors)
    validate_attributes(component, path, errors)
    validate_content_field(component, path, errors)
    validate_nesting(component, path, parent_type, errors)

    for i, child in enumerate(component.get("components", [])):
        validate_component(child, f"{path}.components[{i}]", comp_type, errors)


def validate_template_file(filepath):
    errors = []
    warnings = []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        errors.append(f"Invalid JSON: {e}")
        return errors, warnings
    except FileNotFoundError:
        errors.append(f"File not found: {filepath}")
        return errors, warnings

    # Top-level field checks
    for field in ("name", "category", "description", "template", "styles"):
        if field not in data:
            errors.append(f"Missing required top-level field: '{field}'")

    if "name" in data and not data["name"].strip():
        errors.append("'name' must not be empty")

    if "category" in data:
        if data["category"] not in VALID_CATEGORIES:
            errors.append(f"Invalid category '{data['category']}'. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}")

    if "description" in data and not data["description"].strip():
        errors.append("'description' must not be empty")

    if "styles" in data and not isinstance(data["styles"], list):
        errors.append("'styles' must be an array")

    # Template validation
    if "template" in data:
        template = data["template"]
        if not isinstance(template, dict):
            errors.append("'template' must be an object (the root section component)")
        else:
            root_type = template.get("type")
            if root_type != "section":
                errors.append(f"Root element must be type 'section', got '{root_type}'")
            validate_component(template, "template", None, errors)

    # Filename check
    filename = Path(filepath).stem
    if filename != filename.lower() or " " in filename or "_" in filename:
        warnings.append(f"Filename '{filename}' should be kebab-case (lowercase, hyphens only)")

    return errors, warnings


def main():
    if len(sys.argv) < 2:
        print("Usage: validate_template.py <template.json>")
        sys.exit(1)

    filepath = sys.argv[1]
    errors, warnings = validate_template_file(filepath)

    if warnings:
        print(f"\n  WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"    [!] {w}")

    if errors:
        print(f"\n  ERRORS ({len(errors)}):")
        for e in errors:
            print(f"    [x] {e}")
        print(f"\n  RESULT: FAILED ({len(errors)} errors, {len(warnings)} warnings)")
        sys.exit(1)
    else:
        print(f"\n  RESULT: PASSED (0 errors, {len(warnings)} warnings)")
        sys.exit(0)


if __name__ == "__main__":
    main()
