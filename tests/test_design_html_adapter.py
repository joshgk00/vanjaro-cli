"""Focused tests for the live HTML and legacy Design Document adapter."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

from vanjaro_cli.design.html_adapter import (
    CANONICAL_VIEWPORTS,
    HtmlAdapterError,
    HtmlPageInput,
    RenderedPageObservation,
    RenderedSectionObservation,
    StylesheetCache,
    analyze_html_pages,
    capture_rendered_observations,
    convert_legacy_crawl,
    design_document_from_html,
)
from vanjaro_cli.design import html_adapter
from vanjaro_cli.design.models import BoundingBox, BreakpointName


CAPTURE_TIME = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _legacy_section(section_type: str, content: dict, template: str = "Template") -> dict:
    return {"type": section_type, "template": template, "content": content}


def _make_legacy_crawl(tmp_path: Path, sections: list[dict]) -> Path:
    entries = []
    for index, section in enumerate(sections, start=1):
        file_name = f"pages/home/section-{index:03d}-{section['type']}.json"
        _write_json(tmp_path / file_name, section)
        entries.append(
            {"file": file_name, "type": section["type"], "template": section["template"]}
        )
    _write_json(
        tmp_path / "site-inventory.json",
        {
            "source_url": "https://legacy.example/",
            "crawled_at": "2026-07-16T12:00:00+00:00",
            "pages": [
                {
                    "url": "https://legacy.example/",
                    "title": "Legacy Home",
                    "slug": "home",
                    "parent_slug": None,
                    "sections": entries,
                }
            ],
            "assets": {"manifest": "assets/manifest.json"},
            "global": {
                "header": "global/header.json",
                "footer": "global/footer.json",
            },
        },
    )
    _write_json(
        tmp_path / "assets" / "manifest.json",
        [
            {
                "source_url": "https://legacy.example/card-one.jpg",
                "local_file": "card-one.jpg",
                "content_type": "image/jpeg",
            }
        ],
    )
    _write_json(
        tmp_path / "design-tokens.json",
        {"brand_colors": ["#123456"], "fonts": ["Inter"]},
    )
    return tmp_path


def test_convert_legacy_crawl_maps_representative_sections_and_provenance(
    tmp_path: Path,
) -> None:
    root = _make_legacy_crawl(
        tmp_path,
        [
            _legacy_section(
                "hero",
                {
                    "headings": ["Welcome"],
                    "paragraphs": ["Introduction"],
                    "images": [],
                    "buttons": [{"text": "Start", "href": "/start"}],
                },
            ),
            _legacy_section(
                "cards",
                {
                    "headings": ["One", "Two"],
                    "paragraphs": ["First", "Second"],
                    "images": [
                        {"src": "https://legacy.example/card-one.jpg", "alt": "One"},
                        {"src": "https://legacy.example/card-two.jpg", "alt": "Two"},
                    ],
                    "buttons": [
                        {"text": "Read One", "href": "/one"},
                        {"text": "Read Two", "href": "/two"},
                    ],
                },
            ),
            _legacy_section(
                "gallery",
                {
                    "headings": [],
                    "paragraphs": [],
                    "images": [
                        {"src": "https://legacy.example/a.jpg", "alt": "A"},
                        {"src": "https://legacy.example/b.jpg", "alt": "B"},
                    ],
                },
            ),
            _legacy_section(
                "testimonial",
                {
                    "headings": ["Ada", "Grace"],
                    "paragraphs": ["Excellent", "Wonderful"],
                    "images": [],
                },
            ),
            _legacy_section(
                "pricing",
                {
                    "headings": ["Basic", "Pro"],
                    "paragraphs": ["$10", "$20"],
                    "images": [],
                },
            ),
            _legacy_section(
                "split",
                {
                    "headings": ["Our Story"],
                    "paragraphs": ["How it began"],
                    "images": [{"src": "https://legacy.example/story.jpg", "alt": ""}],
                },
                template="Split Media Reverse",
            ),
        ],
    )
    before = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*.json")
    }

    document = convert_legacy_crawl(root)

    assert document.source.kind.value == "legacy_sections"
    assert document.source.captured_at == CAPTURE_TIME
    assert document.source.metadata["global_artifacts"] == {
        "header": "global/header.json",
        "footer": "global/footer.json",
    }
    assert len(document.pages[0].sections) == 6
    cards = document.pages[0].sections[1]
    assert cards.semantic_role == "feature_cards"
    assert cards.groups[0].kind.value == "card"
    assert len(cards.groups[0].items) == 2
    first_fields = cards.groups[0].items[0].fields
    first_title_id = first_fields["title"]
    assert next(element for element in cards.content if element.id == first_title_id).value == "One"
    split = document.pages[0].sections[-1]
    assert split.layout.kind.value == "split"
    assert split.layout.media_position.value == "right"
    assert document.pages[0].provenance[0].method.value == "legacy"
    assert document.assets
    assert document.tokens.colors["brand_colors_1"].value == "#123456"
    after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*.json")}
    assert after == before


def test_convert_legacy_crawl_preserves_positional_action_gaps(tmp_path: Path) -> None:
    root = _make_legacy_crawl(
        tmp_path,
        [
            _legacy_section(
                "cards",
                {
                    "headings": ["One", "Two"],
                    "paragraphs": ["First", "Second"],
                    "images": [],
                    "buttons": [None, {"text": "Second Action", "href": "/two"}],
                    "links": [
                        {"text": "First Link", "href": "/one"},
                        {"text": "Second Link", "href": "/two-link"},
                    ],
                },
            )
        ],
    )

    group = convert_legacy_crawl(root).pages[0].sections[0].groups[0]

    first_action = group.items[0].fields["action"]
    second_actions = group.items[1].fields["action"]
    section = convert_legacy_crawl(root).pages[0].sections[0]
    assert next(element for element in section.content if element.id == first_action).value == "First Link"
    assert isinstance(second_actions, list)
    assert [
        next(element for element in section.content if element.id == element_id).value
        for element_id in second_actions
    ] == ["Second Action", "Second Link"]


def test_convert_legacy_crawl_warns_on_ambiguous_and_malformed_data(
    tmp_path: Path,
) -> None:
    root = _make_legacy_crawl(
        tmp_path,
        [
            _legacy_section(
                "cards",
                {
                    "headings": ["One", "Two", "Three"],
                    "paragraphs": ["Only one body"],
                    "images": [],
                },
            ),
            {"type": "content", "template": "Rich Text", "content": ["bad"]},
        ],
    )
    inventory = json.loads((root / "site-inventory.json").read_text(encoding="utf-8"))
    inventory["pages"][0]["sections"].append(
        {"file": "pages/home/missing.json", "type": "content", "template": "Rich Text"}
    )
    _write_json(root / "site-inventory.json", inventory)

    document = convert_legacy_crawl(root)

    codes = {warning.code for warning in document.warnings}
    assert "legacy_relationship_ambiguous" in codes
    assert "legacy_content_malformed" in codes
    assert "legacy_section_unreadable" in codes
    assert document.pages[0].sections[0].metadata["relationship_confidence"] == 0.6


def test_convert_legacy_crawl_rejects_invalid_inventory(tmp_path: Path) -> None:
    _write_json(tmp_path / "site-inventory.json", {"pages": []})

    with pytest.raises(HtmlAdapterError, match="missing source_url"):
        convert_legacy_crawl(tmp_path)


def test_static_html_produces_relationship_aware_document_and_excludes_chrome() -> None:
    html = """
    <html><head><title>Example</title></head><body>
      <header><nav><a href="/">Home</a></nav></header>
      <main>
        <section class="hero"><h1>Welcome</h1><p>Hello.</p><a class="btn" href="/start">Start</a></section>
        <section class="features">
          <div class="card"><h3>Fast</h3><p>Quick.</p><img src="/fast.jpg"></div>
          <div class="card"><h3>Safe</h3><p>Secure.</p><img src="/safe.jpg"></div>
          <div class="card"><h3>Fun</h3><p>Enjoyable.</p><img src="/fun.jpg"></div>
        </section>
      </main>
      <dialog><h2>Newsletter</h2><p>Not page content.</p></dialog>
      <footer>Copyright</footer>
    </body></html>
    """

    document = design_document_from_html(
        html, "https://example.com/", captured_at=CAPTURE_TIME
    )

    assert [section.semantic_role for section in document.pages[0].sections] == [
        "hero",
        "feature_cards",
    ]
    cards = document.pages[0].sections[1]
    assert len(cards.groups[0].items) == 3
    assert not any(element.value == "Newsletter" for section in document.pages[0].sections for element in section.content)
    assert {asset.source_url for asset in document.assets} == {
        "https://example.com/fast.jpg",
        "https://example.com/safe.jpg",
        "https://example.com/fun.jpg",
    }
    assert any(interaction.kind.value == "menu" for interaction in document.pages[0].sections[0].interactions)


def test_static_html_inventories_interactions_without_raw_form_or_script() -> None:
    html = """
    <html><body><main>
      <section class="accordion"><h2>FAQ</h2>
        <details><summary>Q1</summary><p>A1</p></details>
        <details><summary>Q2</summary><p>A2</p></details>
        <details><summary>Q3</summary><p>A3</p></details>
      </section>
      <section><div role="tablist"><button role="tab">One</button></div></section>
      <section><div class="carousel"><h3>Slide</h3></div></section>
      <section><video src="/movie.mp4"></video></section>
      <section class="contact"><form action="/submit">
        <label>Name<input name="name" required></label>
        <button type="submit">Send</button><script>steal()</script>
      </form></section>
      <section><button data-bs-toggle="modal">Open</button></section>
    </main></body></html>
    """

    document = design_document_from_html(html, "https://example.com/")

    interactions = {
        interaction.kind.value
        for section in document.pages[0].sections
        for interaction in section.interactions
    }
    assert {"accordion", "tabs", "carousel", "video_embed", "form", "modal_trigger"} <= interactions
    faq = document.pages[0].sections[0]
    assert len(faq.groups[0].items) == 3
    first_question_id = faq.groups[0].items[0].fields["title"]
    assert next(element for element in faq.content if element.id == first_question_id).value == "Q1"
    assert any(
        element.kind.value == "form_placeholder"
        for section in document.pages[0].sections
        for element in section.content
    )
    serialized = document.model_dump_json()
    assert "steal()" not in serialized
    assert "raw_scripts_copied\":false" in serialized
    assert any(warning.code == "unsupported_interaction" for warning in document.warnings)


def test_stylesheet_cache_fetches_shared_once_and_includes_page_specific_css() -> None:
    calls: list[str] = []
    css_by_url = {
        "https://example.com/shared.css": ".shared { color: #111111; }",
        "https://example.com/about.css": ".special { background-color: #224466; }",
    }

    def fetch(url: str) -> str:
        calls.append(url)
        return css_by_url[url]

    cache = StylesheetCache(fetch)
    pages = [
        HtmlPageInput(
            "https://example.com/",
            '<html><head><link rel="stylesheet" href="/shared.css"></head><body><main><section><h1>Home</h1></section></main></body></html>',
            title="Home",
            slug="home",
        ),
        HtmlPageInput(
            "https://example.com/about",
            '<html><head><link rel="stylesheet" href="/shared.css"><link rel="stylesheet" href="/about.css"></head><body><main><section class="special"><h1>About</h1></section></main></body></html>',
            title="About",
            slug="about",
        ),
    ]

    document = analyze_html_pages(
        pages, stylesheet_cache=cache, captured_at=CAPTURE_TIME
    )

    assert calls == [
        "https://example.com/shared.css",
        "https://example.com/about.css",
    ]
    assert cache.cached_urls == tuple(calls)
    about_style = {
        observation.property.value: observation.value
        for observation in document.pages[1].sections[0].style.observations
    }
    assert about_style["background_color"] == "#224466"


def test_stylesheet_failure_identifies_page_and_url_and_is_cached() -> None:
    calls = 0

    def failing_fetch(_url: str) -> str:
        nonlocal calls
        calls += 1
        raise ValueError("offline")

    cache = StylesheetCache(failing_fetch)
    html = '<html><head><link rel="stylesheet" href="/bad.css"></head><body><main><section><h1>X</h1></section></main></body></html>'
    pages = [
        HtmlPageInput("https://example.com/", html, title="Home", slug="home"),
        HtmlPageInput("https://example.com/about", html, title="About", slug="about"),
    ]

    document = analyze_html_pages(pages, stylesheet_cache=cache)

    assert calls == 1
    assert len(document.warnings) == 2
    assert all("https://example.com/bad.css" in warning.message for warning in document.warnings)
    assert {warning.path for warning in document.warnings} == {
        "https://example.com/",
        "https://example.com/about",
    }


class _FakePage:
    def __init__(self, width: int) -> None:
        self.width = width

    def evaluate(self, _expression: str) -> dict:
        return {
            "sections": [
                {
                    "selector": "#hero",
                    "bounds": {"x": 0, "y": 0, "width": self.width, "height": 500},
                    "hidden": False,
                    "styles": {
                        "background_color": "rgb(1, 2, 3)",
                        "column_count": 1,
                    },
                }
            ],
            "navigation_collapsed": self.width < 800,
        }


def test_capture_rendered_observations_preserves_partial_success() -> None:
    @contextmanager
    def session_factory(viewport: tuple[int, int]):
        if viewport[0] == 768:
            raise ValueError("tablet browser failed")
        yield _FakePage(viewport[0])

    result = capture_rendered_observations(
        "https://example.com/",
        session_factory=session_factory,
        render=lambda _page, _url, _timeout: (
            '<html><body><main><section id="hero"><h1>Hello</h1></section></main></body></html>'
        ),
    )

    assert [observation.breakpoint for observation in result.observations] == [
        BreakpointName.DESKTOP,
        BreakpointName.MOBILE,
    ]
    assert result.observations[1].navigation_collapsed is True
    assert len(result.warnings) == 1
    assert "tablet" in result.warnings[0].message


def test_rendered_styles_override_static_and_emit_responsive_deltas() -> None:
    html = """
    <html><head><style>.hero { background-color: #111111; }</style></head>
    <body><main><section class="hero"><h1>Hello</h1></section></main></body></html>
    """
    desktop = RenderedPageObservation(
        breakpoint=BreakpointName.DESKTOP,
        viewport=CANONICAL_VIEWPORTS[BreakpointName.DESKTOP],
        html=html,
        sections=(
            RenderedSectionObservation(
                selector=".hero",
                bounds=BoundingBox(x=0, y=0, width=1440, height=600),
                hidden=False,
                styles={"background_color": "rgb(34, 34, 34)", "column_count": 3},
            ),
        ),
        navigation_collapsed=False,
    )
    mobile = RenderedPageObservation(
        breakpoint=BreakpointName.MOBILE,
        viewport=CANONICAL_VIEWPORTS[BreakpointName.MOBILE],
        html=html,
        sections=(
            RenderedSectionObservation(
                selector=".hero",
                bounds=BoundingBox(x=0, y=0, width=390, height=700),
                hidden=False,
                styles={"background_color": "rgb(51, 51, 51)", "column_count": 1},
            ),
        ),
        navigation_collapsed=True,
    )

    document = design_document_from_html(
        html,
        "https://example.com/",
        css_text=".hero { background-color: #111111; }",
        rendered_observations=[desktop, mobile],
    )

    section = document.pages[0].sections[0]
    styles = {
        observation.property.value: observation.value
        for observation in section.style.observations
    }
    assert styles["background_color"] == "rgb(34, 34, 34)"
    assert section.provenance[0].method.value == "rendered"
    assert section.provenance[0].bounds.width == 1440
    assert [item.breakpoint for item in section.responsive] == [
        BreakpointName.DESKTOP,
        BreakpointName.MOBILE,
    ]
    mobile_delta = section.responsive[1]
    assert mobile_delta.layout_changes["columns"] == 1
    assert {
        observation.property.value: observation.value
        for observation in mobile_delta.style.observations
    }["background_color"] == "rgb(51, 51, 51)"
    assert document.pages[0].metadata["navigation_collapsed"] == {
        "desktop": False,
        "mobile": True,
    }


PAIRING_HTML = """
<html><head><title>Pairing</title></head>
<body>
  <header><nav id="site-nav"><a href="/">Home</a><a href="/about">About</a></nav></header>
  <main>
    <section id="hero"><h1>Find your north</h1><p>We build measured systems.</p></section>
    <section id="services"><h2>What we do</h2><p>Design, build, measure.</p></section>
    <section id="contact"><h2>Ready?</h2><a class="btn" href="/contact">Start</a></section>
  </main>
</body></html>
"""


def _pairing_section(selector: str, y: float) -> RenderedSectionObservation:
    return RenderedSectionObservation(
        selector=selector,
        bounds=BoundingBox(x=0.0, y=y, width=1440.0, height=200.0),
        hidden=False,
        styles={"background_color": "#101820"},
    )


def _desktop_observation(
    sections: tuple[RenderedSectionObservation, ...],
) -> RenderedPageObservation:
    return RenderedPageObservation(
        breakpoint=BreakpointName.DESKTOP,
        viewport=CANONICAL_VIEWPORTS[BreakpointName.DESKTOP],
        html=PAIRING_HTML,
        sections=sections,
    )


def _bounds_by_role(document) -> dict[str, float | None]:
    return {
        str(section.semantic_role): (
            section.provenance[0].bounds.y
            if section.provenance[0].bounds is not None
            else None
        )
        for section in document.pages[0].sections
    }


def test_rendered_evidence_pairs_by_identity_not_position() -> None:
    """The browser skips header content, so the lists differ in length.

    Pairing by position would put the hero's geometry on the nav and shift every
    later section onto its neighbour — a measurement of the wrong element that
    still looks like evidence.
    """

    document = design_document_from_html(
        PAIRING_HTML,
        "https://pairing.test/",
        captured_at=CAPTURE_TIME,
        rendered_observations=(
            _desktop_observation(
                (
                    _pairing_section("#contact", 700.0),
                    _pairing_section("#hero", 60.0),
                )
            ),
        ),
    )

    bounds = _bounds_by_role(document)
    assert bounds["hero"] == 60.0
    assert bounds["call_to_action"] == 700.0
    assert bounds["rich_text"] is None
    assert any(
        warning.code == "rendered_section_unmatched" for warning in document.warnings
    )


def test_equal_length_lists_still_pair_by_position_without_identity() -> None:
    document = design_document_from_html(
        PAIRING_HTML,
        "https://pairing.test/",
        captured_at=CAPTURE_TIME,
        rendered_observations=(
            _desktop_observation(
                tuple(
                    _pairing_section(f"rendered-section-{index + 1}", index * 100.0)
                    for index in range(4)
                )
            ),
        ),
    )

    # Four, not three: the nav is extracted as a section too, and position
    # pairing is only offered when the two lists are the same length.
    bounds = _bounds_by_role(document)
    assert bounds["navigation"] == 0.0
    assert bounds["hero"] == 100.0
    assert bounds["rich_text"] == 200.0
    assert bounds["call_to_action"] == 300.0


def test_unidentifiable_lists_of_different_lengths_attach_no_geometry() -> None:
    """Without identity and without matching counts there is no correspondence.

    Attaching geometry anyway would guess which rendered box belongs to which
    section, and a wrong box scores worse than an absent one.
    """

    document = design_document_from_html(
        PAIRING_HTML,
        "https://pairing.test/",
        captured_at=CAPTURE_TIME,
        rendered_observations=(
            _desktop_observation(
                (
                    _pairing_section("rendered-section-1", 0.0),
                    _pairing_section("rendered-section-2", 100.0),
                )
            ),
        ),
    )

    assert all(value is None for value in _bounds_by_role(document).values())
    assert any(
        warning.code == "rendered_section_unmatched" for warning in document.warnings
    )


def test_duplicate_rendered_selectors_are_not_used_for_pairing() -> None:
    document = design_document_from_html(
        PAIRING_HTML,
        "https://pairing.test/",
        captured_at=CAPTURE_TIME,
        rendered_observations=(
            _desktop_observation(
                (
                    _pairing_section("#hero", 60.0),
                    _pairing_section("#hero", 300.0),
                    _pairing_section("#contact", 700.0),
                )
            ),
        ),
    )

    bounds = _bounds_by_role(document)
    assert bounds["hero"] is None
    assert bounds["call_to_action"] == 700.0


TYPOGRAPHY_HTML = """
<html><head><title>Type</title></head><body><main>
  <section id="hero"><h1>Find your north</h1><p>First body copy.</p>
    <h2>Second heading</h2><p>Second body copy.</p></section>
</main></body></html>
"""


def _type_observation(samples: dict) -> RenderedPageObservation:
    return RenderedPageObservation(
        breakpoint=BreakpointName.DESKTOP,
        viewport=CANONICAL_VIEWPORTS[BreakpointName.DESKTOP],
        html=TYPOGRAPHY_HTML,
        sections=(
            RenderedSectionObservation(
                selector="#hero",
                bounds=BoundingBox(x=0.0, y=0.0, width=1440.0, height=400.0),
                hidden=False,
                styles={},
                typography=samples,
            ),
        ),
    )


def _font_props(element) -> dict[str, str]:
    return {
        observation.property.value: observation.value
        for observation in element.style.observations
    }


def _typography_document(samples: dict):
    return design_document_from_html(
        TYPOGRAPHY_HTML,
        "https://type.test/",
        captured_at=CAPTURE_TIME,
        rendered_observations=(_type_observation(samples),),
    )


SAMPLES = {
    "heading": {"font_family": "Inter", "font_size": "32px", "font_weight": "700"},
    "body": {"font_family": "Inter", "font_size": "16px", "font_weight": "400"},
}


def test_measured_fonts_reach_the_heading_and_body_elements() -> None:
    """The typography metric reads each element's own style, while a rendered
    crawl records computed values on the section box. Without this the design
    side has no type evidence and the dimension scores nothing."""

    document = _typography_document(SAMPLES)
    content = document.pages[0].sections[0].content
    heading = next(element for element in content if element.kind.value == "heading")
    body = next(element for element in content if element.kind.value == "text")

    assert _font_props(heading)["font_size"] == "32px"
    assert _font_props(heading)["font_weight"] == "700"
    assert _font_props(body)["font_size"] == "16px"


def test_at_most_one_element_of_each_kind_carries_the_sample() -> None:
    """`querySelector` returns the first match, so claiming the value for later
    elements would assert a measurement that was never taken."""

    document = _typography_document(SAMPLES)
    content = document.pages[0].sections[0].content
    stamped_kinds = [
        element.kind.value for element in content if element.style.observations
    ]

    assert sorted(stamped_kinds) == ["heading", "text"]
    assert len(stamped_kinds) == len(set(stamped_kinds))


def test_a_missing_sample_leaves_that_element_unstamped() -> None:
    document = _typography_document({"heading": SAMPLES["heading"]})
    content = document.pages[0].sections[0].content
    body = next(element for element in content if element.kind.value == "text")

    assert _font_props(body) == {}


def test_static_analysis_records_no_type_samples() -> None:
    document = design_document_from_html(
        TYPOGRAPHY_HTML, "https://type.test/", captured_at=CAPTURE_TIME
    )

    assert all(
        not element.style.observations
        for element in document.pages[0].sections[0].content
    )


def test_the_observation_script_measures_page_chrome() -> None:
    """The body query cannot reach a nav inside a header, so the design side
    carried no styles and no geometry for it: the nav scored on two of six
    dimensions while every body section scored five, and came out highest.

    The script itself only runs in a browser, so this pins the intent; the
    behaviour is verified against a live page in the progress log.
    """

    script = html_adapter._RENDERED_OBSERVATION_JS

    assert "'header, footer'" in script
    assert "body > nav" in script
    # Chrome is measured, but a dialog is still not a section.
    assert "dialog, [role=\"dialog\"]" in script


def test_the_observation_script_prefers_the_outermost_chrome_root() -> None:
    """The author's id sits on the header, and that is what pairing matches on.
    Taking the inner nav instead produced `rendered-section-N` and paired with
    nothing."""

    script = html_adapter._RENDERED_OBSERVATION_JS
    chrome_block = script[script.index("const chrome = []") :]

    assert "querySelectorAll('header, footer')" in chrome_block
    assert "!el.closest('header, footer')" in chrome_block


def test_both_scripts_measure_the_effective_background() -> None:
    """A transparent section still shows a painted colour — the nearest
    ancestor's. Reading the element's own value leaves background unmeasured on
    every section of a source that paints on `body`, which is absence of a
    decision, not absence of a colour."""

    from vanjaro_cli.design import fidelity_measure

    for script in (html_adapter._RENDERED_OBSERVATION_JS, fidelity_measure.MEASURE_SCRIPT):
        assert "effectiveBackground" in script
        assert "parentElement" in script
    # Nothing painted anywhere stays honestly unmeasured.
    assert "return null;" in html_adapter._RENDERED_OBSERVATION_JS


def test_the_analysis_script_samples_the_first_labelled_action() -> None:
    """An action with no label is not the call: a thumbnail wrapped in a link
    was reporting the page's default colours as the section's accent."""

    script = html_adapter._RENDERED_OBSERVATION_JS
    start = script.index("action: (() =>")
    block = script[start : start + 600]

    assert "querySelectorAll('a, button')" in block
    assert "textContent" in block, "the rendered side stopped requiring a label"
    assert "text_color:" in block


ACTION_HTML = """
<html><head><title>Action</title></head><body><main>
  <section id="cta"><h2>Ready?</h2>
    <a class="btn" href="/start">Start</a><a class="btn" href="/more">More</a></section>
</main></body></html>
"""


def _action_document(sample: dict):
    observation = RenderedPageObservation(
        breakpoint=BreakpointName.DESKTOP,
        viewport=CANONICAL_VIEWPORTS[BreakpointName.DESKTOP],
        html=ACTION_HTML,
        sections=(
            RenderedSectionObservation(
                selector="#cta",
                bounds=BoundingBox(x=0.0, y=0.0, width=1440.0, height=200.0),
                hidden=False,
                styles={},
                action=sample,
            ),
        ),
    )
    return design_document_from_html(
        ACTION_HTML,
        "https://action.test/",
        captured_at=CAPTURE_TIME,
        rendered_observations=(observation,),
    )


def test_the_measured_action_colour_reaches_the_first_action_element() -> None:
    document = _action_document(
        {"text_color": "#ffffff", "background_color": "#0b5ed7"}
    )
    actions = [
        element
        for element in document.pages[0].sections[0].content
        if element.kind.value in ("button", "link")
    ]

    assert actions
    stamped = {
        observation.property.value: observation.value
        for observation in actions[0].style.observations
    }
    assert stamped["text_color"] == "#ffffff"
    assert stamped["background_color"] == "#0b5ed7"


def test_only_the_first_action_element_carries_the_sample() -> None:
    document = _action_document({"text_color": "#ffffff"})
    stamped = [
        element
        for element in document.pages[0].sections[0].content
        if element.kind.value in ("button", "link") and element.style.observations
    ]

    assert len(stamped) == 1


def test_the_script_reports_stylesheets_a_file_render_cannot_resolve() -> None:
    """A saved page's root-relative sheets cannot resolve from file://, so the
    browser paints its own defaults and the evidence looks measured while
    describing nothing the author chose. On the real EDCA source that is 10
    stylesheets, and every rendered analysis before this reported none."""

    script = html_adapter._RENDERED_OBSERVATION_JS

    assert "unresolved_stylesheets" in script
    assert "location.protocol === 'file:'" in script
    # Protocol-relative URLs do resolve; only root-relative ones cannot.
    assert "!href.startsWith('//')" in script


def test_the_file_branch_cannot_rely_on_link_sheet() -> None:
    """A failed file:// load still yields a truthy `link.sheet` whose cssRules
    throw exactly as a legitimately cross-origin sheet's do, so on that
    transport only the address distinguishes failure. Over http `link.sheet` is
    a usable hint, which is why the branches differ."""

    script = html_adapter._RENDERED_OBSERVATION_JS
    block = script[script.index("unresolvedStylesheets = 0") :]
    file_branch = block[block.index("if (isFile)") : block.index("// Served over http")]
    # Comments in that branch discuss link.sheet; the assertion is about code.
    code = chr(10).join(
        line for line in file_branch.splitlines() if not line.strip().startswith("//")
    )

    assert "href.startsWith('/')" in code
    assert "link.sheet" not in code


def test_an_unresolved_stylesheet_warning_names_what_it_invalidates() -> None:
    from vanjaro_cli.design import html_adapter as adapter
    import inspect

    source = inspect.getsource(adapter.capture_rendered_observations)

    assert "rendered_stylesheets_unresolved" in source
    assert "colour, typography and spacing" in source


def test_serving_a_saved_page_gives_root_relative_assets_a_root(tmp_path: Path) -> None:
    """A root-relative stylesheet cannot resolve from file://; served over
    loopback it can. Proven end to end rather than asserted: file:// renders the
    browser's defaults, http:// renders the author's."""

    (tmp_path / "css").mkdir()
    (tmp_path / "css" / "site.css").write_text(
        "body{background:#123456;font-family:Georgia}\n#hero{background:#abcdef}\n",
        encoding="utf-8",
    )
    page = tmp_path / "index.html"
    page.write_text(
        '<!doctype html><html><head><link rel="stylesheet" href="/css/site.css"></head>'
        "<body><main><section id=\"hero\"><h1>Hi</h1><p>Body</p></section></main></body></html>",
        encoding="utf-8",
    )

    with html_adapter.serve_local_directory(page) as url:
        assert url.startswith("http://127.0.0.1:")
        assert url.endswith("/index.html")


def test_the_server_binds_loopback_and_shuts_down(tmp_path: Path) -> None:
    """It exists to resolve the page's own references, not to reach a network."""

    import socket
    from urllib.parse import urlsplit

    page = tmp_path / "index.html"
    page.write_text("<html></html>", encoding="utf-8")

    with html_adapter.serve_local_directory(page) as url:
        parts = urlsplit(url)
        assert parts.hostname == "127.0.0.1"
        port = parts.port

    probe = socket.socket()
    probe.settimeout(2)
    try:
        assert probe.connect_ex(("127.0.0.1", port)) != 0, "server outlived its context"
    finally:
        probe.close()


def test_a_stylesheet_that_404s_over_http_is_still_reported() -> None:
    """Chromium creates a sheet object for a 404 too, so neither link.sheet nor
    cssRules distinguishes it. Only the response status does, and serving the
    page changed the address test from catching it to missing it."""

    import inspect

    source = inspect.getsource(html_adapter.capture_rendered_observations)

    assert "response.status >= 400" in source
    assert "failed_styles" in source


def test_sectioning_elements_are_found_at_any_depth() -> None:
    """A real Vanjaro or DNN page nests its sections inside layout divs and has
    no <main>, so a direct-child query matched nothing: a live themed site with
    13 <section> elements produced zero candidates and rendered analysis
    silently yielded nothing on every real page."""

    script = html_adapter._RENDERED_OBSERVATION_JS

    assert "querySelectorAll('section, article')" in script
    # Only the outermost: a nested section is part of its parent, not a peer.
    assert "other.contains(el)" in script


def test_a_section_without_an_id_still_gets_a_locator() -> None:
    """Without one, provenance recorded nothing and the browser had no way to
    find the element the static extractor had chosen."""

    from vanjaro_cli.design.html_boundaries import css_selector_for
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        "<html><body><div><div></div><section>One</section></div></body></html>",
        "html.parser",
    )
    section = soup.find("section")

    selector = css_selector_for(section)

    assert selector is not None
    assert "nth-of-type" in selector
    assert soup.select_one(selector) is section


