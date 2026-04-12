"""Tests for vanjaro_cli.migration.tokens.extract_design_tokens.

These tests construct a fake homepage HTML with an inline ``<style>`` block
so they don't need to mock external HTTP requests for the linked-stylesheet
path. The CSS content is what the extractor really cares about — the link
fetching is exercised separately through the migrate crawl integration.
"""

from __future__ import annotations

from vanjaro_cli.migration.tokens import extract_design_tokens

BASE_URL = "https://example.com/"


def _homepage(css: str) -> str:
    return f"<!doctype html><html><head><style>{css}</style></head><body></body></html>"


def test_extract_resolves_root_css_variables():
    """``var(--brand-primary)`` references must resolve to the value in :root."""
    css = """
    :root {
      --brand-primary: #0f3d81;
      --font-heading: "Inter";
    }
    .hero { color: var(--brand-primary); font-family: var(--font-heading), sans-serif; }
    """

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    assert "#0f3d81" in tokens["brand_colors"]
    assert "Inter" in tokens["fonts"]
    # The raw var() reference must NOT leak into the output.
    assert not any("var(" in font for font in tokens["fonts"])
    assert tokens["css_variables"] == {
        "brand-primary": "#0f3d81",
        "font-heading": '"Inter"',
    }


def test_extract_filters_bootstrap_alert_colors():
    """Bootstrap default alert palette should not pollute brand_colors."""
    css = """
    .alert-success { background: #d4edda; color: #155724; border-color: #c3e6cb; }
    .alert-danger  { background: #f8d7da; color: #721c24; border-color: #f5c6cb; }
    .brand { color: #0f3d81; }
    .brand-alt { background: #0f3d81; }
    """

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    assert "#0f3d81" in tokens["brand_colors"]
    assert "#d4edda" not in tokens["brand_colors"]
    assert "#155724" not in tokens["brand_colors"]
    assert "#f8d7da" not in tokens["brand_colors"]
    assert "#721c24" not in tokens["brand_colors"]


def test_extract_splits_neutral_colors_from_brand():
    """Pure black/white/transparent values go in neutral_colors, not brand_colors."""
    css = """
    body { color: #000000; background: #ffffff; }
    .overlay { background: rgba(0, 0, 0, 0.5); }
    .frosted { background: rgba(255, 255, 255, 0.8); }
    .accent { color: #ff5733; }
    """

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    assert "#ff5733" in tokens["brand_colors"]
    assert "#000000" not in tokens["brand_colors"]
    assert "#ffffff" not in tokens["brand_colors"]

    assert "#000000" in tokens["neutral_colors"]
    assert "#ffffff" in tokens["neutral_colors"]
    # rgba(0,0,0,*) variants should land in neutrals too.
    assert any("rgba(0, 0, 0" in c.replace(" ", " ") for c in tokens["neutral_colors"])


def test_extract_filters_system_font_fallbacks():
    """Generic font fallbacks must not show up in the brand fonts list."""
    css = """
    body { font-family: 'Inter', Arial, sans-serif; }
    h1 { font-family: 'Playfair Display', Georgia, serif; }
    pre { font-family: monospace; }
    .x { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI'; }
    """

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    assert "Inter" in tokens["fonts"]
    assert "Playfair Display" in tokens["fonts"]
    # System fonts and generic families should be filtered out.
    for fallback in ("Arial", "sans-serif", "Georgia", "serif", "monospace", "-apple-system"):
        assert fallback not in tokens["fonts"]


def test_extract_frequency_ranks_brand_colors():
    """The most-used colors come first in the brand_colors list."""
    css = """
    .a { color: #aabbcc; }
    .b { color: #aabbcc; }
    .c { color: #aabbcc; }
    .d { color: #112233; }
    .e { color: #ddeeff; }
    """

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    assert tokens["brand_colors"][0] == "#aabbcc"
    assert "#112233" in tokens["brand_colors"]
    assert "#ddeeff" in tokens["brand_colors"]


