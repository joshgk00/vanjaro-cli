"""Pure-logic tests for Phase 5 migration verification comparators."""

from __future__ import annotations

from vanjaro_cli.migration.text_match import (
    fuzzy_set_match,
    normalize_text,
    score_text_match,
)
from vanjaro_cli.migration.verify import (
    collect_source_content,
    verify_global_block,
    verify_page,
)


# -- Helpers --


def _heading_node(text: str, tag: str = "h2") -> dict:
    return {
        "type": "heading",
        "tagName": tag,
        "content": text,
        "attributes": {"id": f"h-{text[:6]}"},
    }


def _paragraph_node(text: str) -> dict:
    return {
        "type": "text",
        "content": text,
        "attributes": {"id": f"p-{text[:6]}"},
    }


def _image_node(src: str) -> dict:
    return {"type": "image", "attributes": {"id": "img", "src": src}}


def _link_node(href: str, text: str = "Click") -> dict:
    return {
        "type": "link",
        "tagName": "a",
        "content": text,
        "attributes": {"id": "a", "href": href},
    }


def _section_node(*children: dict) -> dict:
    return {"type": "section", "attributes": {"id": "s"}, "components": list(children)}


def _source_section(
    *,
    headings: list[str] | None = None,
    paragraphs: list[str] | None = None,
    images: list[dict] | None = None,
    links: list[dict] | None = None,
    buttons: list[dict] | None = None,
    section_type: str = "content",
) -> dict:
    return {
        "type": section_type,
        "template": "Rich Text Block",
        "content": {
            "headings": headings or [],
            "paragraphs": paragraphs or [],
            "images": images or [],
            "links": links or [],
            "buttons": buttons or [],
        },
    }


def _manifest_entry(source_url: str, vanjaro_url: str | None = None) -> dict:
    return {
        "source_url": source_url,
        "local_file": source_url.rsplit("/", 1)[-1],
        "vanjaro_url": vanjaro_url,
        "uploaded": vanjaro_url is not None,
    }


# -- normalize_text --


def test_normalize_text_collapses_whitespace():
    assert normalize_text("hello\n  world\t\t!") == "hello world !"


def test_normalize_text_decodes_html_entities():
    assert normalize_text("Smith &amp; Co.") == "Smith & Co."


def test_normalize_text_preserves_case_and_punctuation():
    assert normalize_text("Welcome HOME!") == "Welcome HOME!"


def test_normalize_text_handles_non_string_input():
    assert normalize_text(None) == ""  # type: ignore[arg-type]


# -- fuzzy_set_match --


def test_fuzzy_set_match_exact_matches_all():
    matched, missing = fuzzy_set_match(["Hello", "World"], ["Hello", "World"])
    assert matched == ["Hello", "World"]
    assert missing == []


def test_fuzzy_set_match_tolerates_minor_differences():
    # Section reordering + a trailing whitespace doesn't break matching.
    matched, missing = fuzzy_set_match(
        ["Welcome to our site"], ["welcome to our site  "]
    )
    # These differ only in case and trailing whitespace — above the 0.85 ratio.
    assert len(matched) == 1
    assert missing == []


def test_fuzzy_set_match_flags_missing_below_threshold():
    matched, missing = fuzzy_set_match(
        ["Unique heading"], ["Totally unrelated content"]
    )
    assert matched == []
    assert missing == ["Unique heading"]


def test_fuzzy_set_match_is_greedy_one_to_one():
    # Both source items are close to the single migrated item — only one
    # can claim it.
    matched, missing = fuzzy_set_match(
        ["Our team", "Our teams"], ["Our team"]
    )
    assert len(matched) == 1
    assert len(missing) == 1


# -- score_text_match --


def test_score_text_match_perfect_score():
    result = score_text_match(
        source_headings=["A", "B"],
        source_paragraphs=["P1", "P2"],
        migrated_headings=["A", "B"],
        migrated_paragraphs=["P1", "P2"],
        threshold=0.9,
    )
    assert result.score == 1.0
    assert result.passed is True
    assert result.missing_headings == []


def test_score_text_match_combined_divisor():
    result = score_text_match(
        source_headings=["A", "B"],
        source_paragraphs=["P1", "P2"],
        migrated_headings=["A"],
        migrated_paragraphs=["P1"],
    )
    # 2 / 4 matched across the combined heading+paragraph pool
    assert result.score == 0.5
    assert result.passed is False
    assert result.missing_headings == ["B"]
    assert result.missing_paragraphs == ["P2"]


