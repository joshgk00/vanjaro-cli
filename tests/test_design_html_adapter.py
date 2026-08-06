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
                    for index in range(3)
                )
            ),
        ),
    )

    bounds = _bounds_by_role(document)
    assert bounds["hero"] == 0.0
    assert bounds["rich_text"] == 100.0
    assert bounds["call_to_action"] == 200.0


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
