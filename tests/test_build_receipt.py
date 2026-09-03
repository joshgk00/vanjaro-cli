import json

import pytest

from vanjaro_cli.project.build_receipt import (
    BuildReceiptError,
    finalize_build_receipt,
    fingerprint_build_payload,
    is_sha256,
    load_build_receipt,
)


def unsigned_receipt():
    return {
        "schema_version": "agency-build-review-v1",
        "contract_version": "1.0",
        "project_id": "cafe-site",
        "target": {
            "profile": "preview",
            "expected_base_url": "http://preview.test",
            "expected_portal_id": 7,
        },
        "stage": "assets",
        "stage_contract_version": "1.0",
        "action": "execute",
        "attempt": 0,
        "requested": {
            "theme_mode": "preserve",
            "through": "verify",
            "page_mode": "isolated",
            "operator": "operator",
        },
        "manifest_fingerprint": "a" * 64,
        "dependencies": [],
        "inputs": {
            "data": {},
            "files": [{"path": "content/café.json", "sha256": "c" * 64}],
        },
        "input_fingerprint": "b" * 64,
        "approval": None,
        "observed_portal": None,
        "preview": {},
    }


def write_receipt(path, receipt):
    path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")


def test_canonical_fingerprint_is_stable_and_detached():
    original = unsigned_receipt()
    reordered = dict(reversed(list(original.items())))
    assert fingerprint_build_payload(original) == fingerprint_build_payload(reordered)
    finalized = finalize_build_receipt(original)
    assert "fingerprint" not in original
    assert finalized["fingerprint"] == fingerprint_build_payload(finalized)


def test_strict_utf8_round_trip(tmp_path):
    receipt = finalize_build_receipt(unsigned_receipt())
    path = tmp_path / "receipt.json"
    write_receipt(path, receipt)
    assert load_build_receipt(path) == receipt
    path.write_bytes(b'{"project_id":"\xff"}')
    with pytest.raises(BuildReceiptError, match="unable to read"):
        load_build_receipt(path)


def test_tamper_is_detected_without_echoing_value(tmp_path):
    receipt = finalize_build_receipt(unsigned_receipt())
    secret = "TOP-SECRET-RECEIPT-VALUE"
    receipt["requested"]["by"] = secret
    path = tmp_path / "receipt.json"
    write_receipt(path, receipt)
    with pytest.raises(BuildReceiptError) as caught:
        load_build_receipt(path)
    assert secret not in str(caught.value)


@pytest.mark.parametrize(
    "raw",
    [
        '{"schema_version":"x","schema_version":"y"}',
        '{"value":NaN}',
        '{"value":Infinity}',
        '{"value":-Infinity}',
    ],
)
def test_duplicate_and_nonfinite_json_are_rejected(tmp_path, raw):
    path = tmp_path / "receipt.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(BuildReceiptError):
        load_build_receipt(path)


@pytest.mark.parametrize("mutation", ["unknown", "missing"])
def test_exact_top_level_fields(tmp_path, mutation):
    receipt = finalize_build_receipt(unsigned_receipt())
    if mutation == "unknown":
        receipt["surprise"] = "redacted"
    else:
        del receipt["preview"]
    path = tmp_path / "receipt.json"
    write_receipt(path, receipt)
    with pytest.raises(BuildReceiptError, match="missing or unknown"):
        load_build_receipt(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("manifest_fingerprint", "ABC"),
        ("input_fingerprint", "f" * 63),
        ("action", "retry"),
        ("attempt", -1),
        ("attempt", True),
        ("project_id", ""),
        ("stage", "build stage"),
        ("target", "prod;delete"),
    ],
)
def test_bad_contract_values_are_rejected(field, value):
    payload = unsigned_receipt()
    payload[field] = value
    with pytest.raises(BuildReceiptError):
        finalize_build_receipt(payload)


@pytest.mark.parametrize("bad_path", ["/etc/passwd", "../secret", "a/../../secret", r"C:\\secret"])
def test_unsafe_input_file_paths_are_rejected(bad_path):
    payload = unsigned_receipt()
    payload["inputs"]["files"] = [{"path": bad_path, "sha256": "c" * 64}]
    with pytest.raises(BuildReceiptError):
        finalize_build_receipt(payload)


def test_nonfinite_python_value_and_bad_final_fingerprint_are_rejected(tmp_path):
    payload = unsigned_receipt()
    payload["preview"] = {"score": float("nan")}
    with pytest.raises(BuildReceiptError):
        finalize_build_receipt(payload)

    receipt = finalize_build_receipt(unsigned_receipt())
    receipt["fingerprint"] = "0" * 64
    path = tmp_path / "receipt.json"
    write_receipt(path, receipt)
    with pytest.raises(BuildReceiptError, match="does not match"):
        load_build_receipt(path)


def test_is_sha256_is_strict():
    assert is_sha256("0" * 64)
    assert not is_sha256("A" * 64)
    assert not is_sha256(True)


@pytest.mark.parametrize("mutation", ["unknown", "missing", "bad_version_type"])
def test_observed_portal_has_an_exact_typed_contract(mutation):
    payload = unsigned_receipt()
    payload["observed_portal"] = {
        "profile": "preview",
        "base_url": "http://preview.test",
        "portal_id": 7,
        "health_status": "ok",
        "dnn_version": "9.13.7",
        "vanjaro_version": "1.3.0",
        "user_name": "host",
    }
    if mutation == "unknown":
        payload["observed_portal"]["extra"] = "not-in-contract"
    elif mutation == "missing":
        del payload["observed_portal"]["dnn_version"]
    else:
        payload["observed_portal"]["vanjaro_version"] = 1

    with pytest.raises(BuildReceiptError):
        finalize_build_receipt(payload)
