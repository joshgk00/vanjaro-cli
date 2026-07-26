"""Application workflows that connect pure project state to concrete services."""

from vanjaro_cli.orchestration.project_analysis import (
    ProjectAnalysisError,
    run_project_analysis,
    source_input_files,
)
from vanjaro_cli.orchestration.project_planning import (
    run_project_planning,
    template_catalog_fingerprint,
)
from vanjaro_cli.orchestration.project_verify import (
    ProjectVerificationError,
    verify_project_drafts,
)
from vanjaro_cli.orchestration.project_theme import (
    plan_project_theme_stage,
    preview_project_theme_stage,
)
from vanjaro_cli.orchestration.project_image_evidence import (
    ProjectImageEvidenceError,
    ProjectImageEvidencePlan,
    ProjectImageEvidenceResult,
    generate_project_image_evidence,
    plan_project_image_evidence,
)
from vanjaro_cli.orchestration.portal_identity import (
    PortalIdentityError,
    VerifiedPortal,
    verify_project_portal,
)
from vanjaro_cli.orchestration.project_build import (
    preserve_project_theme,
    preview_project_library_stage,
    preview_project_page_stage,
    preview_project_global_stage,
    reconcile_project_page_stage,
    reconcile_project_global_stage,
    register_project_library_stage,
    upload_project_asset_stage,
)

__all__ = [
    "ProjectAnalysisError",
    "ProjectImageEvidenceError",
    "ProjectImageEvidencePlan",
    "ProjectImageEvidenceResult",
    "ProjectVerificationError",
    "PortalIdentityError",
    "VerifiedPortal",
    "run_project_analysis",
    "generate_project_image_evidence",
    "plan_project_image_evidence",
    "run_project_planning",
    "template_catalog_fingerprint",
    "plan_project_theme_stage",
    "preserve_project_theme",
    "preview_project_theme_stage",
    "preview_project_library_stage",
    "preview_project_page_stage",
    "preview_project_global_stage",
    "reconcile_project_page_stage",
    "reconcile_project_global_stage",
    "register_project_library_stage",
    "source_input_files",
    "verify_project_portal",
    "upload_project_asset_stage",
    "verify_project_drafts",
]