def test_score_text_match_empty_inputs_trivially_passes():
    result = score_text_match([], [], [], [])
    assert result.score == 1.0
    assert result.passed is True


# -- collect_source_content --


def test_collect_source_content_flattens_multiple_sections():
    sections = [
        _source_section(
            headings=["Welcome"],
            paragraphs=["Intro copy."],
            images=[{"src": "/hero.jpg", "alt": ""}],
            buttons=[{"text": "Go", "href": "/signup"}],
            section_type="hero",
        ),
        _source_section(
            headings=["Features"],
            images=[{"src": "/a.jpg", "alt": ""}, {"src": "/b.jpg", "alt": ""}],
        ),
    ]

    walked = collect_source_content(sections)

    assert walked.headings == ["Welcome", "Features"]
    assert walked.paragraphs == ["Intro copy."]
    assert walked.images == ["/hero.jpg", "/a.jpg", "/b.jpg"]
    assert walked.links == ["/signup"]
    assert walked.section_count == 2


# -- _compare_images via verify_page --


def test_verify_page_clean_pass():
    sources = [
        _source_section(
            headings=["Welcome"],
            paragraphs=["Lead copy."],
            images=[{"src": "https://src.test/a.jpg", "alt": ""}],
        ),
    ]
    migrated = [
        _section_node(
            _heading_node("Welcome"),
            _paragraph_node("Lead copy."),
            _image_node("/Portals/0/a.jpg"),
        )
    ]
    manifest = [_manifest_entry("https://src.test/a.jpg", "/Portals/0/a.jpg")]

    report = verify_page(
        source_sections=sources,
        migrated_components=migrated,
        asset_manifest=manifest,
        source_page={"title": "Welcome", "url": "https://src.test/"},
        migrated_page={"title": "Welcome", "description": ""},
        text_threshold=0.9,
        page_id=1,
        source_url="https://src.test/",
    )

    assert report.status == "passed"
    assert report.text.score == 1.0
    assert report.images.hard_gaps == []
    assert report.images.soft_gaps == []
    assert report.structure.within_tolerance is True
    assert report.metadata.title_match is True


def test_verify_page_flags_not_uploaded_asset():
    sources = [
        _source_section(
            headings=["Hi"],
            paragraphs=["x"],
            images=[{"src": "https://src.test/a.jpg", "alt": ""}],
        )
    ]
    migrated = [_section_node(_heading_node("Hi"), _paragraph_node("x"))]
    manifest = [_manifest_entry("https://src.test/a.jpg", vanjaro_url=None)]

    report = verify_page(
        source_sections=sources,
        migrated_components=migrated,
        asset_manifest=manifest,
        source_page={"title": "Hi"},
        migrated_page={"title": "Hi"},
        text_threshold=0.9,
        source_url="https://src.test/",
    )

    assert report.status == "failed"
    gap_types = {gap.type for gap in report.images.hard_gaps}
    assert "not_uploaded" in gap_types


def test_verify_page_flags_not_referenced_asset():
    sources = [
        _source_section(
            headings=["Hi"],
            paragraphs=["x"],
            images=[{"src": "https://src.test/a.jpg", "alt": ""}],
        )
    ]
    migrated = [_section_node(_heading_node("Hi"), _paragraph_node("x"))]
    manifest = [_manifest_entry("https://src.test/a.jpg", "/Portals/0/a.jpg")]

    report = verify_page(
        source_sections=sources,
        migrated_components=migrated,
        asset_manifest=manifest,
        source_page={},
        migrated_page={},
        text_threshold=0.9,
        source_url="https://src.test/",
    )

    gap_types = {gap.type for gap in report.images.hard_gaps}
    assert "not_referenced" in gap_types
    assert report.status == "failed"


def test_verify_page_flags_source_url_leak_in_image():
    sources = [
        _source_section(
            headings=["Hi"],
            paragraphs=["x"],
            images=[{"src": "https://src.test/a.jpg", "alt": ""}],
        )
    ]
    migrated = [
        _section_node(
            _heading_node("Hi"),
            _paragraph_node("x"),
            _image_node("https://src.test/a.jpg"),
        )
    ]
    manifest = [_manifest_entry("https://src.test/a.jpg", "/Portals/0/a.jpg")]

    report = verify_page(
        source_sections=sources,
        migrated_components=migrated,
        asset_manifest=manifest,
        source_page={},
        migrated_page={},
        text_threshold=0.9,
        source_url="https://src.test/",
    )

    gap_types = {gap.type for gap in report.images.hard_gaps}
    assert "source_url_in_migrated" in gap_types