def test_extract_var_with_fallback_uses_fallback_when_undefined():
    """``var(--missing, #fallback)`` should resolve to the fallback value."""
    css = """
    .x { color: var(--missing-var, #c0ffee); }
    """

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    assert "#c0ffee" in tokens["brand_colors"]


def test_extract_var_recursion_terminates():
    """Circular variable definitions must not infinite-loop."""
    css = """
    :root {
      --a: var(--b);
      --b: var(--a);
    }
    .x { color: var(--a); }
    """

    # Should return without raising or hanging — extractor caps recursion depth.
    tokens = extract_design_tokens(_homepage(css), BASE_URL)
    assert "css_variables" in tokens


def test_extract_returns_expected_output_shape():
    """Result dict must contain every documented key."""
    tokens = extract_design_tokens(_homepage(".x { color: #ff5733; }"), BASE_URL)

    expected_keys = {
        "colors", "brand_colors", "neutral_colors", "fonts", "spacing", "css_variables"
    }
    assert expected_keys <= set(tokens.keys())


def test_extract_legacy_colors_key_matches_brand_colors():
    """Backward compat: ``colors`` key (legacy) must equal ``brand_colors`` (new)."""
    css = """
    .x { color: #ff5733; background: #112233; }
    .y { color: #fff; background: #d4edda; }
    """

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    assert tokens["colors"] == tokens["brand_colors"]
    # Bootstrap alert and neutral white should not appear in either.
    assert "#d4edda" not in tokens["colors"]
    assert "#fff" not in tokens["colors"]


def test_extract_handles_missing_root_block():
    """When the CSS has no :root variables the extractor still returns cleanly."""
    css = ".x { color: #ff5733; font-family: 'Inter', sans-serif; }"

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    assert tokens["css_variables"] == {}
    assert "#ff5733" in tokens["brand_colors"]
    assert "Inter" in tokens["fonts"]


# --- Framework color filtering ---


def test_extract_filters_bootstrap_grayscale_utilities():
    """Bootstrap gray-100 through gray-900 should not appear in brand_colors."""
    css = """
    .bg-light { background: #f8f9fa; }
    .text-muted { color: #6c757d; }
    .bg-dark { background: #212529; }
    .border { border-color: #dee2e6; }
    .brand { color: #e63946; }
    """

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    assert "#e63946" in tokens["brand_colors"]
    assert "#f8f9fa" not in tokens["brand_colors"]
    assert "#6c757d" not in tokens["brand_colors"]
    assert "#212529" not in tokens["brand_colors"]
    assert "#dee2e6" not in tokens["brand_colors"]


def test_extract_filters_low_alpha_rgba_colors():
    """rgba values with alpha < 0.3 are hover/overlay effects, not brand colors."""
    css = """
    .overlay { background: rgba(0, 100, 200, 0.1); }
    .hover { background: rgba(50, 50, 50, 0.2); }
    .solid-accent { color: rgba(230, 57, 70, 0.9); }
    .half-opacity { background: rgba(100, 200, 50, 0.5); }
    """

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    assert "rgba(0, 100, 200, 0.1)" not in tokens["brand_colors"]
    assert "rgba(50, 50, 50, 0.2)" not in tokens["brand_colors"]
    assert "rgba(230, 57, 70, 0.9)" in tokens["brand_colors"]
    assert "rgba(100, 200, 50, 0.5)" in tokens["brand_colors"]


def test_extract_low_alpha_threshold_boundary_is_strict_less_than():
    """Alpha exactly at 0.3 is kept; alpha at 0.29 is filtered."""
    css = """
    .at-threshold { background: rgba(10, 20, 30, 0.3); }
    .just-below { background: rgba(40, 50, 60, 0.29); }
    """

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    # 0.3 is the threshold — filter is `< 0.3`, so 0.3 itself must NOT be filtered
    assert "rgba(10, 20, 30, 0.3)" in tokens["brand_colors"]
    # 0.29 is just below — must be filtered
    assert "rgba(40, 50, 60, 0.29)" not in tokens["brand_colors"]


