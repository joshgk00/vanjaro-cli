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

_WRAPPER_CLASSES = frozenset({"image-box", "image-frame", "picture-box"})
_INNER_IMAGE_CLASSES = frozenset({"vj-image", "img-fluid"})


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


def _source_classes(image_component: dict[str, Any]) -> list[dict[str, Any]]:
    """The source image's own classes, minus the wrapper and base ones.

    ``rounded-circle`` or a margin utility on the template image has to stay on
    the ``<img>`` that actually renders; the wrapper types and the two classes
    every inner image already carries would only duplicate or confuse.
    """
    names = [
        entry["name"]
        for entry in image_component.get("classes") or []
        if isinstance(entry, dict) and isinstance(entry.get("name"), str) and entry["name"]
    ]
    return [
        {"name": name, "active": False}
        for name in dict.fromkeys(names)
        if name not in _WRAPPER_CLASSES and name not in _INNER_IMAGE_CLASSES
    ]


def build_picture_box(
    image_component: dict[str, Any],
    original_url: str,
    variants: list[dict[str, Any]],
    *,
    keep_source_identity: bool = False,
) -> dict[str, Any] | None:
    """Build a ``picture-box`` tree from an image component and its variants.

    ``original_url`` is the rewritten Vanjaro portal URL for the full-size
    image. ``variants`` is the manifest's variant array (``[{"url", "width",
    "type"}, ...]``). The inner image preserves the source component's ``alt``
    and any extra non-src attributes, and carries the ``vj-image``/``img-fluid``
    classes plus ``loading="lazy"`` like the hand-authored markup.

    The source image's own ``id`` and extra classes are dropped unless
    ``keep_source_identity`` is set. A style rule or a template class aimed at
    the original ``<img>`` (a circular crop on a team photo) must follow it
    into the wrapper, or the wrapped image renders unstyled.

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
    dropped_attributes = ("src",) if keep_source_identity else ("src", "id")
    preserved_attributes: dict[str, Any] = {}
    if isinstance(source_attributes, dict):
        for key, value in source_attributes.items():
            if key in dropped_attributes:
                continue
            preserved_attributes[key] = value

    inner_image = {
        "type": "image",
        "classes": [
            {"name": "vj-image", "active": False},
            {"name": "img-fluid", "active": False},
            *(_source_classes(image_component) if keep_source_identity else []),
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