def test_an_id_still_wins_over_the_structural_path() -> None:
    from vanjaro_cli.design.html_boundaries import css_selector_for
    from bs4 import BeautifulSoup

    soup = BeautifulSoup('<html><body><section id="hero"></section></body></html>', "html.parser")

    assert css_selector_for(soup.find("section")) == "#hero"


def test_static_boundaries_are_found_at_any_depth() -> None:
    """A Vanjaro-built page nests its sections in layout divs and has no <main>,
    so requiring direct children returned nothing at all while the content
    extractor found eleven — and with no DOM candidate to match, no section
    recorded a selector and rendered measurement paired with nothing."""

    from vanjaro_cli.design.html_boundaries import static_boundary_candidates

    html = (
        "<html><body><div class='outer'><div class='inner'>"
        "<section id='one'>First</section><section id='two'>Second</section>"
        "</div></div></body></html>"
    )

    candidates = static_boundary_candidates(html)

    assert [tag.get("id") for tag in candidates] == ["one", "two"]


def test_only_the_outermost_sectioning_element_is_a_boundary() -> None:
    """A nested section is part of its parent, not a peer of it."""

    from vanjaro_cli.design.html_boundaries import static_boundary_candidates

    html = (
        "<html><body><section id='outer'>Outer"
        "<section id='inner'>Inner</section></section></body></html>"
    )

    candidates = static_boundary_candidates(html)

    assert [tag.get("id") for tag in candidates] == ["outer"]