def test_extract_low_alpha_tolerates_malformed_alpha():
    """A malformed alpha value must not crash the extractor."""
    css = """
    .bad { background: rgba(0, 0, 0, 1.2.3); }
    .good { color: #1d3557; }
    """

    # Should return without raising — lenient extractor contract.
    tokens = extract_design_tokens(_homepage(css), BASE_URL)
    assert "#1d3557" in tokens["brand_colors"]


def test_extract_filters_bootstrap_form_validation_colors():
    """BS5 form validation and component default colors should be filtered."""
    css = """
    .btn-primary { background: #0d6efd; }
    .btn-success { background: #198754; }
    .btn-danger { background: #dc3545; }
    .custom-brand { color: #2a9d8f; }
    """

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    assert "#2a9d8f" in tokens["brand_colors"]
    assert "#0d6efd" not in tokens["brand_colors"]
    assert "#198754" not in tokens["brand_colors"]
    assert "#dc3545" not in tokens["brand_colors"]


# --- Typography extraction ---


def test_extract_typography_font_sizes():
    """Font sizes should be extracted and frequency-ranked."""
    css = """
    body { font-size: 16px; }
    h1 { font-size: 48px; }
    h2 { font-size: 32px; }
    p { font-size: 16px; }
    .small { font-size: 14px; }
    """

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    typography = tokens["typography"]
    assert "16px" in typography["font_sizes"]
    assert "48px" in typography["font_sizes"]
    assert "32px" in typography["font_sizes"]
    # 16px appears twice, should rank first
    assert typography["font_sizes"][0] == "16px"


def test_extract_typography_font_size_supports_all_units():
    """SIZE_VALUE regex must capture px/rem/em/%/vw/vh."""
    css = """
    .a { font-size: 2rem; }
    .b { font-size: 1.5em; }
    .c { font-size: 5vh; }
    .d { font-size: 10vw; }
    .e { font-size: 120%; }
    """

    sizes = extract_design_tokens(_homepage(css), BASE_URL)["typography"]["font_sizes"]

    for expected in ("2rem", "1.5em", "5vh", "10vw", "120%"):
        assert expected in sizes


def test_extract_typography_font_weights():
    """Font weights should be extracted as unique values."""
    css = """
    body { font-weight: 400; }
    h1 { font-weight: 700; }
    h2 { font-weight: 600; }
    strong { font-weight: bold; }
    .light { font-weight: 300; }
    """

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    weights = tokens["typography"]["font_weights"]
    assert "400" in weights
    assert "700" in weights
    assert "600" in weights
    assert "bold" in weights
    assert "300" in weights


def test_extract_typography_font_weights_dedupe_preserves_first_seen_order():
    """Duplicate weights collapse to one entry in first-seen order."""
    css = """
    .a { font-weight: 400; }
    .b { font-weight: 700; }
    .c { font-weight: 400; }
    .d { font-weight: 300; }
    """

    weights = extract_design_tokens(_homepage(css), BASE_URL)["typography"]["font_weights"]

    assert weights.count("400") == 1
    assert weights.index("400") < weights.index("700") < weights.index("300")


def test_extract_typography_line_heights():
    """Line-height values should be extracted and ranked."""
    css = """
    body { line-height: 1.5; }
    h1 { line-height: 1.2; }
    p { line-height: 1.6; }
    .compact { line-height: 1.5; }
    """

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    line_heights = tokens["typography"]["line_heights"]
    assert "1.5" in line_heights
    assert "1.2" in line_heights
    assert "1.6" in line_heights
    # 1.5 appears twice, should rank first
    assert line_heights[0] == "1.5"


def test_extract_typography_letter_spacings():
    """Letter-spacing values should be extracted."""
    css = """
    h1 { letter-spacing: 0.05em; }
    .uppercase { letter-spacing: 2px; }
    .tight { letter-spacing: -0.02em; }
    """

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    spacings = tokens["typography"]["letter_spacings"]
    assert "0.05em" in spacings
    assert "2px" in spacings
    assert "-0.02em" in spacings


