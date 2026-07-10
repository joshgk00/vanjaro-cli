"""Pure-logic tests for Figma design-token extraction."""

from __future__ import annotations

from vanjaro_cli.utils.figma_tokens import (
    build_design_tokens,
    build_theme_palette,
    collect_corner_radii,
    collect_image_fills,
    collect_solid_fills,
    collect_text_styles,
    figma_color_to_hex,
)


def solid_fill(r: float, g: float, b: float, opacity: float = 1.0) -> dict:
    return {"type": "SOLID", "color": {"r": r, "g": g, "b": b, "a": 1.0}, "opacity": opacity}


def image_fill(image_ref: str) -> dict:
    return {"type": "IMAGE", "imageRef": image_ref, "scaleMode": "FILL"}


def rect(node_id: str, fills: list[dict], width: float, height: float, **extra: object) -> dict:
    node = {
        "id": node_id,
        "name": f"rect-{node_id}",
        "type": "RECTANGLE",
        "fills": fills,
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": width, "height": height},
    }
    node.update(extra)
    return node


def text(node_id: str, family: str, weight: int, size: float) -> dict:
    return {
        "id": node_id,
        "name": f"text-{node_id}",
        "type": "TEXT",
        "characters": "Sample",
        "fills": [solid_fill(0.06, 0.18, 0.18)],
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 200, "height": size},
        "style": {
            "fontFamily": family,
            "fontWeight": weight,
            "fontSize": size,
            "lineHeightPx": size * 1.2,
            "letterSpacing": 0.0,
        },
    }


# Dark teal #0f2f2f, rust #a24521, gold #fdbb2c, white #ffffff.
DARK_TEAL = (0.0588, 0.1843, 0.1843)
RUST = (0.6353, 0.2706, 0.1294)
GOLD = (0.9922, 0.7333, 0.1725)
WHITE = (1.0, 1.0, 1.0)


def build_fixture_tree() -> dict:
    """A Figma-shaped tree with NO layoutMode and NO shared styles."""
    return {
        "id": "0:1",
        "name": "Home",
        "type": "FRAME",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1440, "height": 8090},
        "children": [
            rect("1", [solid_fill(*WHITE)], 1440, 4000),
            rect("2", [solid_fill(*DARK_TEAL)], 1440, 900, cornerRadius=0),
            rect("3", [solid_fill(*RUST)], 600, 400, cornerRadius=10),
            rect("4", [solid_fill(*RUST)], 300, 200, cornerRadius=8),
            rect("5", [solid_fill(*GOLD)], 200, 60, cornerRadius=200),
            rect("6", [image_fill("aaaa1111")], 1440, 900),
            rect("7", [image_fill("bbbb2222")], 700, 500),
            text("8", "Genova", 700, 56),
            text("9", "Genova", 400, 14),
            text("10", "Genova", 400, 16),
            text("11", "Genova", 400, 14),
        ],
    }


class TestPrimitives:
    def test_color_to_hex(self) -> None:
        assert figma_color_to_hex({"r": 0.0588, "g": 0.1843, "b": 0.1843}) == "#0f2f2f"
        assert figma_color_to_hex({"r": 1.0, "g": 1.0, "b": 1.0}) == "#ffffff"

    def test_collect_solid_fills_weights_by_area(self) -> None:
        fills = collect_solid_fills(build_fixture_tree())
        assert "#0f2f2f" in fills
        assert "#a24521" in fills
        # Rust appears on two rects; its area is the sum.
        assert fills["#a24521"] == 600 * 400 + 300 * 200

    def test_collect_text_styles(self) -> None:
        styles = collect_text_styles(build_fixture_tree())
        assert len(styles) == 4
        assert {s["font_family"] for s in styles} == {"Genova"}

    def test_collect_corner_radii(self) -> None:
        radii = collect_corner_radii(build_fixture_tree())
        assert sorted(set(radii)) == [0.0, 8.0, 10.0, 200.0]

    def test_collect_image_fills(self) -> None:
        fills = collect_image_fills(build_fixture_tree())
        refs = {f["image_ref"] for f in fills}
        assert refs == {"aaaa1111", "bbbb2222"}
        assert fills[0]["node_id"] is not None


class TestDesignTokens:
    def test_colors_mapped(self) -> None:
        tokens = build_design_tokens(build_fixture_tree(), site_name="Keys")
        colors = tokens["colors"]
        assert colors["$darkcolor"] == "#0f2f2f"
        assert colors["$lightcolor"] == "#ffffff"
        # Rust has the largest accent area, gold is the vivid secondary.
        assert colors["$primarycolor"] == "#a24521"
        assert colors["$secondarycolor"] == "#fdbb2c"

    def test_fonts_and_weights(self) -> None:
        tokens = build_design_tokens(build_fixture_tree())
        assert tokens["fonts"]["assignments"]["headings"].startswith("Genova")
        assert tokens["typography"]["heading_weight"] == "700"
        assert tokens["typography"]["paragraph_weight"] == "400"
        assert tokens["fonts"]["register"][0]["name"] == "Genova"

    def test_border_radius(self) -> None:
        tokens = build_design_tokens(build_fixture_tree())
        assert tokens["spacing"]["site_border_radius"] == "8"
        assert tokens["spacing"]["button_border_radius"] == "200"

    def test_site_name_and_source(self) -> None:
        tokens = build_design_tokens(build_fixture_tree(), site_name="Keys", extracted_from="figma-url")
        assert tokens["site_name"] == "Keys"
        assert tokens["extracted_from"] == "figma-url"

    def test_missing_fonts_note(self) -> None:
        tree = {"id": "0:1", "name": "Empty", "type": "FRAME", "children": []}
        tokens = build_design_tokens(tree)
        assert any("No text nodes" in note for note in tokens["custom_css_needed"])


class TestThemePalette:
    def test_flat_palette_omits_unknowns(self) -> None:
        palette = build_theme_palette(build_fixture_tree())
        assert palette["dark"] == "#0f2f2f"
        assert palette["light"] == "#ffffff"
        assert palette["primary"] == "#a24521"
        assert "success" not in palette
        assert "warning" not in palette