def test_both_extractors_agree_on_where_sections_live() -> None:
    """They disagreed completely on a real page: 11 sections against 0 DOM
    candidates. Neither can pair with the other unless they look in the same
    places."""

    from vanjaro_cli.design.html_boundaries import static_boundary_candidates

    rendered_query = html_adapter._RENDERED_OBSERVATION_JS
    static_source = inspect_source = __import__(
        "inspect"
    ).getsource(static_boundary_candidates)

    assert "querySelectorAll('section, article')" in rendered_query
    assert 'select("section, article")' in static_source


def test_a_text_bearing_div_is_extracted_as_a_paragraph() -> None:
    """Extraction asks for <p> in half a dozen places, and a Vanjaro-built page
    has almost none: a real site came back with 51 div.vj-text blocks and 2
    paragraphs, so sections extracted with empty content and every template
    match blocked on a missing body."""

    from vanjaro_cli.design.html_adapter import extract_sections

    html = (
        "<html><body><main><section id='s1'>"
        "<div class='vj-heading'>A Heading</div>"
        "<div class='vj-text'>Some body copy that is long enough to count.</div>"
        "</section></main></body></html>"
    )

    sections = extract_sections(html, "https://vj.test/")

    assert sections
    paragraphs = sections[0]["content"].get("paragraphs") or []
    assert any("body copy" in str(text) for text in paragraphs)


def test_a_wrapper_div_is_not_turned_into_a_paragraph() -> None:
    """A div around other elements is structure, not a paragraph; rewriting it
    would swallow its children's roles."""

    from vanjaro_cli.migration.sections import normalize_text_blocks
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        "<div class='wrap'><div class='vj-text'>Copy</div></div>", "html.parser"
    )

    normalize_text_blocks(soup)

    assert soup.find("div", class_="wrap") is not None
    assert soup.find("p") is not None


def test_an_empty_div_is_left_alone() -> None:
    from vanjaro_cli.migration.sections import normalize_text_blocks
    from bs4 import BeautifulSoup

    soup = BeautifulSoup("<div class='spacer'></div>", "html.parser")

    normalize_text_blocks(soup)

    assert soup.find("p") is None


_VANJARO_CARDS = """
<section id="classes">
  <div class="container">
    <div class="row mb-4">
      <div class="col-12 text-center">
        <div class="vj-text">Our Classes</div>
        <h2 class="vj-heading">MOST POPULAR CLASSES</h2>
      </div>
    </div>
    <div class="row g-4 mb-4">
      <div class="col-md-6 col-12">
        <div class="kts-rounded-16">
          <img class="vj-image" src="/one.png" alt="Prelude"/>
          <div class="kts-card-band">
            <h3 class="vj-heading">PRELUDE</h3>
            <div class="vj-text">Ages nought to five</div>
            <a class="btn" href="/prelude">LEARN MORE</a>
          </div>
        </div>
      </div>
      <div class="col-md-6 col-12">
        <div class="kts-rounded-16">
          <img class="vj-image" src="/two.png" alt="Opening Notes"/>
          <div class="kts-card-band">
            <h3 class="vj-heading">OPENING NOTES</h3>
            <div class="vj-text">Pre piano ages four to six</div>
            <a class="btn" href="/opening">LEARN MORE</a>
          </div>
        </div>
      </div>
    </div>
    <div class="row g-4">
      <div class="col-md-6 col-12">
        <div class="kts-rounded-16">
          <img class="vj-image" src="/three.png" alt="Symphony"/>
          <div class="kts-card-band">
            <h3 class="vj-heading">SYMPHONY</h3>
            <div class="vj-text">Lessons for all ages</div>
            <a class="btn" href="/symphony">LEARN MORE</a>
          </div>
        </div>
      </div>
      <div class="col-md-6 col-12">
        <div class="kts-rounded-16">
          <img class="vj-image" src="/four.png" alt="Finale"/>
          <div class="kts-card-band">
            <h3 class="vj-heading">FINALE</h3>
            <div class="vj-text">Lessons for adults</div>
            <a class="btn" href="/finale">LEARN MORE</a>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>
"""


def _enriched(static_html: str, role: str) -> dict:
    from vanjaro_cli.design.html_ownership import enrich_section_from_static_dom

    section: dict = {"id": "page.section.1", "semantic_role": role, "content": [], "groups": []}
    enrich_section_from_static_dom(
        section,
        static_html,
        source_url="http://example.test/page",
        assets={},
        provenance={"method": "static", "source_kind": "static_html"},
    )
    return section


def test_cards_without_card_markup_still_become_a_repeat_group() -> None:
    """A builder that emits Bootstrap columns has no <article> and no .card, so
    vocabulary discovery found nothing and every item.* field went unbound."""

    section = _enriched(_VANJARO_CARDS, "feature_cards")

    groups = section["groups"]
    assert len(groups) == 1
    assert groups[0]["kind"] == "card"
    assert len(groups[0]["items"]) == 4
    assert all({"title", "media", "body"} <= set(item["fields"]) for item in groups[0]["items"])


def test_card_discovery_spans_sibling_rows() -> None:
    """The four cards live in two separate rows. Grouping by parent would have
    reported two groups of two."""

    section = _enriched(_VANJARO_CARDS, "feature_cards")

    titles = [
        next(element["value"] for element in section["content"] if element["id"] == item["fields"]["title"])
        for item in section["groups"][0]["items"]
    ]
    assert titles == ["PRELUDE", "OPENING NOTES", "SYMPHONY", "FINALE"]


def test_the_card_is_the_card_not_the_box_inside_it() -> None:
    from bs4 import BeautifulSoup

    from vanjaro_cli.design.html_ownership import repeating_subtrees

    root = BeautifulSoup(_VANJARO_CARDS, "html.parser").find("section")

    items = repeating_subtrees(root)

    assert [item.get("class") for item in items] == [["col-md-6", "col-12"]] * 4