def test_extract_typography_font_usage_context():
    """Fonts should be tagged with usage context based on selector."""
    css = """
    h1, h2, h3 { font-family: 'Playfair Display', serif; font-weight: 700; }
    body, p { font-family: 'Inter', sans-serif; font-weight: 400; }
    """

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    typography_fonts = tokens["typography"]["fonts"]
    playfair = next((f for f in typography_fonts if f["family"] == "Playfair Display"), None)
    inter = next((f for f in typography_fonts if f["family"] == "Inter"), None)

    assert playfair is not None
    assert playfair["usage"] == "headings"
    assert "700" in playfair["weights"]

    assert inter is not None
    assert inter["usage"] == "body"
    assert "400" in inter["weights"]


def test_extract_typography_mixed_usage():
    """Fonts used in both heading and body contexts are tagged 'mixed'."""
    css = """
    h1 { font-family: 'Inter', sans-serif; }
    body { font-family: 'Inter', sans-serif; }
    """

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    typography_fonts = tokens["typography"]["fonts"]
    inter = next((f for f in typography_fonts if f["family"] == "Inter"), None)
    assert inter is not None
    assert inter["usage"] == "mixed"


def test_extract_typography_unknown_usage_context():
    """Fonts declared only in generic selectors get usage='unknown'."""
    css = ".hero-banner { font-family: 'Oswald', sans-serif; font-weight: 500; }"

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    oswald = next(
        (f for f in tokens["typography"]["fonts"] if f["family"] == "Oswald"),
        None,
    )
    assert oswald is not None
    assert oswald["usage"] == "unknown"


def test_extract_typography_skips_unresolved_var_font_family():
    """font-family: var(--unresolved) must not leak into the output."""
    css = """
    h1 { font-family: var(--missing-font), serif; }
    body { font-family: 'Lato', sans-serif; }
    """

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    assert "Lato" in tokens["fonts"]
    assert not any("var(" in font for font in tokens["fonts"])
    assert not any(
        font["family"].startswith("var(") for font in tokens["typography"]["fonts"]
    )


def test_extract_typography_filters_inherit_keywords():
    """Typography keywords like inherit/initial/normal should be filtered."""
    css = """
    .reset { font-weight: inherit; font-size: initial; line-height: normal; }
    h1 { font-weight: 700; font-size: 48px; line-height: 1.2; }
    """

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    typography = tokens["typography"]
    assert "inherit" not in typography["font_weights"]
    assert "initial" not in typography["font_weights"]
    assert "700" in typography["font_weights"]
    assert "48px" in typography["font_sizes"]
    assert "1.2" in typography["line_heights"]


def test_extract_typography_filters_normal_keyword_from_line_height_and_letter_spacing():
    """`normal` is a distinct filter path for line-height and letter-spacing."""
    css = """
    .reset { line-height: normal; letter-spacing: normal; }
    h1 { line-height: 1.2; letter-spacing: 0.05em; }
    """

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    typography = tokens["typography"]
    assert "normal" not in typography["line_heights"]
    assert "normal" not in typography["letter_spacings"]
    assert "1.2" in typography["line_heights"]
    assert "0.05em" in typography["letter_spacings"]


def test_extract_typography_empty_css_returns_empty_structure():
    """When there are no style declarations, typography fields are empty lists."""
    tokens = extract_design_tokens(
        "<!doctype html><html><head></head><body></body></html>",
        BASE_URL,
    )

    typography = tokens["typography"]
    assert typography["font_sizes"] == []
    assert typography["font_weights"] == []
    assert typography["line_heights"] == []
    assert typography["letter_spacings"] == []
    assert typography["fonts"] == []


def test_extract_returns_typography_key():
    """Result dict must include the typography key with expected structure."""
    css = "body { font-size: 16px; font-weight: 400; line-height: 1.5; }"

    tokens = extract_design_tokens(_homepage(css), BASE_URL)

    assert "typography" in tokens
    typography = tokens["typography"]
    assert "font_sizes" in typography
    assert "font_weights" in typography
    assert "line_heights" in typography
    assert "letter_spacings" in typography
    assert "fonts" in typography
