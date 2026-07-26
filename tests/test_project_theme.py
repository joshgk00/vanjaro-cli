"""Deterministic, non-mutating project theme-plan regression tests."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from vanjaro_cli.cli import cli
from vanjaro_cli.design.models import DesignDocument
from vanjaro_cli.design.serialization import write_design_document
from vanjaro_cli.design.theme_plan import ProjectThemePlan, build_project_theme_plan
from vanjaro_cli.orchestration import project_theme
from vanjaro_cli.project.models import ProjectStage
from vanjaro_cli.project.stage_engine import StageContext
from tests.test_design_models import make_design_document_data


def _document() -> DesignDocument:
    data = make_design_document_data()
    data["tokens"] = {
        "colors": {
            "color-orange": {"value": "#fe6124"},
            "color-cream": {"value": "#fffcf6"},
            "color-black": {"value": "#000000"},
            "color-teal": {"value": "#08c6b4"},
            "color-pink": {"value": "#f0709d"},
            "color-gold": {"value": "#fdbb2c"},
            "color-muted": {"value": "#d4d4d4"},
        },
        "typography": [
            {"role": "body", "font_family": "Agency Sans", "font_size": "16px"},
            {"role": "body", "font_family": "Agency Sans", "font_size": "18px"},
            {"role": "heading", "font_family": "Inter", "font_size": "48px"},
            {"role": "display", "font_family": "Inter", "font_size": "72px"},
        ],
        "spacing": {"section-gap": {"value": "64px"}},
    }
    return DesignDocument.model_validate(data)


def _settings() -> dict:
    controls = []
    variables = {
        "$primarycolor": "Primary",
        "$secondarycolor": "Secondary",
        "$tertiary": "Tertiary",
        "$quaternary": "Quaternary",
        "$successcolor": "Success",
        "$infocolor": "Info",
        "$warningcolor": "Warning",
        "$dangercolor": "Danger",
        "$lightcolor": "Light",
        "$darkcolor": "Dark",
    }
    for index, (variable, title) in enumerate(variables.items()):
        controls.append(
            {
                "guid": f"color-{index}",
                "lessVariable": variable,
                "category": "Site",
                "title": title,
                "type": "Color Picker",
                "currentValue": "#111111",
            }
        )
    controls.extend(
        [
            {
                "guid": "site-font",
                "lessVariable": "$siteFontFamily",
                "category": "Site",
                "title": "Font Family",
                "type": "Fonts",
                "currentValue": "Arial, sans-serif",
            },
            {
                "guid": "heading-font-1",
                "lessVariable": "$hsoneFontFamily",
                "category": "Styles: Heading",
                "title": "Font Family",
                "type": "Fonts",
                "currentValue": "Arial, sans-serif",
            },
            {
                "guid": "text-font-1",
                "lessVariable": "$psoneFontFamily",
                "category": "Styles: Text",
                "title": "Font Family",
                "type": "Fonts",
                "currentValue": "Arial, sans-serif",
            },
        ]
    )
    return {
        "themeName": "Basic",
        "controls": controls,
        "availableFonts": [
            {"name": "Arial", "value": "Arial, sans-serif"},
            {"name": "Inter", "value": "Inter, sans-serif"},
        ],
    }


def test_theme_plan_is_deterministic_and_maps_existing_palette_controls() -> None:
    document = _document()
    settings = _settings()

    first = build_project_theme_plan(document, settings)
    reversed_data = document.model_dump(mode="json")
    reversed_data["tokens"]["colors"] = dict(
        reversed(list(reversed_data["tokens"]["colors"].items()))
    )
    reversed_document = DesignDocument.model_validate(reversed_data)
    reversed_settings = deepcopy(settings)
    reversed_settings["controls"].reverse()
    second = build_project_theme_plan(reversed_document, reversed_settings)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert set(first.proposed_palette) == {
        "primary", "secondary", "tertiary", "quaternary", "light", "dark"
    }
    assert first.proposed_palette["light"] == "#fffcf6"
    assert first.proposed_palette["dark"] == "#000000"
    assert first.current_palette["primary"] == "#111111"
    palette_controls = {
        item.less_variable: item.planned_value
        for item in first.controls
        if item.less_variable in {
            "$primarycolor", "$secondarycolor", "$tertiary",
            "$quaternary", "$lightcolor", "$darkcolor",
        }
    }
    assert palette_controls == {
        "$primarycolor": first.proposed_palette["primary"],
        "$secondarycolor": first.proposed_palette["secondary"],
        "$tertiary": first.proposed_palette["tertiary"],
        "$quaternary": first.proposed_palette["quaternary"],
        "$lightcolor": "#fffcf6",
        "$darkcolor": "#000000",
    }
    heuristic = [warning for warning in first.warnings if warning.code == "HEURISTIC_PALETTE_MAPPING"]
    assert len(heuristic) == 6
    assert all("requires review" in warning.message for warning in heuristic)


def test_theme_plan_never_invents_or_substitutes_an_unavailable_font() -> None:
    plan = build_project_theme_plan(_document(), _settings())

    planned_values = {item.planned_value for item in plan.controls}
    assert "Agency Sans" not in planned_values
    assert "Agency Sans, sans-serif" not in planned_values
    assert "Inter, sans-serif" in planned_values
    unresolved = [warning for warning in plan.warnings if warning.code == "UNRESOLVED_FONT_TOKEN"]
    assert len(unresolved) == 1
    assert "Agency Sans" in unresolved[0].message
    body = [item for item in plan.fonts if item.role == "body"]
    assert body[0].status == "unresolved"
    assert body[0].available_value is None


def test_theme_plan_emits_explicit_unresolved_token_warnings() -> None:
    data = _document().model_dump(mode="json")
    data["tokens"]["colors"]["gradient"] = {"value": "linear-gradient(red, blue)"}
    document = DesignDocument.model_validate(data)

    plan = build_project_theme_plan(document, _settings())

    warning_paths = {
        path
        for warning in plan.warnings
        for path in warning.token_paths
    }
    assert "tokens.colors.gradient" in warning_paths
    assert "tokens.spacing.section-gap" in warning_paths


def test_semantic_color_token_is_authoritative_but_generic_tokens_are_not() -> None:
    data = _document().model_dump(mode="json")
    data["tokens"]["colors"] = {
        "primary": {"value": "#123456"},
        "danger": {"value": "#cc0011"},
        "color-01": {"value": "#ff3300"},
        "white": {"value": "#ffffff"},
        "black": {"value": "#000000"},
    }
    plan = build_project_theme_plan(DesignDocument.model_validate(data), _settings())

    assert plan.proposed_palette["primary"] == "#123456"
    assert plan.proposed_palette["danger"] == "#cc0011"
    primary_warnings = [
        warning
        for warning in plan.warnings
        if "tokens.colors.primary" in warning.token_paths
    ]
    assert all(warning.code != "HEURISTIC_PALETTE_MAPPING" for warning in primary_warnings)
    assert any(
        warning.code == "HEURISTIC_PALETTE_MAPPING"
        and "tokens.colors.color-01" in warning.token_paths
        for warning in plan.warnings
    )
    assert not any(
        warning.code == "HEURISTIC_PALETTE_MAPPING"
        and "tokens.colors.danger" in warning.token_paths
        for warning in plan.warnings
    )


def test_status_palette_slots_are_never_filled_heuristically() -> None:
    plan = build_project_theme_plan(_document(), _settings())

    assert not ({"success", "info", "warning", "danger"} & set(plan.proposed_palette))
    assert {"success", "info", "warning", "danger"} <= set(plan.current_palette)


def test_ambiguous_live_control_is_warned_and_never_targeted() -> None:
    settings = _settings()
    duplicate = deepcopy(settings["controls"][0])
    duplicate["guid"] = "duplicate-primary"
    settings["controls"].append(duplicate)

    plan = build_project_theme_plan(_document(), settings)

    assert not any(item.less_variable == "$primarycolor" for item in plan.controls)
    assert any(
        warning.code == "THEME_CONTROL_AMBIGUOUS"
        and "$primarycolor" in warning.message
        for warning in plan.warnings
    )


def test_theme_plan_contract_rejects_unknown_fields() -> None:
    payload = build_project_theme_plan(_document(), _settings()).model_dump(mode="json")
    payload["unexpected"] = True

    with pytest.raises(ValidationError, match="unexpected"):
        ProjectThemePlan.model_validate(payload)


class _ReadOnlyClient:
    def __init__(self, settings: dict) -> None:
        self.settings = settings
        self.get_calls: list[str] = []
        self.write_calls: list[tuple] = []

    def get(self, path: str):
        self.get_calls.append(path)
        return SimpleNamespace(json=lambda: deepcopy(self.settings))

    def post(self, *args, **kwargs):
        self.write_calls.append((args, kwargs))
        raise AssertionError("theme preview must never POST")

    put = post
    patch = post
    delete = post


def _verified():
    return SimpleNamespace(
        portal_id=2,
        as_dict=lambda: {
            "profile": "test",
            "base_url": "http://vanjarocli.local/test",
            "portal_id": 2,
        },
    )


def test_theme_preview_performs_zero_http_or_local_writes(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "plans").mkdir()
    write_design_document(tmp_path / "plans/resolved-design-document.json", _document())
    client = _ReadOnlyClient(_settings())
    monkeypatch.setattr(
        project_theme,
        "verify_project_portal",
        lambda manifest: (client, _verified()),
    )
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    preview = project_theme.preview_project_theme_stage(tmp_path, object())

    after = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert before == after
    assert client.get_calls == [project_theme.GET_THEME_SETTINGS]
    assert client.write_calls == []
    assert preview["mutated"] is False
    assert preview["http_writes"] == 0
    assert preview["local_writes"] == 0


def test_theme_plan_stage_writes_only_review_artifacts(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "plans").mkdir()
    write_design_document(tmp_path / "plans/resolved-design-document.json", _document())
    client = _ReadOnlyClient(_settings())
    monkeypatch.setattr(
        project_theme,
        "verify_project_portal",
        lambda manifest: (client, _verified()),
    )
    context = StageContext(
        root=tmp_path,
        stage=ProjectStage.THEME,
        manifest=object(),
        input_fingerprint="0" * 64,
        attempt=1,
    )

    result = project_theme.plan_project_theme_stage(context)

    assert result.artifacts == (
        "build/theme-plan.json",
        "build/theme-palette.json",
        "build/theme-result.json",
    )
    assert client.write_calls == []
    report = json.loads((tmp_path / "build/theme-result.json").read_text())
    assert report["mutated"] is False
    assert report["http_writes"] == 0
    assert json.loads((tmp_path / "build/theme-palette.json").read_text())


def test_project_build_help_exposes_non_mutating_theme_plan_mode(runner) -> None:
    result = runner.invoke(cli, ["project", "build", "--help"])

    assert result.exit_code == 0
    assert "preserve|plan" in result.output


def test_theme_plan_mode_cannot_flow_into_portal_build_stages(runner, tmp_path: Path) -> None:
    result = runner.invoke(
        cli,
        [
            "project", "build", str(tmp_path), "--theme-mode", "plan",
            "--through", "assets", "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "artifact-only" in payload["message"]