def test_two_bands_holding_unequal_content_are_not_the_repetition() -> None:
    """A services grid had two `div.White` bands, one holding a single picture
    and the other holding six, and six cards one level down. Ranking by depth
    took the bands: two items, and the rest of the section discarded."""

    from bs4 import BeautifulSoup

    from vanjaro_cli.design.html_ownership import repeating_subtrees

    cards = "".join(
        f"<div class='col-sm-4'><img src='/{n}.jpg'><h3>Service {n}</h3></div>"
        for n in range(1, 7)
    )
    root = BeautifulSoup(
        "<section>"
        "<div class='White'><img src='/banner.jpg'><h2>Our Services</h2></div>"
        f"<div class='White'>{cards}</div>"
        "</section>",
        "html.parser",
    ).find("section")

    items = repeating_subtrees(root)

    assert [item.get("class") for item in items] == [["col-sm-4"]] * 6


def test_a_tie_on_count_still_prefers_the_outermost() -> None:
    """The card is still the card rather than the rounded box inside it — the
    rule that ranking by count must not cost."""

    from bs4 import BeautifulSoup

    from vanjaro_cli.design.html_ownership import repeating_subtrees

    cards = "".join(
        f"<div class='card'><div class='inner'><img src='/{n}.jpg'><h3>Item {n}</h3></div></div>"
        for n in range(1, 4)
    )
    root = BeautifulSoup(f"<section>{cards}</section>", "html.parser").find("section")

    items = repeating_subtrees(root)

    assert [item.get("class") for item in items] == [["card"]] * 3


def test_a_signature_that_nests_inside_itself_is_not_a_repetition() -> None:
    """A wrapper sharing its class with what it wraps is one thing containing
    another, not two of a kind — and taking it would make an item that holds
    every other item."""

    from bs4 import BeautifulSoup

    from vanjaro_cli.design.html_ownership import repeating_subtrees

    root = BeautifulSoup(
        "<section>"
        "<div class='panel'><h2>Outer</h2><img src='/outer.jpg'>"
        "<div class='panel'><h3>Inner</h3><img src='/inner.jpg'></div></div>"
        "<div class='tile'><h3>One</h3><img src='/1.jpg'></div>"
        "<div class='tile'><h3>Two</h3><img src='/2.jpg'></div>"
        "</section>",
        "html.parser",
    ).find("section")

    items = repeating_subtrees(root)

    assert [item.get("class") for item in items] == [["tile"]] * 2


def test_the_section_heading_is_not_swallowed_by_a_card() -> None:
    section = _enriched(_VANJARO_CARDS, "feature_cards")

    titles = [element["value"] for element in section["content"] if element["role"] == "section_title"]
    assert titles == ["MOST POPULAR CLASSES"]


def test_a_section_with_no_repetition_reports_no_group() -> None:
    """One card-shaped block is a section, not a repeat group."""

    from bs4 import BeautifulSoup

    from vanjaro_cli.design.html_ownership import repeating_subtrees

    root = BeautifulSoup(
        "<section><div class='col'><h3>Only</h3><img src='/a.png'/></div></section>",
        "html.parser",
    ).find("section")

    assert repeating_subtrees(root) == []


def test_repeated_blocks_without_a_heading_or_image_are_not_cards() -> None:
    from bs4 import BeautifulSoup

    from vanjaro_cli.design.html_ownership import repeating_subtrees

    root = BeautifulSoup(
        "<section><div class='col'>one</div><div class='col'>two</div></section>",
        "html.parser",
    ).find("section")

    assert repeating_subtrees(root) == []


def test_known_card_markup_still_wins_over_structural_discovery() -> None:
    """Vocabulary discovery is unchanged; the structural pass is a fallback."""

    section = _enriched(
        "<section>"
        "<div class='wrap'><article><h3>One</h3><img src='/a.png'/></article></div>"
        "<div class='wrap'><article><h3>Two</h3><img src='/b.png'/></article></div>"
        "</section>",
        "feature_cards",
    )

    assert len(section["groups"][0]["items"]) == 2


def test_card_body_copy_survives_a_builder_that_never_emits_a_paragraph() -> None:
    """This pass parses the source subtree, not extraction output, so it needs
    its own text normalization."""

    section = _enriched(_VANJARO_CARDS, "feature_cards")

    bodies = [element["value"] for element in section["content"] if element["role"] == "card_body"]
    assert bodies == [
        "Ages nought to five",
        "Pre piano ages four to six",
        "Lessons for all ages",
        "Lessons for adults",
    ]


_LINK_BAR_PAGE = """
<body>
  <section id="chrome" class="vj-section">
    <img src="/logo.png" alt="Keys to Success"/>
    <a href="/">Home</a><a href="/studio">The Studio</a>
    <a href="/lessons">Lessons</a><a href="/contact">Contact Us</a>
  </section>
  <section id="story" class="vj-section">
    <h2>MUSIC IS MAGIC</h2>
    <p>The values that come from studying music are miraculous.</p>
  </section>
</body>
"""


def _role_of(html: str, selector: str) -> str:
    from bs4 import BeautifulSoup

    from vanjaro_cli.design.html_boundaries import static_boundary_candidates, static_role

    candidates = static_boundary_candidates(html)
    soup_ids = [tag.get("id") for tag in candidates]
    index = soup_ids.index(selector)
    return static_role(candidates[index], index)


def test_a_link_bar_is_navigation_without_any_nav_markup() -> None:
    """A builder that emits its own chrome carries no <header> and no <nav>, so
    the site header matched a CTA template that wanted a title it lacks."""

    assert _role_of(_LINK_BAR_PAGE, "chrome") == "navigation"


def test_a_section_with_a_heading_is_not_a_link_bar() -> None:
    """A footer carries headings and a copyright line; it is not the header."""

    html = (
        "<body><section id='foot'><h3>Visit</h3>"
        "<a href='/a'>A</a><a href='/b'>B</a><a href='/c'>C</a>"
        "<p>Copyright 2026 Keys to Success, all rights reserved.</p>"
        "</section></body>"
    )

    assert _role_of(html, "foot") != "navigation"


def test_a_call_to_action_with_links_is_not_a_link_bar() -> None:
    """What makes the call is the prose, and a navigation bar has none."""

    html = (
        "<body><section id='cta'>"
        "<p>Enrolment for the autumn term closes on Friday. Choose a class that "
        "suits your child and reserve a place before it goes.</p>"
        "<a href='/a'>Prelude</a><a href='/b'>Opening Notes</a><a href='/c'>Finale</a>"
        "</section></body>"
    )

    assert _role_of(html, "cta") != "navigation"


def test_a_section_of_only_two_links_is_not_a_link_bar() -> None:
    html = "<body><section id='pair'><a href='/a'>A</a><a href='/b'>B</a></section></body>"

    assert _role_of(html, "pair") != "navigation"


def _prepared(html: str, sections: list[dict]) -> list[dict]:
    from vanjaro_cli.design.html_boundaries import prepare_static_sections

    return prepare_static_sections(html, sections)


def _empty_content(**overrides) -> dict:
    content = {key: [] for key in ("headings", "paragraphs", "images", "links", "buttons")}
    content.update(overrides)
    return content


def test_a_section_that_matches_the_chrome_becomes_the_chrome() -> None:
    """The extractor emits the header as an ordinary section. Withholding the
    candidate instead left that section to match the footer's subtree."""

    prepared = _prepared(
        _LINK_BAR_PAGE,
        [
            {"type": "cta", "template": "CTA Banner", "content": _empty_content(
                links=[{"text": "Home", "href": "/"}, {"text": "The Studio", "href": "/studio"}],
            )},
            {"type": "content", "template": "Rich Text Block", "content": _empty_content(
                headings=["MUSIC IS MAGIC"],
                paragraphs=["The values that come from studying music are miraculous."],
            )},
        ],
    )

    assert [entry["_static_role"] for entry in prepared] == ["navigation", "rich_text"]
    assert prepared[0]["_static_selector"] == "#chrome"
    assert prepared[1]["_static_selector"] == "#story"


def test_the_chrome_is_not_recorded_twice() -> None:
    prepared = _prepared(
        _LINK_BAR_PAGE,
        [{"type": "cta", "template": "CTA Banner", "content": _empty_content(
            links=[{"text": "Home", "href": "/"}, {"text": "The Studio", "href": "/studio"}],
        )}],
    )

    assert [entry["_static_role"] for entry in prepared].count("navigation") == 1


def test_chrome_no_section_claimed_is_still_recorded() -> None:
    prepared = _prepared(
        _LINK_BAR_PAGE,
        [{"type": "content", "template": "Rich Text Block", "content": _empty_content(
            headings=["MUSIC IS MAGIC"],
            paragraphs=["The values that come from studying music are miraculous."],
        )}],
    )

    assert [entry["_static_role"] for entry in prepared] == ["navigation", "rich_text"]


_STYLED_HERO = """
<section id="hero">
  <div class="kts-hero-inner">
    <div class="kts-hero-title"><span>MUSIC FOR</span><span>EVERYONE</span></div>
    <p class="vj-text">Lorem ipsum dolor sit amet, consectetur adipiscing elit.</p>
  </div>
</section>
"""


def test_a_styled_div_is_read_as_the_heading_it_looks_like() -> None:
    """A hero band carried its title in a div of two spans, so the section
    reported body copy, no title, and blocked on a required field."""

    section = _enriched(_STYLED_HERO, "hero")

    titles = [element for element in section["content"] if element["role"] == "section_title"]
    assert [element["value"] for element in titles] == ["MUSIC FOR EVERYONE"]
    assert titles[0]["attributes"]["implied"] is True


def test_a_promoted_title_is_not_also_body_copy() -> None:
    section = _enriched(
        "<section><p class='vj-text'>MUSIC FOR EVERYONE</p>"
        "<p class='vj-text'>Lorem ipsum dolor sit amet.</p></section>",
        "hero",
    )

    bodies = [element["value"] for element in section["content"] if element["role"] == "body"]
    assert bodies == ["Lorem ipsum dolor sit amet."]


def test_a_real_heading_is_preferred_and_not_marked_implied() -> None:
    section = _enriched(
        "<section><div class='eyebrow'>Our Classes</div>"
        "<h2>MOST POPULAR CLASSES</h2><p>Copy.</p></section>",
        "rich_text",
    )

    titles = [element for element in section["content"] if element["role"] == "section_title"]
    assert [element["value"] for element in titles] == ["MOST POPULAR CLASSES"]
    assert "implied" not in titles[0]["attributes"]


def test_a_heading_below_h3_is_still_a_heading() -> None:
    section = _enriched("<section><h4>Studio hours</h4><p>Copy.</p></section>", "rich_text")

    titles = [element for element in section["content"] if element["role"] == "section_title"]
    assert [element["value"] for element in titles] == ["Studio hours"]
    assert titles[0]["attributes"]["level"] == 4


def test_a_long_first_block_is_prose_not_a_title() -> None:
    from bs4 import BeautifulSoup

    from vanjaro_cli.design.html_ownership import implied_title

    root = BeautifulSoup(
        "<section><div>" + "word " * 40 + "</div><div>More copy follows.</div></section>",
        "html.parser",
    ).find("section")

    assert implied_title(root) is None


def test_a_section_of_one_block_has_no_title_to_promote() -> None:
    from bs4 import BeautifulSoup

    from vanjaro_cli.design.html_ownership import implied_title

    root = BeautifulSoup("<section><div>MUSIC IS MAGIC</div></section>", "html.parser").find("section")

    assert implied_title(root) is None


_STATS_BAND = """
<section id="band">
  <div class="container">
    <div class="row text-center">
      <div class="col-md-4"><h2>10</h2><p>Professional Instructors</p></div>
      <div class="col-md-4"><h2>&#8734;</h2><p>Happy Students</p></div>
      <div class="col-md-4"><h2>80+</h2><p>Combined Years of Experience</p></div>
    </div>
  </div>
</section>
"""


def test_a_stats_band_is_not_a_card_grid() -> None:
    """A real band nested under a container and a row, so a direct-child test
    found nothing and its numbers were bound as card titles."""

    from vanjaro_cli.migration.sections import extract_sections

    sections = extract_sections(f"<body>{_STATS_BAND}</body>", "http://example.test/")

    assert [section["type"] for section in sections] == ["stats"]


def test_a_symbol_counts_as_a_stat_value() -> None:
    """A page used the infinity sign for happy students. What makes a stat a
    stat is a short token with no letters, not that it is a numeral."""

    from vanjaro_cli.migration.sections import is_stat_value

    assert is_stat_value("∞")
    assert is_stat_value("80+")
    assert not is_stat_value("Professional Instructors")


def test_stats_values_and_labels_survive_a_builder_with_no_strong_tags() -> None:
    section = _enriched(_STATS_BAND, "stats")

    groups = section["groups"]
    assert [group["kind"] for group in groups] == ["stat"]
    assert len(groups[0]["items"]) == 3
    values = [element["value"] for element in section["content"] if element["role"] == "stat_value"]
    labels = [element["value"] for element in section["content"] if element["role"] == "stat_label"]
    assert values == ["10", "∞", "80+"]
    assert labels == ["Professional Instructors", "Happy Students", "Combined Years of Experience"]


