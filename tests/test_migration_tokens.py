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
