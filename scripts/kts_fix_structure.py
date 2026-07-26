"""Structural cleanup pass for the Keys to Success home page content.

Two audit checks were failing on the published page:

  inline-styles     — style="" attributes on the two Photo Band instances
                      (which also shared duplicate component ids), the join
                      CTA section, and the CTA float image.
  responsive-images — every <img> was plain, with no <picture>/srcset wrapper.

This script rewrites artifacts/keys-to-success/pages/home/content.json to:

  1. Uniquify the two Photo Band instances (kts-hero-* / kts-prepare-*) so no
     two components share an id, and lift every inline style into a per-id rule
     in the top-level ``styles`` array (the styleJSON render path emits those
     as a <style> block in contentHtml).
  2. Wrap every content image whose asset has responsive variants in the
     image-box > image-frame > picture structure, preserving the image's
     original kts-* / rounded / ring / width classes on the inner <img>.

Idempotent-ish: re-running after a successful pass is a no-op for inline
styles (none remain) and skips already-wrapped images.
"""

from __future__ import annotations

import json
from pathlib import Path

from vanjaro_cli.migration.picture import build_picture_box, is_picture_box

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "artifacts" / "keys-to-success"
CONTENT = SITE / "pages" / "home" / "content.json"
MANIFEST = SITE / "asset-manifest.json"

# The two Photo Band instances both ship id "tpl-pb-s1" and identical child
# ids — uniquify by instance so per-id style rules stay distinct.
PHOTO_BAND_PREFIXES = ["kts-hero", "kts-prepare"]

# Class the wrapper div already represents; keep it off the inner <img>.
WRAPPER_CLASS = "image-box"


def _id_rule(component_id: str, declarations: dict[str, str]) -> dict:
    """GrapesJS style rule targeting a component by id (renders as #id{...})."""
    return {
        "selectors": [
            {
                "name": component_id,
                "label": component_id,
                "type": 2,
                "active": True,
                "private": True,
                "protected": False,
            }
        ],
        "style": declarations,
    }


def _parse_inline_style(style: str) -> dict[str, str]:
    declarations: dict[str, str] = {}
    for chunk in style.split(";"):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        prop, _, value = chunk.partition(":")
        declarations[prop.strip()] = value.strip()
    return declarations


def _class_names(component: dict) -> list[str]:
    names: list[str] = []
    for entry in component.get("classes") or []:
        if isinstance(entry, dict) and entry.get("name"):
            names.append(entry["name"])
        elif isinstance(entry, str):
            names.append(entry)
    return names


def _rewrite_ids(component: dict, old_prefix: str, new_prefix: str) -> None:
    attributes = component.get("attributes")
    if isinstance(attributes, dict):
        cid = attributes.get("id")
        if isinstance(cid, str) and cid.startswith(old_prefix):
            attributes["id"] = new_prefix + cid[len(old_prefix):]
    for child in component.get("components", []) or []:
        _rewrite_ids(child, old_prefix, new_prefix)


def uniquify_photo_bands(components: list[dict]) -> None:
    """Give each Photo Band instance a distinct id namespace."""
    seen = 0
    for component in components:
        attributes = component.get("attributes") or {}
        if component.get("type") == "section" and attributes.get("id") == "tpl-pb-s1":
            prefix = PHOTO_BAND_PREFIXES[seen] if seen < len(PHOTO_BAND_PREFIXES) else f"kts-pb{seen}"
            _rewrite_ids(component, "tpl-pb-", f"{prefix}-")
            attributes["id"] = f"{prefix}-band"
            component["attributes"] = attributes
            seen += 1


def extract_inline_styles(component: dict, styles: list[dict]) -> None:
    """Move every non-image inline style into a per-id rule in ``styles``.

    Images are handled by the wrapping pass so the CTA float lands on the
    wrapper rather than the inner <img>.
    """
    if component.get("type") != "image":
        attributes = component.get("attributes")
        if isinstance(attributes, dict) and attributes.get("style"):
            component_id = attributes.get("id")
            if component_id:
                styles.append(_id_rule(component_id, _parse_inline_style(attributes["style"])))
                del attributes["style"]
    for child in component.get("components", []) or []:
        extract_inline_styles(child, styles)


def _merged_inner_classes(original: list[str]) -> list[dict]:
    names = [name for name in original if name != WRAPPER_CLASS]
    for required in ("vj-image", "img-fluid"):
        if required not in names:
            names.append(required)
    return [{"name": name, "active": False} for name in names]


def wrap_images(
    components: list[dict],
    variants_by_path: dict[str, list],
    styles: list[dict],
    float_wrapper_seq: list[int],
) -> None:
    """Replace plain image children with picture-box trees, preserving classes."""
    for index, child in enumerate(components):
        if not isinstance(child, dict):
            continue
        if child.get("type") == "image" and not is_picture_box(child):
            attributes = child.get("attributes") or {}
            src = attributes.get("src", "")
            variants = variants_by_path.get(src.split("?", 1)[0])
            if variants:
                original_classes = _class_names(child)
                inline_style = attributes.get("style")
                box = build_picture_box(child, src, variants)
                if box is not None:
                    inner = box["components"][0]["components"][0]["components"][-1]
                    inner["classes"] = _merged_inner_classes(original_classes)
                    # build_picture_box copies every non-src/id attribute onto the
                    # inner <img>, including any inline style — drop it so no image
                    # keeps a style="" attribute.
                    inner.get("attributes", {}).pop("style", None)
                    if inline_style:
                        # The CTA float belongs on the wrapper so body text wraps
                        # around the whole picture, not just the <img>.
                        float_wrapper_seq[0] += 1
                        wrapper_id = f"kts-float-img{float_wrapper_seq[0]}"
                        box["attributes"] = {"id": wrapper_id}
                        styles.append(_id_rule(wrapper_id, _parse_inline_style(inline_style)))
                    components[index] = box
                    continue
        wrap_images(child.get("components", []) or [], variants_by_path, styles, float_wrapper_seq)


def main() -> None:
    content = json.loads(CONTENT.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    variants_by_path = {
        entry["stripped_url"]: entry["variants"]
        for entry in manifest
        if entry.get("stripped_url") and entry.get("variants")
    }

    components = content["components"]
    styles = content.setdefault("styles", [])

    uniquify_photo_bands(components)
    for component in components:
        extract_inline_styles(component, styles)
    wrap_images(components, variants_by_path, styles, [0])

    CONTENT.write_text(json.dumps(content, indent=2), encoding="utf-8")

    wrapped = sum(1 for _ in _iter_pictures(components))
    print(f"styles rules: {len(styles)}")
    print(f"picture-box wrappers: {wrapped}")


def _iter_pictures(components: list[dict]):
    for component in components:
        if isinstance(component, dict):
            if component.get("type") == "picture-box" or component.get("tagName") == "picture":
                yield component
            yield from _iter_pictures(component.get("components", []) or [])


if __name__ == "__main__":
    main()