def test_repeated_blocks_with_no_value_are_not_stats() -> None:
    """A structural group alone is not evidence of a stat, and claiming a
    richer block would drop everything that is neither value nor label."""

    section = _enriched(
        "<section><div class='col'><h3>Piano</h3><p>Weekly lessons.</p></div>"
        "<div class='col'><h3>Guitar</h3><p>Weekly lessons.</p></div>"
        "<div class='col'><h3>Voice</h3><p>Weekly lessons.</p></div></section>",
        "stats",
    )

    assert section["groups"] == []


_CHROME_PAGE = """
<body>
  <section id="chrome" class="vj-section">
    <img src="/logo.png" alt="Studio"/>
    <a href="/">Home</a><a href="/about">About</a><a href="/contact">Contact</a>
  </section>
  <section id="story" class="vj-section"><h2>MUSIC IS MAGIC</h2><p>Copy here.</p></section>
  <section id="foot" class="vj-section">
    <h5>QUICK LINKS</h5><a href="/a">Home</a><a href="/b">Programs</a>
    <h5>OTHER LINKS</h5><a href="/c">Privacy</a>
    <p>Doctors Drive, Angeles California.</p>
  </section>
</body>
"""


def test_a_footer_without_a_footer_element_is_chrome() -> None:
    """A builder that wraps its chrome in plain sections had its header fixed
    and its footer left matching CTA templates that want a title it lacks."""

    prepared = _prepared(_CHROME_PAGE, [])

    assert [entry["_static_role"] for entry in prepared] == ["navigation", "footer"]


def test_the_footer_stays_at_the_end() -> None:
    prepared = _prepared(
        _CHROME_PAGE,
        [{"type": "content", "template": "Rich Text Block", "content": _empty_content(
            headings=["MUSIC IS MAGIC"], paragraphs=["Copy here."],
        )}],
    )

    assert [entry["_static_role"] for entry in prepared] == ["navigation", "rich_text", "footer"]


def test_only_one_footer_is_recorded() -> None:
    """Two footer sections make the global plan report conflicting variants and
    block, which is worse than leaving a copyright bar in the body."""

    prepared = _prepared(_CHROME_PAGE + "<section id='copy'><h6>A</h6><h6>B</h6>"
                         "<a href='/x'>x</a><a href='/y'>y</a><a href='/z'>z</a></section>", [])

    assert [entry["_static_role"] for entry in prepared].count("footer") == 1


def test_a_mid_page_card_grid_is_not_a_footer() -> None:
    html = (
        "<body><section id='services'><h2>What we do</h2>"
        "<h3>Strategy</h3><a href='/s'>More</a>"
        "<h3>Design</h3><a href='/d'>More</a><a href='/b'>More</a></section>"
        "<section id='last'><h2>Closing</h2><p>Copy.</p></section></body>"
    )

    prepared = _prepared(html, [])

    assert not any(entry["_static_role"] == "footer" for entry in prepared)


def test_a_class_that_merely_contains_cta_is_not_a_call_to_action() -> None:
    """`#tpl-ctas-s1` read as a call to action because "ctas" contains "cta",
    and the section has no link at all."""

    html = (
        "<body><section id='tpl-ctas-s1'><h2>Join us at the studio</h2>"
        "<img src='/a.png' alt=''/><p>Short line.</p>"
        "<p>Our mobile studio brings these programs to you.</p></section></body>"
    )

    assert _role_of(html, "tpl-ctas-s1") != "call_to_action"


def test_a_real_cta_class_still_classifies() -> None:
    html = (
        "<body><section id='cta-band'><h2>Ready to start?</h2>"
        "<a href='/go'>Book a lesson</a></section></body>"
    )

    assert _role_of(html, "cta-band") == "call_to_action"


def test_a_link_with_no_label_is_not_the_call() -> None:
    """A media block whose thumbnail is wrapped in a link otherwise reads as a
    call to action, then matches a template requiring an action it cannot fill."""

    html = (
        "<body><section id='media'><h2>See what our students can do</h2>"
        "<p>Pellentesque mattis mauris ac tortor volutpat.</p>"
        "<a href='/watch'><img src='/thumb.png' alt=''/></a></section></body>"
    )

    assert _role_of(html, "media") != "call_to_action"


def test_a_short_line_under_a_headline_is_a_deck() -> None:
    """Calling both lines body copy needs two body slots where the templates
    own one, and loses a distinction a reader can see."""

    section = _enriched(
        "<section><h2>JOIN US AT KEYS TO SUCCESS</h2>"
        "<p>and give your child the gift of music.</p>"
        "<p>Our mobile studio brings these exceptional programs right to you.</p></section>",
        "rich_text",
    )

    roles = [element["role"] for element in section["content"] if element["kind"] == "text"]
    assert roles == ["subtitle", "body"]


def test_a_lone_short_paragraph_is_body_copy() -> None:
    section = _enriched("<section><h2>Studio hours</h2><p>Weekdays.</p></section>", "rich_text")

    assert [element["role"] for element in section["content"] if element["kind"] == "text"] == ["body"]


def test_a_long_first_paragraph_is_not_a_deck() -> None:
    section = _enriched(
        "<section><h2>Studio hours</h2>"
        "<p>" + "word " * 30 + "</p><p>Second paragraph.</p></section>",
        "rich_text",
    )

    assert [element["role"] for element in section["content"] if element["kind"] == "text"] == ["body", "body"]


def test_a_text_free_image_band_is_a_photo_band() -> None:
    """Falling through to rich text gave a DNN banner pane a template whose body
    is required, which a section carrying no text can never satisfy."""

    html = "<body><section id='banner'><div><img src='/banner.jpg' alt=''/></div></section></body>"

    assert _role_of(html, "banner") == "photo_band"


def test_a_band_with_words_is_not_a_photo_band() -> None:
    html = (
        "<body><section id='band'><img src='/a.jpg' alt=''/>"
        "<p>Consulting that fits how you already work.</p></section></body>"
    )

    assert _role_of(html, "band") != "photo_band"


def test_a_photo_band_owns_its_picture_as_background_media() -> None:
    """Only background_media reaches the slot that fills a full-bleed band."""

    section = _enriched("<section><img src='/banner.jpg' alt=''/></section>", "photo_band")

    assert [element["role"] for element in section["content"]] == ["background_media"]


def test_the_loopback_server_does_not_narrate_requests(capsys) -> None:
    """SimpleHTTPRequestHandler logs every request to stderr, and a saved page
    missing ten stylesheets made --json output unparseable."""

    import urllib.request

    from vanjaro_cli.design.html_adapter import serve_local_directory

    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        page = Path(directory) / "page.html"
        page.write_text("<html><body>hi</body></html>", encoding="utf-8")
        with serve_local_directory(page) as url:
            urllib.request.urlopen(url).read()
            try:
                urllib.request.urlopen(url.replace("page.html", "missing.css"))
            except Exception:  # noqa: BLE001 - a 404 is the point
                pass

    assert capsys.readouterr().err == ""


_NESTED_PANES = """
<body><div id="Body">
  <div id="dnn_content" class="Pane">
    <div id="dnn_TopPane" class="Pane"><h2>Who we are</h2><p>A service organization.</p></div>
    <div id="dnn_BannerPane" class="Pane"><img src="/banner.jpg" alt=""/></div>
  </div>
</div></body>
"""


def _selectors(html: str) -> list[str]:
    from vanjaro_cli.design.html_boundaries import css_selector_for, static_boundary_candidates

    return [css_selector_for(tag) for tag in static_boundary_candidates(html)]


def test_a_pane_wrapping_other_panes_is_not_a_boundary() -> None:
    """A real DNN page put #dnn_content around three panes that were themselves
    candidates, so every word inside it was counted twice."""

    assert _selectors(_NESTED_PANES) == ["#dnn_TopPane", "#dnn_BannerPane"]


def test_a_wrapper_that_carries_its_own_copy_is_kept() -> None:
    """Outermost is the wrong tie-break here — the test is contribution. A
    wrapper with words of its own is a section that happens to contain one."""

    html = (
        "<body><div id='Body'><div id='dnn_content' class='Pane'>"
        "<h2>Introduction that belongs to the outer pane</h2>"
        "<div id='dnn_TopPane' class='Pane'><p>Inner copy.</p></div>"
        "</div></div></body>"
    )

    assert "#dnn_content" in _selectors(html)


def test_a_wrapper_holding_an_extra_image_is_kept() -> None:
    html = (
        "<body><div id='Body'><div id='dnn_content' class='Pane'>"
        "<img src='/outer.jpg' alt=''/>"
        "<div id='dnn_TopPane' class='Pane'><p>Inner copy.</p></div>"
        "</div></div></body>"
    )

    assert "#dnn_content" in _selectors(html)


def test_unnested_panes_are_all_boundaries() -> None:
    html = (
        "<body><div id='Body'>"
        "<div id='dnn_TopPane' class='Pane'><p>One.</p></div>"
        "<div id='dnn_BottomPane' class='Pane'><p>Two.</p></div>"
        "</div></body>"
    )

    assert _selectors(html) == ["#dnn_TopPane", "#dnn_BottomPane"]


_SPLIT_SECTION = """
<body><section id="split"><div class="container"><div class="row">
  <div class="col-md-6"><img src="/boy.png" alt="Boy playing a ukulele"/></div>
  <div class="col-md-6"><h2>MUSIC IS MAGIC</h2>
    <p>The values that come from studying music are truly miraculous.</p>
    <a class="btn" href="/learn">LEARN MORE</a></div>
</div></div></section></body>
"""


def test_a_picture_beside_its_copy_is_a_split() -> None:
    """The layout was recorded as a one-column stack, so the section read
    rich_text and matched a template with no media field and no action."""

    assert _role_of(_SPLIT_SECTION, "split") == "split_media"


def test_a_card_grid_is_not_a_split() -> None:
    """The inner row of a four-card grid has two columns and a picture in one."""

    assert _role_of(_VANJARO_CARDS, "classes") != "split_media"


def test_a_section_with_two_pictures_is_not_a_split() -> None:
    """A split is one picture beside one block of copy. A stacked media feature
    carrying a mascot and a thumbnail is not one."""

    html = (
        "<body><section id='feature'><div class='row'>"
        "<div><img src='/mascot.png' alt=''/></div>"
        "<div><h2>See what our students can do</h2>"
        "<p>Pellentesque mattis mauris ac tortor volutpat.</p>"
        "<img src='/thumb.png' alt=''/></div>"
        "</div></section></body>"
    )

    assert _role_of(html, "feature") != "split_media"


def test_a_split_records_which_side_the_picture_is_on() -> None:
    """A mirrored build reads as a different design."""

    from bs4 import BeautifulSoup

    section = _enriched(
        str(BeautifulSoup(_SPLIT_SECTION, "html.parser").find("section")), "split_media"
    )

    assert section["layout"]["kind"] == "split"
    assert section["layout"]["media_position"] == "left"


def test_a_split_with_the_picture_second_says_right() -> None:
    from bs4 import BeautifulSoup

    reversed_html = (
        "<section id='split'><div class='row'>"
        "<div><h2>MUSIC IS MAGIC</h2>"
        "<p>The values that come from studying music are truly miraculous.</p></div>"
        "<div><img src='/boy.png' alt=''/></div>"
        "</div></section>"
    )

    section = _enriched(
        str(BeautifulSoup(reversed_html, "html.parser").find("section")), "split_media"
    )

    assert section["layout"]["media_position"] == "right"


def test_the_title_is_the_most_prominent_heading_not_the_first() -> None:
    """A section led by a small eyebrow titled itself with the eyebrow and
    dropped its real heading entirely."""

    section = _enriched(
        "<section><h5>OUR MEDIA</h5><h2>See what our students can do</h2>"
        "<p>Pellentesque mattis mauris ac tortor volutpat.</p></section>",
        "rich_text",
    )

    titles = [e["value"] for e in section["content"] if e["role"] == "section_title"]
    assert titles == ["See what our students can do"]


def test_a_kicker_above_the_headline_is_kept_as_an_eyebrow() -> None:
    section = _enriched(
        "<section><h5>OUR MEDIA</h5><h2>See what our students can do</h2>"
        "<p>Pellentesque mattis mauris ac tortor volutpat.</p></section>",
        "rich_text",
    )

    assert [e["value"] for e in section["content"] if e["role"] == "eyebrow"] == ["OUR MEDIA"]


def test_a_kicker_spelled_as_copy_is_still_an_eyebrow() -> None:
    """A Vanjaro page spells its kicker `div.vj-text`, which normalizes to a
    paragraph — so `Our Classes` above `MOST POPULAR CLASSES` arrived as body
    copy, and a card grid that rightly has no body field was asked for one."""

    section = _enriched(
        "<section><div class='vj-text'>Our Classes</div>"
        "<h2>MOST POPULAR CLASSES</h2>"
        "<div class='card'><h3>Prelude</h3><p>Age 0-5 yrs.</p></div>"
        "<div class='card'><h3>Finale</h3><p>Lessons for adults.</p></div>"
        "</section>",
        "feature_cards",
    )

    assert [e["value"] for e in section["content"] if e["role"] == "eyebrow"] == ["Our Classes"]
    assert not [e for e in section["content"] if e["role"] == "body"]
    assert [e["value"] for e in section["content"] if e["role"] == "section_title"] == [
        "MOST POPULAR CLASSES"
    ]


