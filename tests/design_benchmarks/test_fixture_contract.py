"""Contract tests for the committed Design Translation v2 benchmark corpus."""

from __future__ import annotations

import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup


CORPUS = Path(__file__).parents[1] / "fixtures" / "design-benchmarks"
MANIFEST = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))


def _load(relative_path: str) -> dict:
    return json.loads((CORPUS / relative_path).read_text(encoding="utf-8"))


def _figma_nodes(node: dict):
    yield node
    for child in node.get("children", []):
        yield from _figma_nodes(child)


def test_manifest_has_required_source_diversity_and_canonical_viewports():
    assert MANIFEST["schema_version"] == "1.0"
    assert MANIFEST["corpus"]["synthetic_only"] is True
    assert MANIFEST["corpus"]["regression_tolerance"] == 0.02
    assert MANIFEST["viewports"] == {
        "desktop": {"width": 1440, "height": 900},
        "tablet": {"width": 768, "height": 1024},
        "mobile": {"width": 390, "height": 844},
    }

    cases = MANIFEST["cases"]
    assert len(cases) >= 5
    assert len({case["id"] for case in cases}) == len(cases)
    html_profiles = {
        case["adapter_profile"] for case in cases if case["source_kind"] == "live_html"
    }
    assert len(html_profiles) >= 3
    assert sum(case["source_kind"] == "figma" for case in cases) >= 2


def test_manifest_paths_are_offline_relative_and_visual_references_exist():
    for case in MANIFEST["cases"]:
        paths = [case["source"]["path"], case["annotations"]]
        paths.extend(reference["path"] for reference in case["references"])
        for relative in paths:
            path = Path(relative)
            assert not path.is_absolute()
            assert ".." not in path.parts
            assert (CORPUS / path).is_file(), f"missing {case['id']} artifact: {relative}"

        references = {reference["breakpoint"]: reference for reference in case["references"]}
        assert set(references) == {"desktop", "mobile"}
        for breakpoint, reference in references.items():
            root = ET.parse(CORPUS / reference["path"]).getroot()
            assert int(root.attrib["width"]) == MANIFEST["viewports"][breakpoint]["width"]
            assert int(root.attrib["height"]) == MANIFEST["viewports"][breakpoint]["height"]
            assert reference["synthetic"] is True


def test_annotations_are_metrics_ready_and_meet_corpus_size_gates():
    section_total = 0
    repeat_item_total = 0

    for case in MANIFEST["cases"]:
        annotation = _load(case["annotations"])
        assert annotation["schema_version"] == "1.0"
        assert annotation["case_id"] == case["id"]
        assert annotation["source_kind"] == case["source_kind"]
        assert set(annotation["page"]["breakpoints"]) == {"desktop", "tablet", "mobile"}

        sections = annotation["expected"]["sections"]
        section_total += len(sections)
        assert [section["order"] for section in sections] == list(range(1, len(sections) + 1))
        assert len({section["id"] for section in sections}) == len(sections)

        document_element_ids: set[str] = set()
        document_group_ids: set[str] = set()
        for section in sections:
            assert section["semantic_role"]
            assert section["boundary"]["value"]
            assert section["acceptable_templates"]
            assert len(section["acceptable_templates"]) == len(set(section["acceptable_templates"]))
            assert section["responsive"], f"{section['id']} has no responsive expectation"
            assert any(item["breakpoint"] == "mobile" for item in section["responsive"])

            element_ids = {element["id"] for element in section["content"]}
            group_ids = {group["id"] for group in section["groups"]}
            assert len(element_ids) == len(section["content"])
            assert len(group_ids) == len(section["groups"])
            assert not document_element_ids.intersection(element_ids)
            assert not document_group_ids.intersection(group_ids)
            document_element_ids.update(element_ids)
            document_group_ids.update(group_ids)

            for element in section["content"]:
                assert element["kind"] and element["role"] and element["order"] >= 1
                assert element["group_id"] is None or element["group_id"] in group_ids

            for group in section["groups"]:
                repeat_item_total += len(group["items"])
                for item in group["items"]:
                    assert item["fields"]
                    assert set(item["fields"].values()).issubset(element_ids)

            for asset in section["assets"]:
                assert asset["element_id"] in element_ids
                assert asset["source_ref"]

    assert section_total >= 25
    assert repeat_item_total >= 40


def test_annotation_boundaries_and_expected_values_exist_in_sources():
    for case in MANIFEST["cases"]:
        annotation = _load(case["annotations"])
        source_path = CORPUS / case["source"]["path"]

        if case["source_kind"] == "live_html":
            source_text = source_path.read_text(encoding="utf-8")
            soup = BeautifulSoup(source_text, "html.parser")
            for section in annotation["expected"]["sections"]:
                assert section["boundary"]["kind"] == "css_selector"
                boundary = soup.select_one(section["boundary"]["value"])
                assert boundary is not None, section["id"]
                boundary_text = str(boundary)
                for element in section["content"]:
                    if element["value"] is not None:
                        assert element["value"] in boundary_text, (
                            f"{section['id']} missing expected value {element['value']!r}"
                        )
        else:
            source = json.loads(source_path.read_text(encoding="utf-8"))
            nodes = {node["id"]: node for node in _figma_nodes(source["document"])}
            source_text = json.dumps(source, sort_keys=True)
            for section in annotation["expected"]["sections"]:
                assert section["boundary"]["kind"] == "figma_node_id"
                assert section["boundary"]["value"] in nodes
                for element in section["content"]:
                    assert element["value"] is None or element["value"] in source_text


def test_corpus_contains_a_figma_design_without_auto_layout():
    freeform = next(
        case for case in MANIFEST["cases"]
        if case["adapter_profile"] == "figma_freeform_no_auto_layout"
    )
    source = _load(freeform["source"]["path"])
    layout_modes = {
        node.get("layoutMode") for node in _figma_nodes(source["document"])
        if node.get("layoutMode") is not None
    }
    assert not layout_modes.intersection({"HORIZONTAL", "VERTICAL"})


def test_fixture_sources_are_synthetic_and_secret_free():
    secret_pattern = re.compile(
        r"(?i)(api[_-]?key|client[_-]?secret|password|authorization\s*:|bearer\s+[a-z0-9])"
    )
    for case in MANIFEST["cases"]:
        assert case["source"]["synthetic"] is True
        assert case["legal"] == {
            "classification": "synthetic",
            "contains_secrets": False,
            "contains_personal_data": False,
        }
        source_text = (CORPUS / case["source"]["path"]).read_text(encoding="utf-8")
        assert not secret_pattern.search(source_text)


def test_legacy_baseline_is_explicit_about_metric_availability():
    report = _load("baseline-score-report.json")
    assert report["schema_version"] == "1.0"
    assert report["measurement_policy"]["regression_tolerance"] == 0.02
    assert report["aggregate"]["group_field_association_accuracy"]["status"] == "not_measurable"
    statuses = {case["case_id"]: case["status"] for case in report["cases"]}
    assert set(statuses) == {case["id"] for case in MANIFEST["cases"]}
    assert statuses["figma-auto-layout-saas"] == "not_supported"
    assert statuses["figma-freeform-nonprofit"] == "not_supported"