def test_verify_page_flags_extra_image_as_soft_gap_only():
    sources = [_source_section(headings=["Hi"], paragraphs=["x"])]
    migrated = [
        _section_node(
            _heading_node("Hi"),
            _paragraph_node("x"),
            _image_node("/Portals/0/placeholder.jpg"),
        )
    ]

    report = verify_page(
        source_sections=sources,
        migrated_components=migrated,
        asset_manifest=[],
        source_page={},
        migrated_page={},
        text_threshold=0.9,
        source_url="https://src.test/",
    )

    # Extra image is a soft gap — shouldn't flip status to failed.
    assert report.status == "passed"
    assert len(report.images.soft_gaps) == 1
    assert report.images.soft_gaps[0].type == "extra_in_migrated"


# -- Links --


def test_verify_page_flags_source_url_leak_in_link():
    sources = [_source_section(headings=["Hi"], paragraphs=["x"])]
    migrated = [
        _section_node(
            _heading_node("Hi"),
            _paragraph_node("x"),
            _link_node("https://src.test/about"),
        )
    ]

    report = verify_page(
        source_sections=sources,
        migrated_components=migrated,
        asset_manifest=[],
        source_page={},
        migrated_page={},
        text_threshold=0.9,
        source_url="https://src.test/",
    )

    assert report.status == "failed"
    assert any(
        gap.type == "source_url_in_migrated" for gap in report.links.hard_gaps
    )


def test_verify_page_flags_broken_internal_link_when_paths_known():
    sources = [_source_section(headings=["Hi"], paragraphs=["x"])]
    migrated = [
        _section_node(
            _heading_node("Hi"),
            _paragraph_node("x"),
            _link_node("/mystery-page"),
        )
    ]

    report = verify_page(
        source_sections=sources,
        migrated_components=migrated,
        asset_manifest=[],
        source_page={},
        migrated_page={},
        text_threshold=0.9,
        source_url="https://src.test/",
        known_vanjaro_paths={"/", "/about"},
    )

    assert report.status == "failed"
    assert any(gap.type == "broken_internal" for gap in report.links.hard_gaps)


def test_verify_page_allows_external_links():
    sources = [_source_section(headings=["Hi"], paragraphs=["x"])]
    migrated = [
        _section_node(
            _heading_node("Hi"),
            _paragraph_node("x"),
            _link_node("https://twitter.com/acme"),
        )
    ]

    report = verify_page(
        source_sections=sources,
        migrated_components=migrated,
        asset_manifest=[],
        source_page={},
        migrated_page={},
        text_threshold=0.9,
        source_url="https://src.test/",
    )

    assert report.links.hard_gaps == []


# -- Structure --


def test_verify_page_structure_tolerates_small_drift():
    sources = [
        _source_section(headings=["A"], paragraphs=["x"]),
        _source_section(headings=["B"], paragraphs=["y"]),
        _source_section(headings=["C"], paragraphs=["z"]),
    ]
    migrated = [
        _section_node(_heading_node("A"), _paragraph_node("x")),
        _section_node(
            _heading_node("B"),
            _paragraph_node("y"),
            _heading_node("C"),
            _paragraph_node("z"),
        ),
    ]

    report = verify_page(
        source_sections=sources,
        migrated_components=migrated,
        asset_manifest=[],
        source_page={},
        migrated_page={},
        text_threshold=0.9,
    )

    # 3 source sections vs 2 migrated — within the ±1 tolerance window.
    assert report.structure.within_tolerance is True


def test_verify_page_structure_outside_tolerance():
    sources = [_source_section(headings=[f"H{i}"]) for i in range(5)]
    migrated = [_section_node(_heading_node("H0"))]

    report = verify_page(
        source_sections=sources,
        migrated_components=migrated,
        asset_manifest=[],
        source_page={},
        migrated_page={},
        text_threshold=0.9,
    )

    assert report.structure.source_sections == 5
    assert report.structure.migrated_sections == 1
    assert report.structure.within_tolerance is False


# -- Metadata --