def test_a_short_line_below_the_headline_is_not_an_eyebrow() -> None:
    """Position is the whole distinction. A short line under the headline is a
    deck or body copy; only what opens above it is a kicker."""

    section = _enriched(
        "<section><h2>Studio hours</h2><div class='vj-text'>Weekdays only.</div>"
        "<div class='vj-text'>We open at nine and close when the last lesson ends.</div>"
        "</section>",
        "rich_text",
    )

    assert not [e for e in section["content"] if e["role"] == "eyebrow"]
    assert [e["value"] for e in section["content"] if e["role"] == "subtitle"] == ["Weekdays only."]


def test_a_headings_kicker_wins_and_the_line_above_it_is_still_kept() -> None:
    """Both spellings can appear at once. Reporting two eyebrows would give the
    section a part it does not have — and the loser must not vanish, which is
    what happens if it is skipped as an eyebrow that was never emitted."""

    section = _enriched(
        "<section><div class='vj-text'>Our studio</div><h5>OUR MEDIA</h5>"
        "<h2>See what our students can do</h2><p>Copy that runs on.</p></section>",
        "rich_text",
    )

    assert [e["value"] for e in section["content"] if e["role"] == "eyebrow"] == ["OUR MEDIA"]
    assert "Our studio" in [e["value"] for e in section["content"] if e["role"] == "body"]


def test_every_other_heading_the_section_owns_survives() -> None:
    """Only the title and one eyebrow were emitted, so a subsection label left
    the document entirely — no plan warning names content that was never
    extracted, and coverage cannot count what did not arrive."""

    section = _enriched(
        "<section><h2>What we offer</h2><p>Intro copy that runs on a while.</p>"
        "<h3>Branding Package</h3><p>What the package includes.</p>"
        "<h4>Tags</h4></section>",
        "rich_text",
    )

    assert [e["value"] for e in section["content"] if e["role"] == "subheading"] == [
        "Branding Package",
        "Tags",
    ]
    assert [e["value"] for e in section["content"] if e["role"] == "section_title"] == [
        "What we offer"
    ]


def test_the_title_is_not_also_reported_as_a_subheading() -> None:
    section = _enriched(
        "<section><h2>Studio hours</h2><h3>Weekends</h3><p>Copy.</p></section>",
        "rich_text",
    )

    values = [e["value"] for e in section["content"] if e["role"] == "subheading"]
    assert values == ["Weekends"]
    assert "Studio hours" not in values


def test_the_eyebrow_is_not_also_reported_as_a_subheading() -> None:
    """The kicker already has a role. Reporting it twice would make the section
    carry a heading it does not have."""

    section = _enriched(
        "<section><h5>OUR MEDIA</h5><h2>See what our students can do</h2>"
        "<h3>Gallery</h3><p>Copy that runs on.</p></section>",
        "rich_text",
    )

    assert [e["value"] for e in section["content"] if e["role"] == "eyebrow"] == ["OUR MEDIA"]
    assert [e["value"] for e in section["content"] if e["role"] == "subheading"] == ["Gallery"]


def test_a_cards_own_heading_is_a_card_title_not_a_subheading() -> None:
    """A repeated item's heading already has an owner. Emitting it again at
    section level would double every card title in the document."""

    section = _enriched(
        "<section><h2>Our services</h2>"
        "<div class='card'><h3>Strategy</h3><p>Plan the work.</p></div>"
        "<div class='card'><h3>Design</h3><p>Shape the work.</p></div>"
        "<div class='card'><h3>Build</h3><p>Do the work.</p></div>"
        "</section>",
        "feature_cards",
    )

    assert [e["value"] for e in section["content"] if e["role"] == "card_title"] == [
        "Strategy",
        "Design",
        "Build",
    ]
    assert not [e for e in section["content"] if e["role"] == "subheading"]


def test_a_paragraph_that_is_only_a_link_arrives_once() -> None:
    """`<p><a href="/post">Read More</a></p>` is a link, and a page of blog
    cards has six. Reading the paragraph as body copy and the anchor as a call
    to action put the same words in twice, once with the destination and once
    without."""

    section = _enriched(
        "<section><h2>From the blog</h2><p>Some genuine body copy here.</p>"
        "<p><a class='btn' href='/blog/post/one'>Read More</a></p>"
        "</section>",
        "rich_text",
    )

    assert [e["value"] for e in section["content"] if e["role"] == "body"] == [
        "Some genuine body copy here."
    ]
    actions = [e for e in section["content"] if e["role"] == "primary_action"]
    assert [e["value"] for e in actions] == ["Read More"]
    assert actions[0]["attributes"]["href"] == "/blog/post/one"


def test_a_paragraph_with_a_link_inside_its_prose_is_still_body_copy() -> None:
    """The rule is that the paragraph IS the link, not that it contains one. A
    citation inside a sentence must not take the sentence with it."""

    section = _enriched(
        "<section><h2>Security</h2>"
        "<p>Chrome users are <a href='https://example.invalid/s'>most of the web</a> "
        "and the change affects them.</p>"
        "<p>A second paragraph so the first is not a deck.</p></section>",
        "rich_text",
    )

    prose = [
        e["value"]
        for e in section["content"]
        if e["kind"] == "text" and "the change affects them" in (e["value"] or "")
    ]
    assert prose == ["Chrome users are most of the web and the change affects them."]


def test_the_rule_claims_a_paragraph_only_when_a_link_supplies_its_text() -> None:
    """An unlabelled anchor is not emitted as an action, so a paragraph holding
    one has no action to defer to. Matching it on emptiness alone would drop the
    element with nothing taking its place."""

    from vanjaro_cli.design.html_ownership import _is_only_a_link

    from bs4 import BeautifulSoup

    empty = BeautifulSoup("<p><a href='#mm-1'></a></p>", "html.parser").find("p")
    labelled = BeautifulSoup("<p><a href='/x'>Read More</a></p>", "html.parser").find("p")

    assert _is_only_a_link(empty) is False
    assert _is_only_a_link(labelled) is True


def test_a_picture_wrapped_in_a_link_is_one_thing_not_two() -> None:
    """The thumbnail arrived twice — once as media and once as a call to action
    with nothing to read on it. The anchor is the picture's destination."""

    section = _enriched(
        "<section><h2>Our work</h2><p>Copy about the work we do.</p>"
        "<a href='/projects/one' aria-label='A finished project'>"
        "<img src='/one.jpg' alt='A finished project'></a>"
        "</section>",
        "rich_text",
    )

    images = [e for e in section["content"] if e["kind"] == "image"]
    assert [e["attributes"]["href"] for e in images] == ["/projects/one"]
    # The anchor carries an accessible name, so only the picture rule keeps this
    # from arriving a second time — and the name survives as the image's alt.
    assert not [e for e in section["content"] if e["role"] == "primary_action"]
    assert images[0]["attributes"]["alt"] == "A finished project"


def test_an_action_named_only_by_its_accessible_name_keeps_that_name() -> None:
    """A social icon says what it is in `aria-label`. Emitting it with an empty
    value made a call to action nobody could read and nothing could bind."""

    section = _enriched(
        "<section><h2>Follow along</h2><p>Copy that runs on a while.</p>"
        "<a href='https://example.invalid/x' aria-label='Twitter'><i class='icon'></i></a>"
        "</section>",
        "rich_text",
    )

    assert [
        e["value"] for e in section["content"] if e["role"] == "primary_action"
    ] == ["Twitter"]


def test_an_anchor_with_nothing_to_read_anywhere_is_not_an_action() -> None:
    """`mm-next` and `mm-close` are a mobile menu's own controls: no text, no
    accessible name, no picture, and a destination that means nothing to a
    reader."""

    section = _enriched(
        "<section><h2>Studio</h2><p>Copy that runs on a while.</p>"
        "<a class='mm-next' href='#mm-1'></a><a class='mm-close' href='#Form'></a>"
        "</section>",
        "rich_text",
    )

    assert not [e for e in section["content"] if e["role"] == "primary_action"]


def test_an_ordinary_labelled_action_is_untouched() -> None:
    """The guard must not swallow the calls that matter."""

    section = _enriched(
        "<section><h2>Ready?</h2><p>Copy that runs on a while.</p>"
        "<a class='btn' href='/contact'>Get Started!</a></section>",
        "call_to_action",
    )

    actions = [e for e in section["content"] if e["role"] == "primary_action"]
    assert [e["value"] for e in actions] == ["Get Started!"]
    assert actions[0]["attributes"]["href"] == "/contact"


def test_a_quotes_attribution_survives_outside_a_testimonials_section() -> None:
    """Only the testimonials branch read a `<cite>`, so the moment a section
    holding a pull-quote stopped being testimonials its attribution left the
    document — "Walt Whitman" under a line of Whitman."""

    section = _enriched(
        "<section><h2>Lighting</h2>"
        "<blockquote><h3>A leaf of grass is no less than the stars</h3>"
        "<footer><cite>Walt Whitman</cite></footer></blockquote>"
        "<p>Copy about lighting that runs on.</p></section>",
        "rich_text",
    )

    assert [e["value"] for e in section["content"] if e["role"] == "author"] == [
        "Walt Whitman"
    ]


def test_an_attribution_owned_by_a_repeated_item_is_not_reported_twice() -> None:
    """A testimonial's own `<cite>` already becomes that item's author. Emitting
    it again at section level would double every attribution on the page."""

    section = _enriched(
        "<section><h2>What clients say</h2>"
        "<figure><blockquote>First quote.</blockquote><figcaption>Amir</figcaption></figure>"
        "<figure><blockquote>Second quote.</blockquote><figcaption>Reese</figcaption></figure>"
        "</section>",
        "testimonials",
    )

    assert [e["value"] for e in section["content"] if e["role"] == "author"] == [
        "Amir",
        "Reese",
    ]


def test_a_smaller_heading_below_the_title_is_not_an_eyebrow() -> None:
    """An eyebrow sits above the headline. A subheading below it does not."""

    section = _enriched(
        "<section><h2>Studio hours</h2><h4>Weekdays</h4><p>Copy.</p></section>",
        "rich_text",
    )

    assert not [e for e in section["content"] if e["role"] == "eyebrow"]
    assert [e["value"] for e in section["content"] if e["role"] == "section_title"] == ["Studio hours"]


def test_document_order_still_breaks_a_tie_between_equal_headings() -> None:
    section = _enriched(
        "<section><h2>First</h2><h2>Second</h2><p>Copy.</p></section>", "rich_text"
    )

    assert [e["value"] for e in section["content"] if e["role"] == "section_title"] == ["First"]


_MEDIA_FEATURE = """
<body><section id="feature">
  <div class="mascot"><img src="/mascot.png" alt="Saxophone player mascot"/></div>
  <div class="container">
    <h5>OUR MEDIA</h5><h2>See what our students can do</h2>
    <p>Pellentesque mattis mauris ac tortor volutpat.</p>
    <a class="vj-link" href="/watch"><img src="/thumb.png" alt="Two students playing"/></a>
  </div>
</section></body>
"""


def test_a_linked_thumbnail_beside_a_heading_is_a_media_feature() -> None:
    """It matched a rich-text template that holds a title and body and nothing
    else, so its eyebrow, its picture and its link were all dropped."""

    assert _role_of(_MEDIA_FEATURE, "feature") == "video_feature"


def test_a_gallery_of_linked_thumbnails_is_not_a_media_feature() -> None:
    html = (
        "<body><section id='gallery'><h2>Our work</h2>"
        "<a href='/a'><img src='/a.png' alt=''/></a>"
        "<a href='/b'><img src='/b.png' alt=''/></a>"
        "<a href='/c'><img src='/c.png' alt=''/></a>"
        "</section></body>"
    )

    assert _role_of(html, "gallery") != "video_feature"


def test_a_labelled_link_is_not_a_thumbnail() -> None:
    """A card grid's links carry their own labels."""

    html = (
        "<body><section id='cards'><h2>Classes</h2>"
        "<a href='/a'><img src='/a.png' alt=''/> LEARN MORE</a>"
        "</section></body>"
    )

    assert _role_of(html, "cards") != "video_feature"


def test_the_featured_picture_is_the_one_the_link_points_at() -> None:
    from bs4 import BeautifulSoup

    section = _enriched(
        str(BeautifulSoup(_MEDIA_FEATURE, "html.parser").find("section")), "video_feature"
    )

    media = [e for e in section["content"] if e["role"] == "section_media"]
    assert [e["attributes"]["alt"] for e in media] == ["Two students playing"]


def test_a_mascot_beside_the_feature_is_decoration_not_media() -> None:
    """Counting it as editorial media made the section overflow a template that
    holds one picture."""

    from bs4 import BeautifulSoup

    section = _enriched(
        str(BeautifulSoup(_MEDIA_FEATURE, "html.parser").find("section")), "video_feature"
    )

    decorative = [e for e in section["content"] if e["role"] == "decorative_media"]
    assert [e["attributes"]["alt"] for e in decorative] == ["Saxophone player mascot"]


