"""Coverage for blog/article card semantic retention (category/body/byline).

`enrich_section_from_static_dom` used to fold a blog card's category label,
excerpt, and byline into one `body` list, even though the catalog's
`Cards/blog-post-cards-4up` template already owns distinct `item.tag`,
`item.body`, and `item.meta` slots for them (`vanjaro_cli/design/
html_card_fields.py` is the focused classifier that now tells them apart).
These tests cover the maintained scenarios beyond the root acceptance file
(`artifacts/test_article_semantics_independent.py`, not owned here): explicit
itemprop evidence, negative/ambiguous and misleading-class cases, mixed
descendant content, multiple same-role values, cross-card isolation,
determinism, the unaffected plain-card path, and two structurally different
fixtures run through the full HTML adapter -> planner -> GrapesJS pipeline.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from vanjaro_cli.design.html_adapter import design_document_from_html
from vanjaro_cli.design.html_ownership import enrich_section_from_static_dom
from vanjaro_cli.design.planner import emit_library_plan, plan_design_document
from vanjaro_cli.design.template_catalog import load_template_catalog
from vanjaro_cli.utils.block_compose import (
    apply_overrides,
    check_overflow,
    enumerate_slots,
    find_template,
)


def _provenance() -> dict:
    return {
        "source_kind": "live_html",
        "method": "static",
        "source_url": "https://agency.example/",
        "css_selector": "section",
    }


def _blog_section(cards_html: str, *, heading: str = "Journal") -> dict:
    section = {
        "id": "home.blog",
        "semantic_role": "blog_cards",
        "layout": {},
        "content": [],
        "groups": [],
        "responsive": [],
    }
    enrich_section_from_static_dom(
        section,
        f"<section><h2>{heading}</h2>{cards_html}</section>",
        source_url="https://agency.example/",
        assets={},
        provenance=_provenance(),
    )
    return section


def _values(section: dict, item: dict, field: str) -> list[str]:
    ids = item["fields"].get(field, [])
    ids = ids if isinstance(ids, list) else [ids]
    content = {element["id"]: element["value"] for element in section["content"]}
    return [content[element_id] for element_id in ids]


# ---------------------------------------------------------------------------
# Explicit itemprop evidence (the root acceptance file already covers class
# tokens and rel="tag"; this fills in the schema.org microdata markers).
# ---------------------------------------------------------------------------


def test_itemprop_evidence_preserves_category_and_author_ownership() -> None:
    cards = "".join(
        "<article>"
        f"<img src='/{i}.jpg'><h3>Story {i}</h3>"
        f"<p itemprop='articleSection'>Field Notes {i}</p>"
        f"<p>A dispatch about the release cycle for entry {i}.</p>"
        f"<p itemprop='author'>Byline {i}</p>"
        "</article>"
        for i in range(2)
    )
    section = _blog_section(cards)
    items = section["groups"][0]["items"]
    assert len(items) == 2
    for i, item in enumerate(items):
        assert _values(section, item, "tag") == [f"Field Notes {i}"]
        assert _values(section, item, "body") == [f"A dispatch about the release cycle for entry {i}."]
        assert _values(section, item, "meta") == [f"Byline {i}"]


# ---------------------------------------------------------------------------
# Negative: ambiguous, style-only, and misleading-class evidence must never
# relabel a paragraph away from body.
# ---------------------------------------------------------------------------


def test_style_only_and_misleading_classes_are_not_semantic_evidence() -> None:
    cards = "".join(
        "<article>"
        f"<img src='/{i}.jpg'><h3>Story {i}</h3>"
        # "vj-category" and "kts-meta-panel" are site-specific/prefixed
        # tokens, not the recognized markers, and "metadata" must not match
        # "meta" by substring.
        f"<p class='vj-category'>Topic {i}</p>"
        f"<p class='metadata'>Notes {i}</p>"
        f"<p class='text-muted'>By Writer {i}</p>"
        "</article>"
        for i in range(2)
    )
    section = _blog_section(cards)
    for i, item in enumerate(section["groups"][0]["items"]):
        assert _values(section, item, "body") == [
            f"Topic {i}", f"Notes {i}", f"By Writer {i}",
        ]
        assert not _values(section, item, "tag")
        assert not _values(section, item, "meta")


def test_mixed_descendant_evidence_does_not_relabel_the_whole_paragraph() -> None:
    """A paragraph that nests a `rel="tag"` link or an author span alongside
    its own prose is not a pure category/byline paragraph — the mixed
    content must stay body, per the same rule `_is_only_a_link` already
    applies to call-to-action anchors."""

    cards = "".join(
        "<article>"
        f"<img src='/{i}.jpg'><h3>Story {i}</h3>"
        f"<p>Filed under <a rel='tag' href='/t/{i}'>Topic {i}</a> this week.</p>"
        f"<p>Reported by <span itemprop='author'>Writer {i}</span> on site.</p>"
        "</article>"
        for i in range(2)
    )
    section = _blog_section(cards)
    for i, item in enumerate(section["groups"][0]["items"]):
        assert _values(section, item, "body") == [
            f"Filed under Topic {i} this week.",
            f"Reported by Writer {i} on site.",
        ]
        assert not _values(section, item, "tag")
        assert not _values(section, item, "meta")


# ---------------------------------------------------------------------------
# Multiple same-role values stay lists, in document order, never joined.
# ---------------------------------------------------------------------------


def test_multiple_same_role_values_remain_an_ordered_list() -> None:
    cards = "".join(
        "<article>"
        f"<img src='/{i}.jpg'><h3>Story {i}</h3>"
        f"<p class='category'>Design {i}</p>"
        f"<p class='category'>Culture {i}</p>"
        f"<p>Excerpt {i}</p>"
        f"<p class='byline'>Writer A {i}</p>"
        f"<p class='byline'>Writer B {i}</p>"
        "</article>"
        for i in range(2)
    )
    section = _blog_section(cards)
    for i, item in enumerate(section["groups"][0]["items"]):
        assert _values(section, item, "tag") == [f"Design {i}", f"Culture {i}"]
        assert _values(section, item, "body") == [f"Excerpt {i}"]
        assert _values(section, item, "meta") == [f"Writer A {i}", f"Writer B {i}"]


# ---------------------------------------------------------------------------
# Cross-card isolation: values and group membership never shift between
# cards, even when every card carries every field.
# ---------------------------------------------------------------------------


def test_per_card_ownership_never_shifts_values_across_cards() -> None:
    cards = "".join(
        "<article>"
        f"<img src='/{i}.jpg'><h3>Story {i}</h3>"
        f"<p class='category'>Category {i}</p>"
        f"<p>Excerpt body number {i}.</p>"
        f"<p class='byline'>Byline {i}</p>"
        "</article>"
        for i in range(4)
    )
    section = _blog_section(cards)
    items = section["groups"][0]["items"]
    group_id = section["groups"][0]["id"]
    assert len(items) == 4
    for i, item in enumerate(items):
        assert _values(section, item, "tag") == [f"Category {i}"]
        assert _values(section, item, "body") == [f"Excerpt body number {i}."]
        assert _values(section, item, "meta") == [f"Byline {i}"]
    element_group_ids = {
        element["id"]: element["group_id"] for element in section["content"]
    }
    for item in items:
        for field in ("tag", "body", "meta", "media", "title"):
            for element_id in (
                item["fields"][field]
                if isinstance(item["fields"][field], list)
                else [item["fields"][field]]
            ):
                assert element_group_ids[element_id] == group_id


# ---------------------------------------------------------------------------
# Old standalone dates keep their preserved fallback behavior.
# ---------------------------------------------------------------------------


def test_a_standalone_date_still_reads_as_tag_with_no_stronger_evidence() -> None:
    cards = "".join(
        f"<article><img src='/{i}.jpg'><h3>Story {i}</h3>"
        f"<p>Nov {13 + i}, 2017</p><p>Excerpt {i}</p></article>"
        for i in range(3)
    )
    section = _blog_section(cards)
    for i, item in enumerate(section["groups"][0]["items"]):
        assert _values(section, item, "tag") == [f"Nov {13 + i}, 2017"]
        assert _values(section, item, "body") == [f"Excerpt {i}"]
        assert not _values(section, item, "meta")


def test_an_explicit_category_and_a_date_both_arrive_without_duplication() -> None:
    """Explicit evidence does not suppress the date reading, and neither
    paragraph is dropped or counted twice."""

    section = _blog_section(
        "<article><img src='/0.jpg'><h3>Story</h3>"
        "<p>Nov 13, 2017</p>"
        "<p class='category'>Design</p>"
        "<p>Excerpt copy.</p>"
        "</article>"
    )
    item = section["groups"][0]["items"][0]
    assert _values(section, item, "tag") == ["Nov 13, 2017", "Design"]
    assert _values(section, item, "body") == ["Excerpt copy."]


# ---------------------------------------------------------------------------
# Plain feature/gallery cards are unaffected by this classifier.
# ---------------------------------------------------------------------------


def test_feature_cards_keep_the_prior_undifferentiated_body_behavior() -> None:
    section = {
        "id": "home.services",
        "semantic_role": "feature_cards",
        "layout": {},
        "content": [],
        "groups": [],
        "responsive": [],
    }
    enrich_section_from_static_dom(
        section,
        "<section><h2>Services</h2>"
        "<article><img src='/1.jpg'><h3>Strategy</h3>"
        "<p class='category'>Consulting</p>"
        "<p>Plan the work.</p>"
        "<p class='byline'>Led by Jordan</p>"
        "</article>"
        "<article><img src='/2.jpg'><h3>Design</h3>"
        "<p class='category'>Consulting</p>"
        "<p>Shape the experience.</p>"
        "<p class='byline'>Led by Morgan</p>"
        "</article>"
        "</section>",
        source_url="https://agency.example/",
        assets={},
        provenance=_provenance(),
    )
    item = section["groups"][0]["items"][0]
    assert set(item["fields"]) == {"media", "title", "body"}
    assert _values(section, item, "body") == ["Consulting", "Plan the work.", "Led by Jordan"]


# ---------------------------------------------------------------------------
# Deterministic repeated extraction.
# ---------------------------------------------------------------------------


def test_repeated_extraction_is_deterministic() -> None:
    cards_html = "".join(
        "<article>"
        f"<img src='/{i}.jpg'><h3>Story {i}</h3>"
        f"<p class='category'>Category {i}</p>"
        f"<p>Excerpt {i}</p>"
        f"<p class='byline'>Writer {i}</p>"
        "</article>"
        for i in range(3)
    )
    first = _blog_section(cards_html)
    second = _blog_section(cards_html)
    assert first == second


# ---------------------------------------------------------------------------
# End-to-end: HTML adapter -> production planner -> composed native GrapesJS
# values, for two structurally different generic article fixtures, using the
# existing template catalog.
# ---------------------------------------------------------------------------


def _composed_values(html: str, *, source_url: str, title: str) -> dict[str, str]:
    """Run the full HTML adapter -> planner -> compose pipeline and read back
    the *actual* content of the resulting native GrapesJS component tree.

    This is offline composition, not browser rendering: `apply_overrides`
    deep-copies the template and mutates its component tree's `content`
    fields in place, and `enumerate_slots` reads those same fields back out.
    Returning the requested override map here instead would only prove the
    plan *asked* for the right values, not that the composed tree *has*
    them -- the two can diverge if composition drops or corrupts content.
    """
    document = design_document_from_html(
        html, source_url, title=title, captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    assets = [
        asset.model_copy(update={"local_path": f"/Portals/0/e2e/{asset.id}.bin", "missing_reason": None})
        for asset in document.assets
    ]
    document = document.model_copy(update={"assets": assets})
    catalog = load_template_catalog()
    plan = plan_design_document(document, catalog=catalog)
    entries = [entry for entry in plan.entries if entry.source_section_id.endswith(".1")]
    assert entries and not entries[0].match.blocking, (
        "generic article fixture unexpectedly blocked from the catalog's "
        "blog card templates; this is a limitation of that fixture, not "
        "evidence the classifier itself misbehaved"
    )
    library_plan = emit_library_plan(plan)
    entry = next(item for item in library_plan if item["key"] == entries[0].source_section_id)
    template = find_template(entry["template"])
    assert check_overflow(template, entry["overrides"]) == []
    composed = apply_overrides(template, entry["overrides"])
    return {slot["key"]: slot["value"] for slot in enumerate_slots(composed["template"])}


_TEXT_SLOT_KEY = re.compile(r"^text_\d+$")


def _composed_text_values(html: str, *, source_url: str, title: str) -> list[str]:
    """The composed tree's ``text`` slot values, in document order.

    Slot numbering (`text_1`, `text_2`, ...) is not stable across fixtures --
    `apply_overrides` prunes explicitly-empty slots before renumbering, so a
    fixed key like `text_2` can point at a different card field depending on
    what else the template contributes. Document order is the only thing the
    per-card (category, excerpt, byline) grouping can rely on.
    """
    composed_values = _composed_values(html, source_url=source_url, title=title)
    return [value for key, value in composed_values.items() if _TEXT_SLOT_KEY.match(key)]


def _class_marked_card(i: int) -> str:
    return (
        f"<div class='list-post'><img src='/journal-{i}.jpg' alt='Post {i}'>"
        f"<h3>Article Headline Number {i}</h3>"
        f"<p class='category'>Category {i}</p>"
        f"<p>This is a much longer excerpt paragraph describing the article "
        f"content in detail for card number {i}.</p>"
        f"<p class='byline'>By Writer {i}</p>"
        "</div>"
    )


def _microdata_marked_card(i: int) -> str:
    return (
        f"<div class='post-item'><img src='/field-notes-{i}.jpg' alt='Post {i}'>"
        f"<h4>Field Notes Entry {i}</h4>"
        f"<p><a rel='tag' href='/topics/{i}'>Topic {i}</a></p>"
        f"<p>Field reporting from the studio floor covers what shipped this "
        f"week in release {i}.</p>"
        f"<p itemprop='author'>Reporter {i}</p>"
        "</div>"
    )


def test_end_to_end_class_marked_fixture_binds_distinct_native_slots() -> None:
    html = (
        "<html><body><section><h2>Journal</h2>"
        + "".join(_class_marked_card(i) for i in range(4))
        + "</section></body></html>"
    )
    text_values = _composed_text_values(html, source_url="https://example.test/journal", title="Journal")
    assert len(text_values) == 12  # 4 cards x (category, excerpt, byline)

    for i in range(4):
        tag, body, meta = text_values[i * 3 : i * 3 + 3]
        assert tag == f"Category {i}"
        assert body == (
            f"This is a much longer excerpt paragraph describing the article "
            f"content in detail for card number {i}."
        )
        assert meta == f"By Writer {i}"
        # Distinct slots, not the same value smeared across all three.
        assert len({tag, body, meta}) == 3


def test_end_to_end_microdata_marked_fixture_binds_distinct_native_slots() -> None:
    html = (
        "<html><body><section><h2>Field Notes</h2>"
        + "".join(_microdata_marked_card(i) for i in range(4))
        + "</section></body></html>"
    )
    text_values = _composed_text_values(
        html, source_url="https://example.test/field-notes", title="Field Notes"
    )
    assert len(text_values) == 12  # 4 cards x (category, excerpt, byline)

    for i in range(4):
        tag, body, meta = text_values[i * 3 : i * 3 + 3]
        assert tag == f"Topic {i}"
        assert body == (
            f"Field reporting from the studio floor covers what shipped this "
            f"week in release {i}."
        )
        assert meta == f"Reporter {i}"
        assert len({tag, body, meta}) == 3


# ---------------------------------------------------------------------------
# Conflicting markers across vocabularies (itemprop vs. class) are the same
# "reused label, not evidence" refusal `_paragraph_role` applies to two
# colliding class tokens; this covers it for a mixed-vocabulary collision.
# ---------------------------------------------------------------------------


def test_conflicting_itemprop_and_class_markers_remain_body() -> None:
    cards = "".join(
        "<article>"
        f"<img src='/{i}.jpg'><h3>Story {i}</h3>"
        f"<p itemprop='articleSection' class='byline'>Shared Label {i}</p>"
        f"<p>Excerpt {i}</p>"
        "</article>"
        for i in range(2)
    )
    section = _blog_section(cards)
    for i, item in enumerate(section["groups"][0]["items"]):
        assert _values(section, item, "body") == [f"Shared Label {i}", f"Excerpt {i}"]
        assert not _values(section, item, "tag")
        assert not _values(section, item, "meta")


# ---------------------------------------------------------------------------
# An unmarked, multi-paragraph card has no honest way to fill the template's
# distinct tag/body/meta slots, so the planner must keep it a blocking match
# rather than silently composing a "successful" plan that drops paragraphs.
# ---------------------------------------------------------------------------


def _ambiguous_overflow_card(i: int) -> str:
    return (
        f"<div class='list-post'><img src='/overflow-{i}.jpg' alt='Post {i}'>"
        f"<h3>Unmarked Roundup Entry {i}</h3>"
        f"<p>Topic {i}</p>"
        f"<p>First unmarked paragraph describing the roundup for entry {i} "
        f"in detail.</p>"
        f"<p>Second unmarked paragraph adding more detail about entry {i} "
        f"that the card has no distinct slot for.</p>"
        f"<p>By Writer {i}</p>"
        "</div>"
    )


def test_ambiguous_multi_paragraph_article_overflow_remains_blocked() -> None:
    html = (
        "<html><body><section><h2>Roundup</h2>"
        + "".join(_ambiguous_overflow_card(i) for i in range(4))
        + "</section></body></html>"
    )
    document = design_document_from_html(
        html, "https://example.test/roundup", title="Roundup",
        captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assets = [
        asset.model_copy(update={"local_path": f"/Portals/0/e2e/{asset.id}.bin", "missing_reason": None})
        for asset in document.assets
    ]
    document = document.model_copy(update={"assets": assets})
    catalog = load_template_catalog()
    plan = plan_design_document(document, catalog=catalog)
    entries = [entry for entry in plan.entries if entry.source_section_id.endswith(".1")]
    assert entries and entries[0].match.blocking, (
        "an unmarked, multi-paragraph card must remain a blocking match, "
        "not a silently truncated success"
    )
    key = entries[0].source_section_id
    library_plan = emit_library_plan(plan)
    assert not any(item["key"] == key for item in library_plan), (
        "a blocking match must not still surface a composed library entry "
        "for the same section"
    )
