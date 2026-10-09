"""RT-37 — expected-side text colour, card fills, photo darkening, and wording."""

from __future__ import annotations

from vanjaro_cli.design.fidelity_color import ColorRole
from vanjaro_cli.design.fidelity_copy import BODY_WEIGHT, HEADLINE_WEIGHT
from vanjaro_cli.design.fidelity_extraction import observe_expected_section
from vanjaro_cli.design.models import (
    BreakpointName,
    ContentElement,
    ContentKind,
    EvidenceStatus,
    LayoutKind,
    LayoutObservation,
    ObservationMethod,
    Provenance,
    ResponsiveObservation,
    Section,
    SourceKind,
    StyleObservation,
    StyleProperty,
    StyleSet,
    Viewport,
)

FIGMA_API = Provenance(source_kind=SourceKind.FIGMA, method=ObservationMethod.API)
HTML_RENDERED = Provenance(source_kind=SourceKind.LIVE_HTML, method=ObservationMethod.RENDERED)


def _element(
    key: str,
    order: int,
    kind: ContentKind,
    value: object = "Copy",
    *,
    color: str | None = None,
    figma: bool = True,
    style: StyleSet | None = None,
) -> ContentElement:
    attributes = {"text_color": color} if color else {}
    return ContentElement(
        id=key,
        order=order,
        kind=kind,
        role="body",
        value=value,  # type: ignore[arg-type]
        attributes=attributes,
        style=style or StyleSet(),
        provenance=[FIGMA_API if figma else HTML_RENDERED],
        confidence=1,
    )


def _section(
    content: list[ContentElement] | None = None,
    *,
    metadata: dict | None = None,
    style: StyleSet | None = None,
    responsive: list[ResponsiveObservation] | None = None,
) -> Section:
    return Section(
        id="home.section.1",
        order=0,
        semantic_role="class_cards",
        role_confidence=1,
        candidate_roles=[],
        layout=LayoutObservation(kind=LayoutKind.GRID, contained=True, columns=3),
        content=content or [],
        groups=[],
        style=style or StyleSet(),
        responsive=responsive or [],
        decorative_layers=[],
        interactions=[],
        provenance=[],
        metadata=metadata or {},
    )


def _observe(section: Section, breakpoint: BreakpointName = BreakpointName.DESKTOP):
    return observe_expected_section(section, {}, breakpoint)


def _style(prop: StyleProperty, value: object) -> StyleSet:
    return StyleSet(observations=[StyleObservation(property=prop, value=value)])


# -- text colour --


def test_the_colour_filling_the_most_characters_is_the_sections_text_colour() -> None:
    observation = _observe(
        _section(
            [
                _element("a", 0, ContentKind.HEADING, "Our Classes", color="#f0709d"),
                _element("b", 1, ContentKind.TEXT, "A long paragraph of body copy here", color="#ffffff"),
                _element("c", 2, ContentKind.TEXT, "More body copy of about the same length", color="#ffffff"),
            ]
        )
    )

    assert observation.palette.get(ColorRole.TEXT) == "#ffffff"


def test_equal_weights_resolve_the_same_way_every_time() -> None:
    elements = [
        _element("a", 0, ContentKind.TEXT, "Same size", color="#222222"),
        _element("b", 1, ContentKind.TEXT, "Same size", color="#ffffff"),
    ]

    first = _observe(_section(elements)).palette.get(ColorRole.TEXT)
    second = _observe(_section(list(reversed(elements)))).palette.get(ColorRole.TEXT)

    assert first == second == "#ffffff"


def test_a_buttons_label_colour_belongs_to_the_accent_role_not_the_text_role() -> None:
    observation = _observe(
        _section(
            [
                _element("a", 0, ContentKind.TEXT, "Body", color="#222222"),
                _element("b", 1, ContentKind.BUTTON, "Learn More About Everything We Do", color="#ffffff"),
            ]
        )
    )

    assert observation.palette.get(ColorRole.TEXT) == "#222222"


def test_a_stated_section_text_colour_wins_over_the_text_fills() -> None:
    observation = _observe(
        _section(
            [_element("a", 0, ContentKind.TEXT, "Body", color="#222222")],
            style=_style(StyleProperty.TEXT_COLOR, "#abcdef"),
        )
    )

    assert observation.palette.get(ColorRole.TEXT) == "#abcdef"


def test_text_without_a_measured_figma_fill_leaves_the_text_colour_unmeasured() -> None:
    no_fill = _observe(_section([_element("a", 0, ContentKind.TEXT, "Body")]))
    not_figma = _observe(
        _section([_element("a", 0, ContentKind.TEXT, "Body", color="#222222", figma=False)])
    )
    unreadable = _observe(
        _section([_element("a", 0, ContentKind.TEXT, "Body", color="not-a-colour")])
    )

    for observation in (no_fill, not_figma, unreadable):
        assert observation.palette.get(ColorRole.TEXT) is None


# -- card fills and photo darkening --


def test_card_fills_are_read_in_the_order_figma_listed_them() -> None:
    metadata = {
        "surface_fills": [
            {"color": "#f0709d", "node_id": "1:1"},
            {"color": "#FDBB2C", "node_id": "1:2"},
            {"color": "oops", "node_id": "1:3"},
            "not a record",
        ]
    }

    observation = _observe(_section(metadata=metadata))

    assert observation.palette.surfaces == ("#f0709d", "#FDBB2C")