def test_the_render_address_does_not_outlive_the_render() -> None:
    """A saved page served on loopback had every asset recorded against
    http://127.0.0.1:<port>/, a socket that closes when the render ends — so one
    picture was stored twice and the acquirer chased a dead port."""

    from vanjaro_cli.design.html_adapter import RenderedCaptureResult, RenderedPageObservation
    from vanjaro_cli.design.models import BreakpointName, Viewport
    from vanjaro_cli.design.sources.html import HtmlSourceAdapter, HtmlSourceRequest

    served = "http://127.0.0.1:51234/page.html"
    captured = RenderedCaptureResult(
        observations=(
            RenderedPageObservation(
                breakpoint=BreakpointName.DESKTOP,
                viewport=Viewport(width=1440, height=900),
                html=(
                    "<body><section id='hero'><h1>Make ideas clear</h1>"
                    "<p>Strategy and design.</p>"
                    "<img src='http://127.0.0.1:51234/synthetic/hero.jpg' alt='Hero'/>"
                    "</section></body>"
                ),
                sections=(),
            ),
        ),
        warnings=(),
    )

    document = HtmlSourceAdapter(capture=lambda url: captured).analyze(
        HtmlSourceRequest(
            html=(
                "<body><section id='hero'><h1>Make ideas clear</h1>"
                "<p>Strategy and design.</p>"
                "<img src='/synthetic/hero.jpg' alt='Hero'/></section></body>"
            ),
            source_url="file:///c:/work/page.html",
            render_url=served,
            render=True,
        )
    )

    sources = [asset.source_url or "" for asset in document.assets]
    assert sources, "the fixture must register an asset for this test to mean anything"
    assert not any("127.0.0.1" in source for source in sources)
    assert any(source.endswith("/synthetic/hero.jpg") for source in sources)


def test_a_live_source_keeps_its_own_address() -> None:
    """Nothing is rebased when the page was rendered at the address it lives at."""

    from vanjaro_cli.design.html_adapter import RenderedCaptureResult, RenderedPageObservation
    from vanjaro_cli.design.models import BreakpointName, Viewport
    from vanjaro_cli.design.sources.html import HtmlSourceAdapter, HtmlSourceRequest

    captured = RenderedCaptureResult(
        observations=(
            RenderedPageObservation(
                breakpoint=BreakpointName.DESKTOP,
                viewport=Viewport(width=1440, height=900),
                html=(
                    "<body><section id='hero'><h1>Make ideas clear</h1>"
                    "<p>Strategy and design.</p>"
                    "<img src='http://example.test/hero.jpg' alt='Hero'/>"
                    "</section></body>"
                ),
                sections=(),
            ),
        ),
        warnings=(),
    )

    document = HtmlSourceAdapter(capture=lambda url: captured).analyze(
        HtmlSourceRequest(
            html=(
                "<body><section id='hero'><h1>Make ideas clear</h1>"
                "<p>Strategy and design.</p>"
                "<img src='/hero.jpg' alt='Hero'/></section></body>"
            ),
            source_url="http://example.test/page",
            render=True,
        )
    )

    sources = [asset.source_url or "" for asset in document.assets]
    assert sources, "the fixture must register an asset for this test to mean anything"
    assert all("example.test" in source for source in sources)


def test_both_discoveries_use_the_same_builder_rules() -> None:
    """The rendered script queried only section/article, so a DNN page whose
    boundaries are panes produced no rendered candidates at all: every section
    paired to nothing and the site scored on static evidence alone."""

    import inspect

    from vanjaro_cli.design import html_adapter, html_boundaries

    script = html_adapter._RENDERED_OBSERVATION_JS
    static_source = inspect.getsource(html_boundaries.static_boundary_candidates)

    builder_selectors = [
        "[data-elementor-type] > [data-id][data-element_type='container']",
        "#Body > [id^='dnn_']",
    ]
    for selector in builder_selectors:
        assert selector in static_source, f"static side lost {selector!r}"
        assert selector in script, f"rendered side lost {selector!r}"

    # The pane rule is a shared predicate on the Python side, because the
    # section extractor needs it too and a third copy of the shape is how the
    # readings drift. The browser cannot call it, so the selector it runs must
    # still select exactly what the predicate accepts.
    pane_selector = "[id^='dnn_'][class*='Pane']"
    assert pane_selector in script, "rendered side lost the pane selector"
    assert "is_builder_pane" in static_source, "static side stopped sharing the predicate"

    from bs4 import BeautifulSoup

    from vanjaro_cli.migration.sections import is_builder_pane

    soup = BeautifulSoup(
        "<div id='dnn_TopPane' class='Pane'>a</div>"
        "<div id='dnn_ContentPane' class='DnnModule Pane wide'>b</div>"
        "<div id='dnn_content'>c</div>"
        "<div id='other_Pane' class='Pane'>d</div>"
        "<div class='Pane'>e</div>"
        # Case matters: a CSS attribute match is case-sensitive, and a looser
        # Python reading selects panes the browser does not.
        "<div id='dnn_lower' class='pane'>f</div>",
        "html.parser",
    )
    assert soup.select(pane_selector) == soup.find_all(is_builder_pane)


def test_the_rendered_script_drops_wrapper_panes_too() -> None:
    """Pairing is by selector, so both sides must agree on which elements are
    boundaries — the static side drops a pane that wraps other panes."""

    from vanjaro_cli.design import html_adapter

    assert "el.contains(other)" in html_adapter._RENDERED_OBSERVATION_JS


_XHR_FORM = """
<body><section id="enquiry"><h3>Contact Us</h3>
  <input id="Name" name="Name" type="text"/>
  <input id="Email" name="Email" type="text"/>
  <textarea id="Message" name="Message"></textarea>
  <input type="hidden" name="__VIEWSTATE" value="x"/>
  <textarea name="g-recaptcha-response"></textarea>
  <button type="button" class="btn submit">Send Now</button>
</section></body>
"""


def test_a_form_that_posts_over_xhr_is_still_a_form() -> None:
    """A DNN ActionForm emits no <form> element, so a section holding Name,
    Email, Message and a Send button read as a call to action — and forms are
    never rebuilt as HTML."""

    assert _role_of(_XHR_FORM, "enquiry") == "contact"


def test_hidden_and_captcha_fields_are_not_counted() -> None:
    from bs4 import BeautifulSoup

    from vanjaro_cli.migration.sections import visible_form_fields

    section = BeautifulSoup(_XHR_FORM, "html.parser").find("section")

    names = [field.get("name") for field in visible_form_fields(section)]
    assert names == ["Name", "Email", "Message"]


def test_a_search_box_is_not_a_contact_form() -> None:
    """One field and a button is a search box, not somewhere to reach anyone."""

    from bs4 import BeautifulSoup

    from vanjaro_cli.migration.sections import has_form_fields

    section = BeautifulSoup(
        "<section><input name='q' type='text'/><button>Search</button></section>",
        "html.parser",
    ).find("section")

    assert not has_form_fields(section)


def test_fields_with_nothing_to_submit_them_are_not_a_form() -> None:
    from bs4 import BeautifulSoup

    from vanjaro_cli.migration.sections import has_form_fields

    section = BeautifulSoup(
        "<section><input name='a'/><input name='b'/></section>", "html.parser"
    ).find("section")

    assert not has_form_fields(section)


def test_the_legacy_extractor_agrees_it_is_contact() -> None:
    """Both discoveries must agree, or a form is a form on one side only."""

    from vanjaro_cli.migration.sections import extract_sections

    sections = extract_sections(_XHR_FORM, "http://example.test/")

    assert [section["type"] for section in sections] == ["contact"]


def test_a_form_without_a_form_element_is_still_inventoried() -> None:
    """The placeholder that replaces a form is built from its fields, and a
    form nobody listed is a form rebuilt as a lookalike."""

    from vanjaro_cli.migration.sections import extract_sections

    content = extract_sections(_XHR_FORM, "http://example.test/")[0]["content"]

    assert [field["label"] for field in content["form_fields"]] == ["Name", "Email", "Message"]


def test_a_captcha_response_is_not_a_field_to_rebuild() -> None:
    """Listing it on a placeholder would ask a human to rebuild plumbing."""

    from vanjaro_cli.migration.sections import extract_sections

    content = extract_sections(_XHR_FORM, "http://example.test/")[0]["content"]

    assert not any("recaptcha" in field["name"] for field in content["form_fields"])


def test_enrichment_does_not_drop_the_form_it_was_given() -> None:
    """Enrichment replaces the content list wholesale, so a form inventoried by
    extraction is lost unless it is re-emitted."""

    from bs4 import BeautifulSoup

    section = _enriched(
        str(BeautifulSoup(_XHR_FORM, "html.parser").find("section")), "contact"
    )

    fields = [element for element in section["content"] if element["role"] == "form_field"]
    assert [element["value"] for element in fields] == ["Name", "Email", "Message"]
    assert all(element["kind"] == "form_placeholder" for element in fields)


def test_a_section_with_no_form_gains_no_form_fields() -> None:
    section = _enriched(
        "<section><h2>Studio hours</h2><p>Weekdays.</p></section>", "rich_text"
    )

    assert not [e for e in section["content"] if e["role"] == "form_field"]


def test_the_rendered_script_names_an_id_less_element_the_same_way() -> None:
    """The rendered side fell back to a positional label, so an element without
    an id could never pair and a real page's header measured nothing."""

    from vanjaro_cli.design import html_adapter

    script = html_adapter._RENDERED_OBSERVATION_JS

    assert "nth-of-type" in script, "rendered side lost its structural selector"
    assert "structuralSelector" in script


def test_a_structural_selector_can_pair() -> None:
    """Only a positional label is unusable; a structural path names exactly one
    element and is what the static side records for anything without an id."""

    from vanjaro_cli.design.html_adapter import (
        BoundingBox,
        RenderedPageObservation,
        RenderedSectionObservation,
        _pair_rendered_sections,
    )
    from vanjaro_cli.design.models import BreakpointName, Viewport

    path = "body:nth-of-type(1) > header:nth-of-type(1)"
    observation = RenderedPageObservation(
        breakpoint=BreakpointName.DESKTOP,
        viewport=Viewport(width=1440, height=900),
        html="<body></body>",
        sections=(
            RenderedSectionObservation(
                selector=path,
                bounds=BoundingBox(x=0, y=0, width=1440, height=90),
                hidden=False,
            ),
        ),
    )

    paired = _pair_rendered_sections([{"_static_selector": path}], observation)

    assert list(paired) == [0]


def test_a_positional_label_still_cannot_pair() -> None:
    """It names no element and would match by coincidence."""

    from vanjaro_cli.design.html_adapter import (
        BoundingBox,
        RenderedPageObservation,
        RenderedSectionObservation,
        _pair_rendered_sections,
    )
    from vanjaro_cli.design.models import BreakpointName, Viewport

    observation = RenderedPageObservation(
        breakpoint=BreakpointName.DESKTOP,
        viewport=Viewport(width=1440, height=900),
        html="<body></body>",
        sections=(
            RenderedSectionObservation(
                selector="rendered-section-1",
                bounds=BoundingBox(x=0, y=0, width=1440, height=90),
                hidden=False,
            ),
        ),
    )

    paired = _pair_rendered_sections(
        [{"_static_selector": "#a"}, {"_static_selector": "#b"}], observation
    )

    assert paired == {}


def test_both_sides_find_a_heading_the_same_way() -> None:
    """The static side promotes a styled block to the section title when there
    is no heading element. The rendered side sampled only h1-h6, so a hero
    titled with a div had a title on one side and no typography on the other."""

    from vanjaro_cli.design import html_adapter

    script = html_adapter._RENDERED_OBSERVATION_JS

    assert "headingElement" in script, "rendered side lost its shape-based heading"
    assert "typeOf(headingElement(el))" in script


def test_the_rendered_heading_prefers_a_real_heading_element() -> None:
    """Same order the static side uses: a real heading first."""

    from vanjaro_cli.design import html_adapter

    script = html_adapter._RENDERED_OBSERVATION_JS
    body = script[script.index("const headingElement") : script.index("const bodyElement")]

    assert body.index("h1, h2, h3, h4, h5, h6") < body.index("blocks.length < 2")


def test_the_rendered_heading_is_the_most_prominent_not_the_first() -> None:
    """A section led by a small kicker stamped the kicker's font as the
    section's heading; the static side stopped doing that in iteration 42."""

    from vanjaro_cli.design import html_adapter

    script = html_adapter._RENDERED_OBSERVATION_JS
    start = script.index("const headingElement")
    block = script[start : start + 700]

    assert "reduce" in block, "rendered side went back to taking the first heading"
    assert "tagName[1]" in block


def test_the_heading_font_is_stamped_on_the_most_prominent_heading() -> None:
    """Claiming the value for any other element asserts a measurement that was
    never taken."""

    from vanjaro_cli.design.html_adapter import _sampled_element

    elements = [
        {"kind": "heading", "role": "eyebrow", "attributes": {"level": 5}},
        {"kind": "heading", "role": "section_title", "attributes": {"level": 2}},
    ]

    assert _sampled_element(elements, "heading")["role"] == "section_title"


