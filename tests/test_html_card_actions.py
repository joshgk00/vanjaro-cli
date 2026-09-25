"""Maintained coverage for standalone card-action retention.

`html_ownership.enrich_section_from_static_dom`'s repeated-card branch built
each item from its media, heading, and paragraphs only. A standalone visible
control beside a card's description -- `<a class="btn" href="/learn-more">
Learn more</a>` -- had no owner anywhere in the extraction and vanished
before planning ever saw it, even though the image sitting beside it kept
its own destination. See `docs/agency-card-action-retention-contract.md` and
the confirmed baseline in `artifacts/test_card_action_retention_independent.py`
(read-only and authoritative), which already exercises: distinct and same
image/action targets, a missing first action, five-card expansion, two
actions in one card, an action-only paragraph, a linked-heading/image-only
negative, and an unsafe destination.

This file covers the maintained scenarios beyond that baseline: a bare
standalone action carrying no Bootstrap class, a mixed-prose paragraph that
keeps its inline link rather than becoming a second action, a metadata
(category/byline) anchor, a whole-card anchor, and a source-neutral (no HTML
at all) unsafe action proving the safety boundary lives in shared planning
rather than as an HTML-only special case. It also independently exercises
the confirmed baseline's core shapes (distinct/same targets, a missing first
action, expansion, and multiple actions) through this file's own fixtures,
per the task's test contract.

Every test that composes a page runs the real chain: `design_document_from_html`
-> `split_global_sections` -> `plan_design_document` -> `emit_library_plan` ->
`apply_overrides`, with local asset paths standing in for acquisition -- no
uploads, no network, no portal.
"""

from __future__ import annotations

from datetime import datetime, timezone

from vanjaro_cli.design.global_plan import split_global_sections
from vanjaro_cli.design.html_adapter import design_document_from_html
from vanjaro_cli.design.models import (
    Alignment,
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
    bind_section,
    emit_library_plan,
    plan_design_document,
    validate_composition_plan,
    PlanningError,
)
from vanjaro_cli.design.template_catalog import load_template_catalog
from vanjaro_cli.utils.block_compose import apply_overrides, find_template


# ---------------------------------------------------------------------------
# Shared HTML-chain fixture helpers
# ---------------------------------------------------------------------------


def walk(node, ancestors=()):
    yield node, ancestors
    for child in node.get("components", []):
        if isinstance(child, dict):
            yield from walk(child, (*ancestors, node))


_DEFAULT_LABEL = object()


def _card(
    i: int,
    *,
    action: object = _DEFAULT_LABEL,
    action_href: str | None = None,
    wrap_in_paragraph: bool = False,
    class_hint: str = "btn",
    extra: str = "",
) -> str:
    """One generic service card: a linked image, a heading, a description.

    `action` is the visible label of a standalone control (default
    ``f"Service {i}"``), or `None` to omit it entirely. `action_href`
    defaults to a destination distinct from the card's own image link,
    matching the contract's requirement that an action's label and
    destination stay distinct from the image's even when a caller chooses
    to make them equal.
    """

    body = (
        f'<a href="/image/{i}"><img src="/images/{i}.jpg" alt="Service {i}"></a>'
        f"<h3>Service identity {i}</h3><p>Description for service {i}.</p>"
    )
    if action is not None:
        label = f"Service {i}" if action is _DEFAULT_LABEL else action
        href = action_href if action_href is not None else f"/action/{i}"
        class_attr = f' class="{class_hint}"' if class_hint else ""
        anchor = f'<a{class_attr} href="{href}">{label}</a>'
        body += f"<p>{anchor}</p>" if wrap_in_paragraph else anchor
    body += extra
    return f'<article class="service-item">{body}</article>'


