"""Map crawler-extracted content dicts to block-template override keys.

The crawler writes per-section and global-element files with a ``content``
block shaped like ``{headings, paragraphs, buttons, images, list_items,
nav_items, ...}``. Block templates declare override slots keyed by type
and index (``heading_1``, ``text_1``, ``image_1_src``, ``list-item_1``,
etc.). This module bridges the two shapes so both ``migrate assemble-page``
(per-section composition) and ``migrate compose-global`` (header/footer
composition) can produce overrides from a crawler dict without
duplicating the mapping logic.
"""

from __future__ import annotations

__all__ = ["crawl_content_to_overrides"]


def crawl_content_to_overrides(content: dict, index_offset: int = 0) -> dict[str, str]:
    """Map a crawler-extracted content dict to block-template override keys.

    Maps all extracted content types to their template override slots:
      - headings   → heading_1, heading_2, ...
      - paragraphs → text_1, text_2, ...
      - blockquotes → text_N, N continuing right after the last paragraph
      - buttons    → button_1 / button_1_href, ...
      - images     → image_1_src / image_1_alt, ...
      - list_items → list-item_1, list-item_2, ...

    Works for any section-shaped content dict: page sections from
    ``pages/{slug}/section-*.json`` and global elements from
    ``global/header.json`` / ``global/footer.json`` use the same shape.

    ``index_offset`` shifts heading/text numbering only (not images, buttons,
    or list items). Some templates (e.g. Gallery (3-up)/(6-up)) put a leading
    section-title heading+text pair ahead of a repeating per-item group, so
    heading_1/text_1 belong to the section title rather than item 1 — while
    image_1 has no such leading counterpart. Content with no separate title
    of its own (one heading/paragraph per image) needs its heading/text
    indices shifted by 1 to land on the correct per-item slot instead of
    overwriting the section title. Callers detect this via the target
    template's slot shape; see ``_detect_heading_text_offset`` in
    ``migrate_assemble_cmd.py``.
    """
    overrides: dict[str, str] = {}

    headings = content.get("headings") or []
    if isinstance(headings, list):
        for position, heading in enumerate(headings, start=1):
            index = position + index_offset
            if isinstance(heading, str):
                overrides[f"heading_{index}"] = heading
            elif isinstance(heading, dict) and isinstance(heading.get("text"), str):
                overrides[f"heading_{index}"] = heading["text"]

    paragraphs = content.get("paragraphs") or []
    if isinstance(paragraphs, list):
        for position, paragraph in enumerate(paragraphs, start=1):
            index = position + index_offset
            if isinstance(paragraph, str):
                overrides[f"text_{index}"] = paragraph

    # Testimonial quotes usually crawl as <blockquote> elements rather than
    # <p> tags, landing in content.blockquotes instead of content.paragraphs.
    # Templates have no dedicated blockquote slot, so fold the quote text
    # into the same text_N sequence right after the paragraphs — but only
    # when a section-specific rescope (see _rescope_testimonial) hasn't
    # already copied the same quote into paragraphs, which would otherwise
    # ship the quote twice.
    blockquotes = content.get("blockquotes") or []
    if isinstance(blockquotes, list):
        paragraph_texts = {
            paragraph.strip() for paragraph in paragraphs if isinstance(paragraph, str)
        }
        next_index = len(paragraphs) + index_offset + 1
        for blockquote in blockquotes:
            if not isinstance(blockquote, dict) or not isinstance(blockquote.get("text"), str):
                continue
            text = blockquote["text"]
            if text.strip() in paragraph_texts:
                continue
            overrides[f"text_{next_index}"] = text
            next_index += 1

    buttons = content.get("buttons") or []
    if isinstance(buttons, list):
        for index, button in enumerate(buttons, start=1):
            if not isinstance(button, dict):
                continue
            text = button.get("text")
            href = button.get("href")
            if isinstance(text, str):
                overrides[f"button_{index}"] = text
            if isinstance(href, str):
                overrides[f"button_{index}_href"] = href

    images = content.get("images") or []
    if isinstance(images, list):
        for index, image in enumerate(images, start=1):
            if not isinstance(image, dict):
                continue
            src = image.get("src")
            alt = image.get("alt")
            if isinstance(src, str):
                overrides[f"image_{index}_src"] = src
            if isinstance(alt, str):
                overrides[f"image_{index}_alt"] = alt

    list_items = content.get("list_items") or []
    if isinstance(list_items, list):
        for index, item in enumerate(list_items, start=1):
            if isinstance(item, str):
                overrides[f"list-item_{index}"] = item

    return overrides