def test_no_recorded_cards_means_the_design_states_none() -> None:
    assert _observe(_section()).palette.surfaces is None
    assert _observe(_section(metadata={"surface_fills": []})).palette.surfaces is None
    assert _observe(_section(metadata={"surface_fills": "x"})).palette.surfaces is None


def test_the_recorded_darkening_layer_is_read_with_its_colour_and_opacity() -> None:
    metadata = {"background_overlay": {"color": "#000000", "opacity": 0.4, "node_id": "1:2"}}

    overlay = _observe(_section(metadata=metadata)).palette.overlay

    assert overlay is not None
    assert (overlay.present, overlay.color, overlay.opacity) == (True, "#000000", 0.4)


def test_a_darkening_layer_that_cannot_be_read_is_left_out() -> None:
    for record in (
        {"color": "#000000", "opacity": 1.4},
        {"color": "#000000", "opacity": True},
        {"color": "#000000", "opacity": "0.4"},
        {"color": "nope", "opacity": 0.4},
        {"opacity": 0.4},
        "x",
    ):
        assert _observe(_section(metadata={"background_overlay": record})).palette.overlay is None


# -- wording --


def test_headings_and_stat_figures_weigh_more_than_other_copy() -> None:
    observation = _observe(
        _section(
            [
                _element("a", 0, ContentKind.HEADING, "Our Classes"),
                _element("b", 1, ContentKind.STAT, "80+"),
                _element("c", 2, ContentKind.TEXT, "Body"),
                _element("d", 3, ContentKind.BUTTON, "Learn More"),
                _element("e", 4, ContentKind.LINK, "Home"),
                _element("f", 5, ContentKind.LIST_ITEM, "Item"),
                _element("g", 6, ContentKind.QUOTE, "Quote"),
            ]
        )
    )

    assert [(line.text, line.weight) for line in observation.wording.expected] == [
        ("Our Classes", HEADLINE_WEIGHT),
        ("80+", HEADLINE_WEIGHT),
        ("Body", BODY_WEIGHT),
        ("Learn More", BODY_WEIGHT),
        ("Home", BODY_WEIGHT),
        ("Item", BODY_WEIGHT),
        ("Quote", BODY_WEIGHT),
    ]
    assert observation.wording.rendered is None


def test_lines_follow_the_design_order_and_collapse_whitespace() -> None:
    observation = _observe(
        _section(
            [
                _element("b", 1, ContentKind.TEXT, "Second"),
                _element("a", 0, ContentKind.HEADING, "Happy \n  Students"),
            ]
        )
    )

    assert [line.text for line in observation.wording.expected] == ["Happy Students", "Second"]


def test_media_forms_and_values_that_are_not_text_state_no_copy() -> None:
    observation = _observe(
        _section(
            [
                _element("a", 0, ContentKind.IMAGE, "image-ref"),
                _element("b", 1, ContentKind.VIDEO, "video-ref"),
                _element("c", 2, ContentKind.FORM_PLACEHOLDER, "Contact form"),
                _element("d", 3, ContentKind.OTHER, "Something"),
                _element("e", 4, ContentKind.TEXT, None),
                _element("f", 5, ContentKind.TEXT, 42),
                _element("g", 6, ContentKind.TEXT, "   "),
            ]
        )
    )

    assert observation.wording.expected == ()


def test_text_the_design_hides_is_not_copy_a_visitor_was_meant_to_see() -> None:
    observation = _observe(
        _section(
            [
                _element("a", 0, ContentKind.TEXT, "Shown"),
                _element("b", 1, ContentKind.TEXT, "Menu drawer", style=_style(StyleProperty.DISPLAY, "none")),
                _element("c", 2, ContentKind.TEXT, "Skip link", style=_style(StyleProperty.VISIBILITY, "hidden")),
            ]
        )
    )

    assert [line.text for line in observation.wording.expected] == ["Shown"]


def test_a_section_hidden_at_a_breakpoint_states_no_copy_there() -> None:
    hidden = ResponsiveObservation(
        breakpoint=BreakpointName.MOBILE,
        viewport=Viewport(width=390, height=844),
        status=EvidenceStatus.OBSERVED,
        hidden=True,
    )
    section = _section([_element("a", 0, ContentKind.HEADING, "Promo")], responsive=[hidden])

    assert _observe(section, BreakpointName.MOBILE).wording.expected == ()
    assert [line.text for line in _observe(section, BreakpointName.DESKTOP).wording.expected] == ["Promo"]


def test_sample_text_is_not_copy_because_the_build_must_leave_it_out() -> None:
    observation = _observe(
        _section(
            [
                _element("a", 0, ContentKind.TEXT, "Lorem ipsum dolor sit amet, consectetur"),
                _element("b", 1, ContentKind.TEXT, "Put your actual text here. Lorem  Ipsum is simply"),
                _element("c", 2, ContentKind.LINK, "https://example.com/contact"),
                _element("d", 3, ContentKind.TEXT, "Real copy"),
            ]
        )
    )

    assert [line.text for line in observation.wording.expected] == ["Real copy"]


def test_the_sample_text_vocabulary_matches_the_planners() -> None:
    from vanjaro_cli.design import planner
    from vanjaro_cli.design.fidelity_copy import PLACEHOLDER_COPY

    assert PLACEHOLDER_COPY.pattern == planner._PLACEHOLDER_RE.pattern
    assert PLACEHOLDER_COPY.flags == planner._PLACEHOLDER_RE.flags
