"""Durability and fail-closed contracts for build transaction journals."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from vanjaro_cli.project.build_transaction import (
    BuildTransactionError,
    begin_build_transaction,
    complete_build_transaction,
    fail_build_transaction,
    load_build_transaction,
    mark_build_transaction_attempting,
    require_build_transaction_binding,
)


NOW = datetime(2026, 8, 31, tzinfo=timezone.utc)


def _receipt() -> dict:
    return {
        "fingerprint": "a" * 64,
        "project_id": "agency-site",
        "stage": "pages",
        "attempt": 2,
        "preview": {
            "portal_actions": [
                {
                    "key": "home",
                    "action": "update",
                    "operations": [
                        {
                            "kind": "portal_request",
                            "method": "POST",
                            "endpoint": "/pages/update",
                        }
                    ],
                },
                {
                    "key": "about",
                    "action": "reuse",
                    "operations": [
                        {
                            "kind": "portal_readback",
                            "method": "GET",
                            "endpoint": "/pages/get",
                        }
                    ],
                },
            ],
            "local_writes": ["build/page-manifest.json"],
        },
    }


def test_transaction_persists_intent_attempt_and_completion(tmp_path) -> None:
    receipt = _receipt()
    journal = begin_build_transaction(
        tmp_path, receipt=receipt, operator="Agency Operator", now=NOW
    )
    assert [item["status"] for item in journal["actions"]] == [
        "pending",
        "preexisting",
    ]

    mark_build_transaction_attempting(tmp_path, journal, now=NOW)
    assert [item["status"] for item in journal["actions"]] == [
        "attempting",
        "preexisting",
    ]

    complete_build_transaction(
        tmp_path,
        journal,
        execution={"stage": "pages", "status": "completed"},
        now=NOW,
    )
    loaded = load_build_transaction(tmp_path, receipt["fingerprint"])
    assert loaded is not None
    assert loaded["status"] == "completed"
    assert [item["status"] for item in loaded["actions"]] == [
        "committed",
        "preexisting",
    ]


def test_failure_is_redacted_and_blocks_mismatched_reentry(tmp_path) -> None:
    receipt = _receipt()
    journal = begin_build_transaction(
        tmp_path, receipt=receipt, operator="Agency Operator", now=NOW
    )
    mark_build_transaction_attempting(tmp_path, journal, now=NOW)
    fail_build_transaction(
        tmp_path,
        journal,
        error=RuntimeError("https://user:secret@example.test/path?token=abc"),
        now=NOW,
    )

    loaded = load_build_transaction(tmp_path, receipt["fingerprint"])
    assert loaded is not None
    assert loaded["status"] == "recovery_required"
    assert "secret" not in loaded["error"]["message"]
    assert "token=abc" not in loaded["error"]["message"]
    with pytest.raises(BuildTransactionError, match="different receipt"):
        require_build_transaction_binding(
            loaded, receipt=receipt, operator="Different Operator"
        )


def test_existing_transaction_cannot_be_silently_reinitialized(tmp_path) -> None:
    receipt = _receipt()
    begin_build_transaction(
        tmp_path, receipt=receipt, operator="Agency Operator", now=NOW
    )

    with pytest.raises(BuildTransactionError, match="already exists"):
        begin_build_transaction(
            tmp_path, receipt=receipt, operator="Agency Operator", now=NOW
        )