def test_equal_headings_fall_back_to_document_order() -> None:
    from vanjaro_cli.design.html_adapter import _sampled_element

    elements = [
        {"kind": "heading", "role": "first", "attributes": {"level": 2}},
        {"kind": "heading", "role": "second", "attributes": {"level": 2}},
    ]

    assert _sampled_element(elements, "heading")["role"] == "first"


def test_a_body_sample_still_takes_the_first_of_its_kind() -> None:
    """Only headings are chosen by prominence; the browser's own query returns
    the first for everything else."""

    from vanjaro_cli.design.html_adapter import _sampled_element

    elements = [
        {"kind": "text", "role": "body", "attributes": {}},
        {"kind": "text", "role": "body_two", "attributes": {}},
    ]

    assert _sampled_element(elements, "text")["role"] == "body"


def test_a_page_whose_second_pane_never_became_a_section_says_so() -> None:
    """The raw extractor takes the wrapper as ONE section, so its content dict
    holds both panes; matching then narrows that section to the first pane and
    enrichment rebuilds its content from that pane's DOM alone. The second
    pane's words were extracted and then discarded, and nothing said so."""

    document = design_document_from_html(
        "<html><body><section id='dnn_content'>"
        "<div id='dnn_TopPane' class='Pane'><h1>Contact Us</h1>"
        "<p>Have a project in mind?</p></div>"
        "<div id='dnn_SidePane' class='Pane'><h2>Give us a call</h2>"
        "<p>Reach the team on PO Box 773.</p></div>"
        "</section></body></html>",
        "https://example.invalid/contact",
    )

    values = {
        element.value
        for page in document.pages
        for section in page.sections
        for element in section.content
    }
    dropped = [w for w in document.warnings if w.code == "boundary_content_dropped"]

    kept, lost = ("Contact Us", "Give us a call")
    if "Contact Us" not in values:
        kept, lost = lost, kept
    assert kept in values and lost not in values
    assert len(dropped) == 1
    assert "2 text run(s)" in dropped[0].message


def test_a_multi_page_crawl_reports_the_boundary_each_page_dropped() -> None:
    """The multi-page entry has its own wiring, and a crawl is where an unnoticed
    drop repeats across every page that shares the layout."""

    def page(slug: str, aside: str) -> HtmlPageInput:
        return HtmlPageInput(
            url=f"https://example.invalid/{slug}",
            html=(
                "<html><body><section id='dnn_content'>"
                "<div id='dnn_TopPane' class='Pane'><h1>Contact Us</h1>"
                "<p>Have a project in mind?</p></div>"
                f"<div id='dnn_SidePane' class='Pane'><h2>{aside}</h2>"
                "<p>Reach the team on PO Box 773.</p></div>"
                "</section></body></html>"
            ),
            slug=slug,
        )

    document = analyze_html_pages([page("contact", "Give us a call"), page("about", "Find us")])

    dropped = [w for w in document.warnings if w.code == "boundary_content_dropped"]
    assert [w.path for w in dropped] == ["#dnn_TopPane", "#dnn_TopPane"]


def test_a_boundary_repeating_copy_another_section_carries_is_not_reported() -> None:
    """A decorative marquee repeating a phrase a real section also carries went
    unclaimed on the best-scoring project measured. Nothing was lost, so naming
    it would send the next iteration after a boundary that costs the page
    nothing — which is how a queue fills with noise."""

    document = design_document_from_html(
        "<html><body><section id='dnn_content'>"
        "<div id='dnn_TopPane' class='Pane'><h1>Music is magic!</h1>"
        "<p>Lessons for every age.</p></div>"
        "<div id='dnn_MarqueePane' class='Pane'><span>Music is magic!</span>"
        "<span>Music is magic!</span></div>"
        "</section></body></html>",
        "https://example.invalid/home",
    )

    dropped = [w for w in document.warnings if w.code == "boundary_content_dropped"]
    assert [w.path for w in dropped] == []


def _pane_page(slug: str, first: str, second: str) -> HtmlPageInput:
    return HtmlPageInput(
        url=f"https://example.invalid/{slug}",
        html=(
            "<html><body><section id='dnn_content'>"
            f"<div id='dnn_TopPane' class='Pane'>{first}</div>"
            f"<div id='dnn_SidePane' class='Pane'>{second}</div>"
            "</section></body></html>"
        ),
        slug=slug,
    )


def test_a_picture_that_arrives_by_another_route_is_not_reported_as_dropped() -> None:
    """A page keeps a picture as a content element, a section background or a
    decorative layer. Only the first is an element, so comparing elements alone
    would report every promoted banner image as lost."""

    document = design_document_from_html(
        "<html><body><section id='dnn_content'>"
        "<div id='dnn_TopPane' class='Pane'><h1>Keys to Success</h1>"
        "<p>Lessons for every age in Detroit.</p><img src='/badge.png' alt='Badge'></div>"
        "<div id='dnn_SidePane' class='Pane'><img src='/badge.png' alt='Badge'></div>"
        "</section></body></html>",
        "https://example.invalid/home",
    )

    dropped = [w for w in document.warnings if w.code == "boundary_content_dropped"]
    assert [w.path for w in dropped] == []


def test_one_page_keeping_a_block_does_not_vouch_for_another_that_dropped_it() -> None:
    """A crawl repeats its layout, so pooling every page's content would let a
    page that kept a shared block silence the page that lost it."""

    dropping = _pane_page(
        "contact",
        "<h1>Contact the studio today</h1><p>Have a project in mind? Ask us anything at all.</p>",
        "<h2>Shared block</h2><p>Shared block copy.</p>",
    )
    keeping = HtmlPageInput(
        url="https://example.invalid/about",
        html=(
            "<html><body><section id='dnn_content'>"
            "<div id='dnn_TopPane' class='Pane'><h2>Shared block</h2>"
            "<p>Shared block copy.</p></div>"
            "</section></body></html>"
        ),
        slug="about",
    )

    document = analyze_html_pages([dropping, keeping])

    dropped = [w for w in document.warnings if w.code == "boundary_content_dropped"]
    assert [w.path for w in dropped] == ["#dnn_SidePane"]


def test_markup_comments_and_scripts_are_not_counted_as_lost_content() -> None:
    """DNN pages carry cache directives as HTML comments — dozens per page —
    and inline scripts alongside the copy. Counting either would inflate every
    report with text no visitor ever saw — as would counting one repeated line
    once per repetition, which is what a marquee is."""

    document = design_document_from_html(
        "<html><body><section id='dnn_content'>"
        "<div id='dnn_TopPane' class='Pane'><h1>Keys to Success</h1>"
        "<p>Lessons for every age in Detroit.</p></div>"
        "<div id='dnn_SidePane' class='Pane'>"
        "<!-- CDF(Css|/Portals/_default/container.css|DnnPageHeaderProvider|10) -->"
        "<p>Reach the studio on PO Box 773.</p>"
        "<!-- Container Title -->"
        "<p>Reach the studio on PO Box 773.</p>"
        "<script>var dnnLoader = 1;</script></div>"
        "</section></body></html>",
        "https://example.invalid/home",
    )

    dropped = [w for w in document.warnings if w.code == "boundary_content_dropped"]
    assert [w.path for w in dropped] == ["#dnn_SidePane"]
    assert "1 text run(s)" in dropped[0].message


def _section_losses(document):
    return {
        w.path: w.message
        for w in document.warnings
        if w.code == "section_content_dropped"
    }


def test_a_section_that_keeps_less_than_its_boundary_offered_says_so() -> None:
    """Once a boundary IS claimed, whatever the section fails to extract from it
    is invisible: no loss entry, no dropped-boundary warning, and the element
    count has nothing to compare against. contact-page's contact panel arrived
    and stopped being reported while five of its twelve runs were still gone."""

    document = design_document_from_html(
        "<html><body><section id='dnn_content'>"
        "<div id='dnn_TopPane' class='Pane'><h2>Give us a call</h2>"
        "<address>Clicks and Mortar</address>"
        "<address>PO Box 773</address></div>"
        "</section></body></html>",
        "https://example.invalid/contact",
    )

    losses = _section_losses(document)
    assert list(losses) == ["#dnn_TopPane"]
    assert "kept 1 of 3" in losses["#dnn_TopPane"]


def test_a_section_that_kept_everything_is_not_reported() -> None:
    document = design_document_from_html(
        "<html><body><section id='dnn_content'>"
        "<div id='dnn_TopPane' class='Pane'><h2>Give us a call</h2>"
        "<p>We answer the phone every weekday morning.</p></div>"
        "</section></body></html>",
        "https://example.invalid/contact",
    )

    assert _section_losses(document) == {}


def test_a_form_controls_own_text_is_not_counted_as_lost() -> None:
    """A form is migrated as a placeholder listing its detected fields, never as
    markup, so a label and a submit button are absent by design."""

    document = design_document_from_html(
        "<html><body><section id='dnn_content'>"
        "<div id='dnn_TopPane' class='Pane'><h2>Get in touch</h2>"
        "<p>We answer the phone every weekday morning.</p>"
        "<label>Security</label><button>Send Now</button></div>"
        "</section></body></html>",
        "https://example.invalid/contact",
    )

    assert _section_losses(document) == {}


def test_a_form_ancestor_does_not_hold_back_the_page_around_it() -> None:
    """An ASP.NET page wraps its whole body in one `<form runat=server>`. Reading
    a form ancestor as ownership suppressed 61 of the 63 measured losses,
    including a pricing table and eight portfolio links."""

    document = design_document_from_html(
        "<html><body><form id='Form'><section id='dnn_content'>"
        "<div id='dnn_TopPane' class='Pane'><h2>Our prices</h2>"
        "<address>PO Box 773</address></div>"
        "</section></form></body></html>",
        "https://example.invalid/prices",
    )

    losses = _section_losses(document)
    assert list(losses) == ["#dnn_TopPane"]
    assert "kept 1 of 2" in losses["#dnn_TopPane"]


def test_rebuilt_chrome_is_not_reported_as_losing_its_markup() -> None:
    """A header is rebuilt from its links rather than extracted, so a DNN login
    control is absent by design and is not content the visitor lost."""

    document = design_document_from_html(
        "<html><body>"
        "<header id='header'><span>Freephone 0800 111 222</span>"
        "<nav><a href='/'>Home</a><a href='/work'>Work</a>"
        "<a href='/login'>Login</a></nav></header>"
        "<section id='dnn_content'><div id='dnn_TopPane' class='Pane'>"
        "<h2>Give us a call</h2><p>We answer every weekday morning.</p></div>"
        "</section></body></html>",
        "https://example.invalid/contact",
    )

    assert _section_losses(document) == {}


def test_one_line_repeated_is_one_missing_run() -> None:
    """A marquee repeats its phrase a dozen times. Counting each repetition
    separately makes a one-line loss read as a catastrophe."""

    document = design_document_from_html(
        "<html><body><section id='dnn_content'>"
        "<div id='dnn_TopPane' class='Pane'><h2>Give us a call</h2>"
        "<address>PO Box 773</address><address>PO Box 773</address>"
        "<address>PO Box 773</address></div>"
        "</section></body></html>",
        "https://example.invalid/contact",
    )

    assert "kept 1 of 2" in _section_losses(document)["#dnn_TopPane"]


def test_copy_split_by_an_inline_tag_is_not_reported_as_lost() -> None:
    """A paragraph carrying `<strong>` reaches the document as one joined value
    while the source offers it as separate runs. Comparing for equality reports
    every emphasised sentence on the page as missing."""

    document = design_document_from_html(
        "<html><body><section id='dnn_content'>"
        "<div id='dnn_TopPane' class='Pane'><h2>Give us a call</h2>"
        "<p>We answer <strong>every weekday</strong> morning without fail.</p></div>"
        "</section></body></html>",
        "https://example.invalid/contact",
    )

    assert _section_losses(document) == {}


def test_an_id_beginning_with_a_digit_does_not_take_down_the_analysis() -> None:
    """`css_selector_for` emits `#<id>` verbatim and a real page carries section
    ids like `1f670a38`, which is not a valid CSS identifier. Selecting it
    RAISES rather than returning nothing, and that failed the whole analyze
    stage on kts-fidelity — the browser's `querySelector` cannot read it
    either."""

    document = design_document_from_html(
        "<html><body>"
        "<header class='site-header'><nav><a href='/'>Home</a><a href='/x'>Work</a></nav></header>"
        "<section id='kts-hero'><h1>Music for everyone</h1>"
        "<p>Lessons for every age in Detroit.</p></section>"
        "<section id='1f670a38'><h2>Give us a call</h2>"
        "<address>PO Box 773</address></section>"
        "<footer class='site-footer'><p>Copyright 2026.</p></footer>"
        "</body></html>",
        "https://example.invalid/contact",
    )

    assert "kept 1 of 2" in _section_losses(document)["#1f670a38"]
