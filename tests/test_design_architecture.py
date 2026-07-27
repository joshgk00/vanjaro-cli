"""Enforce source-adapter and shared-reasoning package boundaries."""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESIGN_ROOT = PROJECT_ROOT / "vanjaro_cli" / "design"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_shared_reasoning_does_not_import_concrete_source_adapters() -> None:
    shared_modules = (
        "matcher.py",
        "planner.py",
        "style_translation.py",
        "template_catalog.py",
        "composition.py",
        "semantics.py",
    )
    forbidden = {
        "vanjaro_cli.design.figma_adapter",
        "vanjaro_cli.design.html_adapter",
        "vanjaro_cli.design.sources.figma",
        "vanjaro_cli.design.sources.html",
        "vanjaro_cli.design.sources.image",
    }

    for module in shared_modules:
        assert _imports(DESIGN_ROOT / module).isdisjoint(forbidden), module


def test_source_adapters_do_not_import_matching_planning_or_portal_layers() -> None:
    forbidden_prefixes = (
        "vanjaro_cli.client",
        "vanjaro_cli.commands",
        "vanjaro_cli.design.matcher",
        "vanjaro_cli.design.planner",
        "vanjaro_cli.design.vanjaro_benchmark_backend",
    )
    concrete_source_modules = list((DESIGN_ROOT / "sources").glob("*.py")) + [
        DESIGN_ROOT / "figma_adapter.py",
        DESIGN_ROOT / "figma_sections.py",
        DESIGN_ROOT / "figma_tree.py",
        DESIGN_ROOT / "html_adapter.py",
        DESIGN_ROOT / "html_boundaries.py",
        DESIGN_ROOT / "html_ownership.py",
        DESIGN_ROOT / "html_primitives.py",
        DESIGN_ROOT / "image_adapter.py",
        DESIGN_ROOT / "image_conversion_support.py",
        DESIGN_ROOT / "image_evidence.py",
    ]
    for path in concrete_source_modules:
        offending = {
            imported
            for imported in _imports(path)
            if imported.startswith(forbidden_prefixes)
        }
        assert not offending, f"{path.name}: {sorted(offending)}"


def test_project_domain_does_not_import_cli_config_or_portal_layers() -> None:
    forbidden_prefixes = (
        "vanjaro_cli.client",
        "vanjaro_cli.commands",
        "vanjaro_cli.config",
        "vanjaro_cli.design.figma_adapter",
        "vanjaro_cli.design.html_adapter",
        "vanjaro_cli.design.matcher",
        "vanjaro_cli.design.planner",
    )
    for path in (PROJECT_ROOT / "vanjaro_cli" / "project").glob("*.py"):
        offending = {
            imported
            for imported in _imports(path)
            if imported.startswith(forbidden_prefixes)
        }
        assert not offending, f"{path.name}: {sorted(offending)}"


def test_evidence_contracts_are_separate_from_cli_project_and_portal_layers() -> None:
    evidence_root = PROJECT_ROOT / "vanjaro_cli" / "evidence"
    pure_modules = ("models.py", "normalization.py", "prompts.py")
    forbidden_prefixes = (
        "requests",
        "vanjaro_cli.client",
        "vanjaro_cli.commands",
        "vanjaro_cli.orchestration",
        "vanjaro_cli.portal",
        "vanjaro_cli.project",
        "vanjaro_cli.design.matcher",
        "vanjaro_cli.design.planner",
    )
    for module in pure_modules:
        offending = {
            imported
            for imported in _imports(evidence_root / module)
            if imported.startswith(forbidden_prefixes)
        }
        assert not offending, f"{module}: {sorted(offending)}"


def test_openai_evidence_provider_does_not_import_cli_project_or_portal() -> None:
    imports = _imports(
        PROJECT_ROOT / "vanjaro_cli" / "evidence" / "openai_provider.py"
    )
    forbidden_prefixes = (
        "vanjaro_cli.client",
        "vanjaro_cli.commands",
        "vanjaro_cli.orchestration",
        "vanjaro_cli.portal",
        "vanjaro_cli.project",
        "vanjaro_cli.design.matcher",
        "vanjaro_cli.design.planner",
    )
    offending = {
        imported for imported in imports if imported.startswith(forbidden_prefixes)
    }
    assert not offending, sorted(offending)


def test_agency_library_governance_is_independent_of_cli_portal_and_projects() -> None:
    agency_root = PROJECT_ROOT / "vanjaro_cli" / "agency_library"
    forbidden_prefixes = (
        "requests",
        "vanjaro_cli.client",
        "vanjaro_cli.commands",
        "vanjaro_cli.config",
        "vanjaro_cli.orchestration",
        "vanjaro_cli.portal",
        "vanjaro_cli.project",
        "vanjaro_cli.design.matcher",
        "vanjaro_cli.design.planner",
    )
    for module in ("models.py", "registry.py", "compatibility.py"):
        offending = {
            imported
            for imported in _imports(agency_root / module)
            if imported.startswith(forbidden_prefixes)
        }
        assert not offending, f"{module}: {sorted(offending)}"


def test_fidelity_scoring_is_pure() -> None:
    """The authoritative score must not depend on I/O or a model provider.

    VF-1 requires the primary score be reproducible from measured evidence
    alone. Reaching the network, the filesystem, or an evidence provider would
    make a rerun able to return a different number for unchanged input.
    """

    forbidden = {
        "requests",
        "pathlib",
        "os",
        "subprocess",
        "vanjaro_cli.client",
        "vanjaro_cli.config",
        "vanjaro_cli.evidence",
        "vanjaro_cli.evidence.openai_provider",
        "vanjaro_cli.portal",
    }

    for module in (
        "fidelity.py",
        "fidelity_layout.py",
        "fidelity_color.py",
        "fidelity_type.py",
    ):
        imported = _imports(DESIGN_ROOT / module)
        assert imported.isdisjoint(forbidden), (module, sorted(imported & forbidden))
