from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from pydantic import BaseModel

from vanjaro_cli.release.models import (
    ControlEvidenceReceipt,
    LiveAttestationReceipt,
    LiveEvidenceReceipt,
    ProjectEffortEvidence,
    ProjectQualityEvidence,
    ProjectReleaseReceipt,
    ReleaseContract,
    TestEvidenceReceipt as ReleaseTestEvidenceReceipt,
    TestPolicy as ReleaseTestPolicy,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" / "release"
EXAMPLE_DIR = ROOT / "release" / "examples"
EXPECTED = {
    "release-contract": ReleaseContract,
    "test-policy": ReleaseTestPolicy,
    "test-evidence-receipt": ReleaseTestEvidenceReceipt,
    "control-evidence-receipt": ControlEvidenceReceipt,
    "project-quality-evidence": ProjectQualityEvidence,
    "project-effort-evidence": ProjectEffortEvidence,
    "project-release-receipt": ProjectReleaseReceipt,
    "live-evidence-receipt": LiveEvidenceReceipt,
    "live-attestation-receipt": LiveAttestationReceipt,
}


def _load_generator():
    path = ROOT / "tools" / "generate_release_schemas.py"
    spec = importlib.util.spec_from_file_location("generate_release_schemas", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_schemas_match_models(tmp_path: Path, capsys) -> None:
    generator = _load_generator()
    declared = {
        filename.removesuffix(".schema.json"): model
        for filename, model in generator.SCHEMA_MODELS
    }
    assert declared == EXPECTED
    assert {path.name for path in SCHEMA_DIR.iterdir()} == {
        f"{name}.schema.json" for name in EXPECTED
    }

    rendered = generator.rendered_schemas()
    for name, model in EXPECTED.items():
        path = SCHEMA_DIR / f"{name}.schema.json"
        raw = path.read_bytes()
        assert raw == rendered[path.name].encode("utf-8")
        schema = json.loads(raw)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"] == path.name
        assert schema["title"] == model.__name__

    checked = subprocess.run(
        [sys.executable, "tools/generate_release_schemas.py", "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr

    drift_dir = tmp_path / "schemas"
    generator.SCHEMA_DIRECTORY = drift_dir
    assert generator.generate(check=True) == 1
    assert not drift_dir.exists(), "--check must not create or write paths"
    assert "missing schema" in capsys.readouterr().err

    assert generator.generate(check=False) == 0
    drift_path = drift_dir / "release-contract.schema.json"
    drift_path.write_text("{}\n", encoding="utf-8")
    before = drift_path.read_bytes()
    assert generator.generate(check=True) == 1
    assert drift_path.read_bytes() == before, "--check must not repair drift"
    assert "release schema drift detected" in capsys.readouterr().err


def test_release_examples_validate_against_models() -> None:
    assert {path.name for path in EXAMPLE_DIR.iterdir()} == {
        "README.md",
        *(f"{name}.json" for name in EXPECTED),
    }
    for name, model in EXPECTED.items():
        assert issubclass(model, BaseModel)
        path = EXAMPLE_DIR / f"{name}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        validated = model.model_validate(payload)
        assert validated.model_dump(mode="json") == payload