def test_verify_page_title_match_and_description_skipped_when_empty():
    report = verify_page(
        source_sections=[_source_section(headings=["A"], paragraphs=["b"])],
        migrated_components=[
            _section_node(_heading_node("A"), _paragraph_node("b"))
        ],
        asset_manifest=[],
        source_page={"title": "About Us"},
        migrated_page={"title": "About Us", "description": "Non-empty migrated desc"},
        text_threshold=0.9,
    )

    assert report.metadata.title_match is True
    # Source description is empty — comparison is intentionally skipped so
    # that a migrated description (which the crawler can't yet capture) is
    # treated as neutral.
    assert report.metadata.description_match is True


def test_verify_page_description_mismatch_when_source_has_one():
    report = verify_page(
        source_sections=[_source_section(headings=["A"], paragraphs=["b"])],
        migrated_components=[
            _section_node(_heading_node("A"), _paragraph_node("b"))
        ],
        asset_manifest=[],
        source_page={"title": "About", "description": "Learn about us"},
        migrated_page={"title": "About", "description": ""},
        text_threshold=0.9,
    )

    assert report.metadata.description_match is False


def test_verify_page_title_mismatch():
    report = verify_page(
        source_sections=[_source_section(headings=["A"], paragraphs=["b"])],
        migrated_components=[
            _section_node(_heading_node("A"), _paragraph_node("b"))
        ],
        asset_manifest=[],
        source_page={"title": "Original"},
        migrated_page={"title": "Something Else"},
        text_threshold=0.9,
    )

    assert report.metadata.title_match is False


# -- verify_global_block --


def test_verify_global_block_match():
    source = {
        "type": "header",
        "template": "Site Header",
        "content": {
            "headings": [],
            "paragraphs": [],
            "images": [],
            "links": [
                {"text": "Home", "href": "/"},
                {"text": "About", "href": "/about"},
            ],
            "buttons": [],
        },
    }
    migrated = [
        _section_node(
            _link_node("/", text="Home"),
            _link_node("/about", text="About"),
        )
    ]

    report = verify_global_block(source, migrated)

    assert report.status == "match"
    assert report.missing_links == []


def test_verify_global_block_mismatch_on_missing_link():
    source = {
        "type": "footer",
        "template": "Site Footer",
        "content": {
            "headings": [],
            "paragraphs": [],
            "images": [],
            "links": [
                {"text": "Home", "href": "/"},
                {"text": "Careers", "href": "/careers"},
            ],
            "buttons": [],
        },
    }
    migrated = [_section_node(_link_node("/", text="Home"))]

    report = verify_global_block(source, migrated)

    assert report.status == "mismatch"
    assert report.missing_links == ["Careers"]


# -- Text gap failure path --


def test_verify_page_text_gap_flips_status_to_failed():
    sources = [
        _source_section(
            headings=["Welcome to our site"],
            paragraphs=["Founded in 1998", "We build things", "Our team matters"],
        )
    ]
    migrated = [
        _section_node(_heading_node("Welcome to our site"), _paragraph_node("We build things"))
    ]

    report = verify_page(
        source_sections=sources,
        migrated_components=migrated,
        asset_manifest=[],
        source_page={},
        migrated_page={},
        text_threshold=0.9,
    )

    assert report.status == "failed"
    assert report.text.passed is False
    assert "Founded in 1998" in report.text.missing_paragraphs


# -- Report serialization --


def test_page_report_as_dict_shape():
    report = verify_page(
        source_sections=[_source_section(headings=["A"], paragraphs=["b"])],
        migrated_components=[
            _section_node(_heading_node("A"), _paragraph_node("b"))
        ],
        asset_manifest=[],
        source_page={"title": "A"},
        migrated_page={"title": "A"},
        text_threshold=0.9,
        page_id=7,
        source_url="https://src.test/",
    )

    payload = report.as_dict()

    assert payload["page_id"] == 7
    assert payload["source_url"] == "https://src.test/"
    assert payload["status"] == "passed"
    assert set(payload["text"].keys()) >= {
        "score",
        "threshold",
        "passed",
        "matched_headings",
        "missing_headings",
        "matched_paragraphs",
        "missing_paragraphs",
    }
    assert set(payload["images"].keys()) == {"hard_gaps", "soft_gaps"}
    assert set(payload["links"].keys()) == {"hard_gaps"}
    assert set(payload["structure"].keys()) == {
        "source_sections",
        "migrated_sections",
        "within_tolerance",
    }
    assert "metadata" in payload
    assert "header" not in payload  # only added when flags are used
    assert "footer" not in payload
