"""Wrap a plain GrapesJS image component into a responsive ``<picture>`` tree.

Hand-built Vanjaro sites serve every image as ``<picture>`` with a multi-width
WebP ``srcset`` drawn from ``/Portals/0/Images/.versions/``. Migrated images
arrive as plain ``<img>``. The ``/AIAsset/Upload`` endpoint already returns the
generated variants (one per width step, in both the original format and WebP),
which the asset manifest now records. This module turns a plain image component
plus its variant list into the ``image-box > image-frame > picture`` structure
the Vanjaro renderer emits for responsive images.

The wrapper mirrors what a hand-authored Vanjaro page stores:

    image-box (div)
      image-frame (span)
        picture (picture)
          source[type=image/webp]  (webp variants, srcset with width descriptors)
          source                    (original-format variants)
          image.vj-image.img-fluid  (original url, loading=lazy)
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "is_picture_box",
    "build_picture_box",
]

WEBP_VARIANT_TYPE = "webp"
IMAGE_VARIANT_TYPE = "image"


def is_picture_box(component: dict[str, Any]) -> bool:
    """Report whether a component is already a ``picture-box`` wrapper.

    Used to keep the wrapping idempotent — an image that already lives inside
    a picture structure (re-run of the rewrite stage, hand-authored content)
    must not be wrapped a second time.
    """
    if component.get("type") in ("image-box", "picture-box", "image-frame"):
        return True
    if component.get("tagName") == "picture":
        return True
    return False


def _srcset(variants: list[dict[str, Any]], variant_type: str) -> str:
    """Build a ``srcset`` string for variants of one type, with width descriptors.

    Variants without a usable ``url``/``width`` pair are skipped. Output is
    ordered by ascending width so the browser's smallest-first selection works.
    """
    entries: list[tuple[int, str]] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        if variant.get("type") != variant_type:
            continue
        url = variant.get("url")
        width = variant.get("width")
        if not isinstance(url, str) or not url:
            continue
        if not isinstance(width, int) or width <= 0:
            continue
        entries.append((width, url))

    entries.sort(key=lambda item: item[0])
    return ", ".join(f"{url} {width}w" for width, url in entries)


def _source(srcset: str, mime_type: str | None) -> dict[str, Any]:
    attributes: dict[str, Any] = {"srcset": srcset, "sizes": "100vw"}
    if mime_type:
        # type must precede srcset so the browser can skip unsupported formats
        # without parsing the candidate list — matches the hand-authored order.
        attributes = {"type": mime_type, "srcset": srcset, "sizes": "100vw"}
    return {
        "type": "source",
        "classes": [{"name": "source", "active": False}],
        "attributes": attributes,
    }


def build_picture_box(
    image_component: dict[str, Any],
    original_url: str,
    variants: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Build a ``picture-box`` tree from an image component and its variants.

    ``original_url`` is the rewritten Vanjaro portal URL for the full-size
    image. ``variants`` is the manifest's variant array (``[{"url", "width",
    "type"}, ...]``). The inner image preserves the source component's ``alt``
    and any extra non-src attributes, and carries the ``vj-image``/``img-fluid``
    classes plus ``loading="lazy"`` like the hand-authored markup.

    Returns ``None`` when there are no usable variants — the caller should
    leave the plain image untouched in that case (external URLs, SVGs, upload
    failures all land here).
    """
    webp_srcset = _srcset(variants, WEBP_VARIANT_TYPE)
    original_srcset = _srcset(variants, IMAGE_VARIANT_TYPE)
    if not webp_srcset and not original_srcset:
        return None

    sources: list[dict[str, Any]] = []
    if webp_srcset:
        sources.append(_source(webp_srcset, "image/webp"))
    if original_srcset:
        sources.append(_source(original_srcset, None))

    source_attributes = image_component.get("attributes")
    preserved_attributes: dict[str, Any] = {}
    if isinstance(source_attributes, dict):
        for key, value in source_attributes.items():
            if key in ("src", "id"):
                continue
            preserved_attributes[key] = value

    inner_image = {
        "type": "image",
        "classes": [
            {"name": "vj-image", "active": False},
            {"name": "img-fluid", "active": False},
        ],
        "attributes": {
            "loading": "lazy",
            "src": original_url,
            **preserved_attributes,
        },
    }

    picture = {
        "tagName": "picture",
        "type": "picture-box",
        "classes": [{"name": "picture-box", "active": False}],
        "components": [*sources, inner_image],
    }

    image_frame = {
        "type": "image-frame",
        "classes": [{"name": "image-frame", "active": False}],
        "components": [picture],
    }

    return {
        "type": "image-box",
        "components": [image_frame],
    }