def _cards_document(cards_html: str, *, count: int):
    html = (
        '<html><body><header class="site-header"><nav><a href="/">Home</a>'
        '<a href="/services">Services</a></nav></header><section id="dnn_content">'
        '<div id="dnn_ServicesPane" class="Pane"><h2>Our Services</h2>'
        + cards_html
        + "</div></section>"
        '<footer class="site-footer"><p>Copyright 2026.</p></footer></body></html>'
    )
    raw = design_document_from_html(
        html, "https://maintained.example/", captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    raw = raw.model_copy(
        update={
            "assets": [
                asset.model_copy(update={"local_path": f"assets/{i}.jpg"})
                for i, asset in enumerate(raw.assets)
            ]
        }
    )
    body, _, issues = split_global_sections(raw)
    assert not issues
    sections = [s for p in body.pages for s in p.sections if s.semantic_role == "feature_cards"]
    assert len(sections) == 1, "Fixture must exercise real service-card extraction"
    section = sections[0]
    assert len(section.groups[0].items) == count
    return body, section


def action_elements(section, item):
    refs = item.fields.get("action", [])
    refs = refs if isinstance(refs, list) else [refs]
    by_id = {element.id: element for element in section.content}
    return [by_id[ref] for ref in refs]


def body_values(section, item):
    refs = item.fields.get("body", [])
    refs = refs if isinstance(refs, list) else [refs]
    by_id = {element.id: element for element in section.content}
    return [by_id[ref].value for ref in refs]


def compose(body, section):
    plan = plan_design_document(body)
    assert not validate_composition_plan(plan)
    entry = next(e for e in plan.entries if e.source_section_id == section.id)
    assert not entry.match.blocking, entry.warnings
    library = next(item for item in emit_library_plan(plan) if item["key"] == section.id)
    return apply_overrides(find_template(library["template"]), library["overrides"])["template"]


def assert_native_action(root, index: int, href: str, label: str) -> None:
    matches = [
        (node, ancestors)
        for node, ancestors in walk(root)
        if node.get("type") in {"button", "link"} and node.get("content") == label
    ]
    assert len(matches) == 1, f"Expected exactly one native control for {label!r}"
    node, ancestors = matches[0]
    assert node.get("attributes", {}).get("href") == href
    column = next(a for a in reversed(ancestors) if a.get("type") == "column")
    headings = [n.get("content") for n, _ in walk(column) if n.get("type") == "heading"]
    assert f"Service identity {index}" in headings, "Action landed in the wrong card"


# ---------------------------------------------------------------------------
# Baseline shapes, exercised independently of the root acceptance file
# ---------------------------------------------------------------------------


def test_distinct_image_and_action_targets_both_survive_as_native_controls():
    cards = "".join(_card(i) for i in range(3))
    body, section = _cards_document(cards, count=3)
    for i, item in enumerate(section.groups[0].items):
        actions = action_elements(section, item)
        assert len(actions) == 1
        assert actions[0].value == f"Service {i}"
        assert actions[0].attributes["href"] == f"/action/{i}"
    root = compose(body, section)
    for i in range(3):
        assert_native_action(root, i, f"/action/{i}", f"Service {i}")


def test_same_image_and_action_destination_still_yields_two_controls():
    cards = "".join(_card(i, action_href=f"/image/{i}") for i in range(3))
    body, section = _cards_document(cards, count=3)
    root = compose(body, section)
    for i in range(3):
        assert_native_action(root, i, f"/image/{i}", f"Service {i}")
        linked_images = [
            (n, ancestors)
            for n, ancestors in walk(root)
            if n.get("type") == "image" and n.get("attributes", {}).get("alt") == f"Service {i}"
        ]
        assert len(linked_images) == 1
        _, ancestors = linked_images[0]
        owner = next(a for a in reversed(ancestors) if a.get("type") == "link")
        assert owner["attributes"]["href"] == f"/image/{i}"


def test_missing_first_action_does_not_shift_ownership_to_the_first_card():
    cards = _card(0, action=None) + "".join(_card(i) for i in (1, 2))
    body, section = _cards_document(cards, count=3)
    assert not action_elements(section, section.groups[0].items[0])
    root = compose(body, section)
    assert not any(n.get("content") == "Service 0" for n, _ in walk(root))
    for i in (1, 2):
        assert_native_action(root, i, f"/action/{i}", f"Service {i}")


def test_actions_survive_repeat_expansion_past_the_template_default():
    cards = "".join(_card(i) for i in range(5))
    body, section = _cards_document(cards, count=5)
    root = compose(body, section)
    for i in range(5):
        assert_native_action(root, i, f"/action/{i}", f"Service {i}")


def test_two_actions_in_one_card_block_with_an_explicit_capacity_diagnostic():
    second = '<a class="btn" href="/second/0">Compare service 0</a>'
    cards = _card(0, extra=second) + "".join(_card(i) for i in (1, 2))
    body, section = _cards_document(cards, count=3)
    actions = action_elements(section, section.groups[0].items[0])
    assert [(a.value, a.attributes["href"]) for a in actions] == [
        ("Service 0", "/action/0"),
        ("Compare service 0", "/second/0"),
    ]
    plan = plan_design_document(body)
    entry = next(e for e in plan.entries if e.source_section_id == section.id)
    assert entry.match.blocking, "Feature Cards (3-up) owns one action slot per card"
    assert not any(item["key"] == section.id for item in emit_library_plan(plan))
    assert any("action" in str(w).lower() for w in entry.warnings)


def test_action_only_paragraph_is_not_also_emitted_as_body_copy():
    cards = "".join(_card(i, wrap_in_paragraph=True) for i in range(3))
    body, section = _cards_document(cards, count=3)
    for i, item in enumerate(section.groups[0].items):
        assert len(action_elements(section, item)) == 1
        assert body_values(section, item) == [f"Description for service {i}."]
    root = compose(body, section)
    for i in range(3):
        assert_native_action(root, i, f"/action/{i}", f"Service {i}")


# ---------------------------------------------------------------------------
# Additional maintained scenarios
# ---------------------------------------------------------------------------


def test_direct_standalone_action_without_bootstrap_classes_is_still_retained():
    cards = "".join(_card(i, class_hint="") for i in range(3))
    body, section = _cards_document(cards, count=3)
    for i, item in enumerate(section.groups[0].items):
        actions = action_elements(section, item)
        assert len(actions) == 1
        assert actions[0].value == f"Service {i}"
        assert actions[0].attributes["href"] == f"/action/{i}"
    root = compose(body, section)
    for i in range(3):
        assert_native_action(root, i, f"/action/{i}", f"Service {i}")


def test_mixed_prose_paragraph_keeps_its_prose_and_invents_no_action():
    cards = "".join(
        '<article class="service-item">'
        f'<a href="/image/{i}"><img src="/images/{i}.jpg" alt="Service {i}"></a>'
        f"<h3>Service identity {i}</h3>"
        f'<p>Read more about <a href="/details/{i}">our process</a> today.</p>'
        f'<a class="btn" href="/action/{i}">Explore service {i}</a>'
        "</article>"
        for i in range(2)
    )
    body, section = _cards_document(cards, count=2)
    for i, item in enumerate(section.groups[0].items):
        actions = action_elements(section, item)
        assert [a.value for a in actions] == [f"Explore service {i}"]
        assert body_values(section, item) == ["Read more about our process today."]
    root = compose(body, section)
    for i in range(2):
        assert_native_action(root, i, f"/action/{i}", f"Explore service {i}")
        assert not any(n.get("content") == "our process" for n, _ in walk(root))


def test_category_and_byline_anchors_are_not_invented_as_actions():
    cards = "".join(
        '<article class="service-item">'
        f'<a href="/image/{i}"><img src="/images/{i}.jpg" alt="Service {i}"></a>'
        f"<h3>Service identity {i}</h3>"
        f'<a class="category" href="/category/design-{i}">Design</a>'
        f"<p>Description for service {i}.</p>"
        f'<a rel="author" href="/author/{i}">Staff Writer</a>'
        f'<a class="btn" href="/action/{i}">Explore service {i}</a>'
        "</article>"
        for i in range(2)
    )
    body, section = _cards_document(cards, count=2)
    for i, item in enumerate(section.groups[0].items):
        actions = action_elements(section, item)
        assert [a.value for a in actions] == [f"Explore service {i}"]
    root = compose(body, section)
    for i in range(2):
        assert_native_action(root, i, f"/action/{i}", f"Explore service {i}")
        assert not any(n.get("content") == "Design" for n, _ in walk(root))
        assert not any(n.get("content") == "Staff Writer" for n, _ in walk(root))


def test_whole_card_anchor_does_not_invent_a_standalone_action():
    cards = "".join(
        '<article class="service-item"><a class="card-link" href="/service/{0}">'
        '<img src="/images/{0}.jpg" alt="Service {0}">'
        "<h3>Service identity {0}</h3>"
        "<p>Description for service {0}.</p></a></article>".format(i)
        for i in range(2)
    )
    body, section = _cards_document(cards, count=2)
    for item in section.groups[0].items:
        assert action_elements(section, item) == []
    # Title and body still arrive despite the wrapping anchor.
    for i, item in enumerate(section.groups[0].items):
        assert body_values(section, item) == [f"Description for service {i}."]


# ---------------------------------------------------------------------------
# Source-neutral safety: the boundary lives in shared planning, not HTML
# ---------------------------------------------------------------------------


def _manual_feature_section(*, href: str) -> Section:
    title = ContentElement(
        id="element-1",
        kind=ContentKind.HEADING,
        role="section_title",
        value="Our Services",
        order=0,
        provenance=[],
        confidence=1.0,
    )
    card_title = ContentElement(
        id="element-2",
        kind=ContentKind.HEADING,
        role="card_title",
        value="Service 1",
        order=1,
        provenance=[],
        confidence=1.0,
    )
    action = ContentElement(
        id="element-3",
        kind=ContentKind.BUTTON,
        role="primary_action",
        value="Explore service 1",
        attributes={"href": href},
        order=2,
        provenance=[],
        confidence=1.0,
    )
    return Section(
        id="home.services",
        order=0,
        semantic_role="feature_cards",
        role_confidence=1.0,
        candidate_roles=[],
        layout=LayoutObservation(
            kind=LayoutKind.GRID,
            contained=True,
            columns=3,
            media_position=MediaPosition.TOP,
            alignment=Alignment.LEFT,
        ),
        content=[title, card_title, action],
        groups=[
            RepeatGroup(
                id="cards",
                kind=RepeatGroupKind.CARD,
                items=[
                    RepeatGroupItem(
                        id="card-1",
                        fields={"title": card_title.id, "action": action.id},
                    )
                ],
            )
        ],
        style=StyleSet(),
        responsive=[],
        decorative_layers=[],
        interactions=[],
        provenance=[],
    )


def _manual_document(section: Section) -> DesignDocument:
    return DesignDocument(
        schema_version="1.0",
        source=DesignSource(
            kind=SourceKind.LIVE_HTML,
            identifier="https://maintained-manual.test",
            captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            adapter_version="1.0",
        ),
        tokens=DesignTokens(),
        assets=[],
        pages=[
            Page(
                id="home",
                source_reference="https://maintained-manual.test",
                title="Home",
                slug="",
                sections=[section],
                breakpoints=[],
                navigation_visibility=NavigationVisibility.VISIBLE,
                provenance=[],
            )
        ],
        warnings=[],
        analysis=DesignAnalysis(section_confidence_mean=1.0, unsupported_traits=[]),
    )


def test_source_neutral_manually_constructed_action_with_unsafe_href_blocks():
    """A hand-built section -- no HTML adapter involved at all -- proves the
    unsafe-href boundary is a planning concern shared by every button/link
    binding, not something wired up only inside the HTML card-action path."""

    entry = next(
        e for e in load_template_catalog() if e.name == "Feature Cards (3-up)"
    )
    with_disguise = " javascript:alert(1)"
    try:
        bind_section(_manual_feature_section(href=with_disguise), entry)
    except PlanningError as exc:
        assert any("unsafe" in issue.casefold() for issue in exc.issues)
    else:
        raise AssertionError("expected an unsafe destination to raise PlanningError")

    document = _manual_document(_manual_feature_section(href="javascript:alert(1)"))
    plan = plan_design_document(document)
    entry_plan = plan.entries[0]
    assert entry_plan.match.blocking
    assert any("unsafe" in warning.casefold() for warning in entry_plan.warnings)
    assert not emit_library_plan(plan)


def test_safe_relative_action_href_still_binds_normally():
    document = _manual_document(_manual_feature_section(href="/service-1"))
    plan = plan_design_document(document)
    entry_plan = plan.entries[0]
    assert not entry_plan.match.blocking
    library = emit_library_plan(plan)
    assert library
    composed = apply_overrides(find_template(library[0]["template"]), library[0]["overrides"])["template"]
    matches = [
        node
        for node, _ in walk(composed)
        if node.get("type") in {"button", "link"} and node.get("content") == "Explore service 1"
    ]
    assert len(matches) == 1
    assert matches[0]["attributes"]["href"] == "/service-1"
