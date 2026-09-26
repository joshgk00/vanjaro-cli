"""Shared identifiers for persisted publish, launch, and release contracts."""

PUBLISH_REVIEW_SCHEMA = "agency-publish-review-v1"
PUBLISH_RESULT_SCHEMA = "agency-publish-result-v1"
PUBLISH_JOURNAL_SCHEMA = "agency-publish-journal-v1"
PUBLISH_LOCK_SCHEMA = "agency-publish-lock-v1"

LAUNCH_PLAN_SCHEMA = "agency-launch-plan-v1"
LAUNCH_REVIEW_SCHEMA = "agency-launch-review-v2"
LAUNCH_RESULT_SCHEMA = "agency-launch-result-v1"
LAUNCH_TRANSACTION_SCHEMA = "agency-launch-transaction-v1"

COMPATIBILITY_POLICY_SCHEMA = "agency-compatibility-policy-v1"
COMPATIBILITY_REPORT_SCHEMA = "compatibility-report-v1"
CONTROL_EVIDENCE_SCHEMA = "reliability-control-evidence-v1"
DIAGNOSTIC_SCHEMA = "diagnostic-v1"
LIVE_ATTESTATION_SCHEMA = "agency-live-attestation-v1"
LIVE_EVIDENCE_SCHEMA = "agency-live-evidence-v1"
PERFORMANCE_EVIDENCE_SCHEMA = "performance-evidence-v1"
PERFORMANCE_REPORT_SCHEMA = "performance-report-v1"
PROJECT_EFFORT_EVIDENCE_SCHEMA = "project-effort-evidence-v1"
PROJECT_MIGRATION_REPORT_SCHEMA = "project-migration-report-v1"
PROJECT_MIGRATION_TRANSACTION_SCHEMA = "project-migration-transaction-v1"
PROJECT_QUALITY_EVIDENCE_SCHEMA = "project-quality-evidence-v1"
PROJECT_RELEASE_EVIDENCE_SCHEMA = "project-release-evidence-v1"
RELEASE_AUDIT_SCHEMA = "agency-release-audit-v1"
RELEASE_CONTRACT_SCHEMA = "1.0"
SECRET_SCAN_SCHEMA = "secret-scan-v1"
TEST_EVIDENCE_SCHEMA = "test-evidence-v1"
TEST_POLICY_SCHEMA = "agency-test-policy-v1"

PERSISTED_ACTION_CONTRACTS = {
    "launch_plan": LAUNCH_PLAN_SCHEMA,
    "launch_result": LAUNCH_RESULT_SCHEMA,
    "launch_review": LAUNCH_REVIEW_SCHEMA,
    "launch_transaction": LAUNCH_TRANSACTION_SCHEMA,
    "publish_journal": PUBLISH_JOURNAL_SCHEMA,
    "publish_lock": PUBLISH_LOCK_SCHEMA,
    "publish_result": PUBLISH_RESULT_SCHEMA,
    "publish_review": PUBLISH_REVIEW_SCHEMA,
}

PERSISTED_RELEASE_CONTRACTS = {
    "compatibility_policy": COMPATIBILITY_POLICY_SCHEMA,
    "compatibility_report": COMPATIBILITY_REPORT_SCHEMA,
    "control_evidence": CONTROL_EVIDENCE_SCHEMA,
    "diagnostic": DIAGNOSTIC_SCHEMA,
    "live_attestation": LIVE_ATTESTATION_SCHEMA,
    "live_evidence": LIVE_EVIDENCE_SCHEMA,
    "performance_evidence": PERFORMANCE_EVIDENCE_SCHEMA,
    "performance_report": PERFORMANCE_REPORT_SCHEMA,
    "project_effort_evidence": PROJECT_EFFORT_EVIDENCE_SCHEMA,
    "project_migration_report": PROJECT_MIGRATION_REPORT_SCHEMA,
    "project_migration_transaction": PROJECT_MIGRATION_TRANSACTION_SCHEMA,
    "project_quality_evidence": PROJECT_QUALITY_EVIDENCE_SCHEMA,
    "project_release_evidence": PROJECT_RELEASE_EVIDENCE_SCHEMA,
    "release_audit": RELEASE_AUDIT_SCHEMA,
    "release_contract": RELEASE_CONTRACT_SCHEMA,
    "scan_artifacts": SECRET_SCAN_SCHEMA,
    "test_evidence": TEST_EVIDENCE_SCHEMA,
    "test_policy": TEST_POLICY_SCHEMA,
}

PERSISTED_RUNTIME_CONTRACTS = {
    **PERSISTED_ACTION_CONTRACTS,
    **PERSISTED_RELEASE_CONTRACTS,
}

__all__ = [
    "COMPATIBILITY_POLICY_SCHEMA",
    "COMPATIBILITY_REPORT_SCHEMA",
    "CONTROL_EVIDENCE_SCHEMA",
    "DIAGNOSTIC_SCHEMA",
    "LAUNCH_PLAN_SCHEMA",
    "LAUNCH_RESULT_SCHEMA",
    "LAUNCH_REVIEW_SCHEMA",
    "LAUNCH_TRANSACTION_SCHEMA",
    "LIVE_ATTESTATION_SCHEMA",
    "LIVE_EVIDENCE_SCHEMA",
    "PERFORMANCE_EVIDENCE_SCHEMA",
    "PERFORMANCE_REPORT_SCHEMA",
    "PERSISTED_ACTION_CONTRACTS",
    "PERSISTED_RELEASE_CONTRACTS",
    "PERSISTED_RUNTIME_CONTRACTS",
    "PROJECT_EFFORT_EVIDENCE_SCHEMA",
    "PROJECT_MIGRATION_REPORT_SCHEMA",
    "PROJECT_MIGRATION_TRANSACTION_SCHEMA",
    "PROJECT_QUALITY_EVIDENCE_SCHEMA",
    "PROJECT_RELEASE_EVIDENCE_SCHEMA",
    "PUBLISH_JOURNAL_SCHEMA",
    "PUBLISH_LOCK_SCHEMA",
    "PUBLISH_RESULT_SCHEMA",
    "PUBLISH_REVIEW_SCHEMA",
    "RELEASE_AUDIT_SCHEMA",
    "RELEASE_CONTRACT_SCHEMA",
    "SECRET_SCAN_SCHEMA",
    "TEST_EVIDENCE_SCHEMA",
    "TEST_POLICY_SCHEMA",
]
