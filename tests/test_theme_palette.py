"""Tests for vanjaro_cli.utils.theme_palette."""

from __future__ import annotations

import json

import pytest

from vanjaro_cli.utils.theme_palette import (
    PaletteError,
    load_palette,
    nearest_palette_slot,
)

SAMPLE_PALETTE = {
    "primary": "#00aa55",
    "secondary": "#4A5057",
    "info": "#17a2b8",
    "light": "#f8f9fa",
    "dark": "#343a40",
}


def test_load_palette_parses_hex_into_rgb(tmp_path, write_json):
    palette = load_palette(write_json(tmp_path / "palette.json", SAMPLE_PALETTE))
    assert palette["primary"] == (0, 170, 85)
    assert palette["dark"] == (52, 58, 64)


def test_load_palette_skips_unknown_slots_and_bad_colors(tmp_path, write_json):
    palette = load_palette(
        write_json(
            tmp_path / "palette.json",
            {"primary": "#00aa55", "bogus": "#ffffff", "secondary": "transparent"},
        )
    )
    assert "primary" in palette
    assert "bogus" not in palette
    assert "secondary" not in palette


def test_load_palette_accepts_rgb_values(tmp_path, write_json):
    palette = load_palette(write_json(tmp_path / "palette.json", {"primary": "rgb(38, 35, 35)"}))
    assert palette["primary"] == (38, 35, 35)


def test_load_palette_missing_file_raises(tmp_path):
    with pytest.raises(PaletteError, match="Cannot read palette file"):
        load_palette(tmp_path / "nope.json")


def test_load_palette_non_object_raises(tmp_path):
    path = tmp_path / "palette.json"
    path.write_text(json.dumps(["#fff"]), encoding="utf-8")
    with pytest.raises(PaletteError, match="must be a JSON object"):
        load_palette(str(path))


def _rgb_palette() -> dict[str, tuple[int, int, int]]:
    return {slot: tuple(int(v.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
            for slot, v in SAMPLE_PALETTE.items()}


def test_nearest_slot_exact_match():
    assert nearest_palette_slot("#00aa55", _rgb_palette()) == "primary"


def test_nearest_slot_near_match_within_threshold():
    # One channel off by ~8 — well inside the default 40 threshold.
    assert nearest_palette_slot("#08aa5d", _rgb_palette()) == "primary"


def test_nearest_slot_distinct_color_falls_through():
    # A saturated royal blue is nowhere near any sample slot; the default
    # max_distance (40) must keep distinct brand colors from false-matching.
    assert nearest_palette_slot("#1f4fff", _rgb_palette()) is None


def test_nearest_slot_accepts_rgb_input():
    assert nearest_palette_slot("rgb(0, 170, 85)", _rgb_palette()) == "primary"


def test_nearest_slot_unparseable_color_is_none():
    assert nearest_palette_slot("linear-gradient(...)", _rgb_palette()) is None


def test_nearest_slot_empty_palette_is_none():
    assert nearest_palette_slot("#00aa55", {}) is None
