"""Rendering and transactional writes for agency handoff artifacts."""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any, Mapping


_SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(authorization)\s*[:=]\s*(?:bearer\s+)?[^\s,;]+"
    ),
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|client[_-]?secret|password)"
        r"\s*[:=]\s*[^\s,;]+"
    ),
)


class HandoffOutputError(OSError):
    """Categorized failure while committing the handoff output pair."""

    def __init__(self, code: str, message: str, recommended_action: str) -> None:
        self.code = code
        self.recommended_action = recommended_action
        super().__init__(message)


def redact_handoff_text(value: str) -> str:
    """Remove common inline credential forms from user-controlled evidence."""

    result = value
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(lambda match: f"{match.group(1)}=[REDACTED]", result)
    return result


def redact_handoff_value(value: Any) -> Any:
    """Recursively redact every string value exported to handoff artifacts."""

    if isinstance(value, str):
        return redact_handoff_text(value)
    if isinstance(value, Mapping):
        return {key: redact_handoff_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_handoff_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_handoff_value(item) for item in value)
    return value


def render_handoff(scorecard: Mapping[str, Any]) -> str:
    """Render a concise, deterministic editor-facing Markdown handoff."""

    project = _mapping(scorecard.get("project"))
    target = _mapping(scorecard.get("target"))
    agency_pack = _mapping(scorecard.get("agency_pack"))
    inventory = _mapping(scorecard.get("inventory"))
    status = str(scorecard.get("status", "review_required"))
    score = scorecard.get("score", 0)
    maximum = scorecard.get("maximum_score", 100)
    lines = [
        f"# Agency handoff: {project.get('name', 'Unnamed project')}",
        "",
        f"- Status: `{status}`",
        f"- Maintenance score: `{score}/{maximum}`",
        f"- Project ID: `{project.get('id', '')}`",
        f"- Target profile: `{target.get('profile', '')}`",
        f"- Agency pack: `{agency_pack.get('name', '')}` "
        f"(`{agency_pack.get('version', '')}`)",
        f"- Evidence fingerprint: `{scorecard.get('fingerprint', '')}`",
        "",
        "This handoff is read-only evidence. It does not publish or mutate the target site.",
        "",
        "## Readiness checks",
        "",
        "| Check | Result | Evidence | Weight |",
        "| --- | --- | ---: | ---: |",
    ]
    for check in _mappings(scorecard.get("checks")):
        lines.append(
            "| {label} | {status} | {actual} / {required} | {earned}/{weight} |".format(
                label=_table_text(check.get("label", check.get("id", ""))),
                status=_table_text(check.get("status", "unavailable")),
                actual=_table_text(check.get("actual", "")),
                required=_table_text(check.get("required", "")),
                earned=_table_text(check.get("earned_points", 0)),
                weight=_table_text(check.get("weight", 0)),
            )
        )
    lines.extend(
        [
            "",
            "## Managed inventory",
            "",
            f"- Assets: {inventory.get('asset_count', 0)}",
            f"- Reusable page blocks: {inventory.get('library_block_count', 0)}",
            f"- Draft pages: {inventory.get('page_count', 0)}",
            f"- Global header/footer blocks: {inventory.get('global_block_count', 0)}",
            "",
            "## Open items",
            "",
        ]
    )
    open_items = _mappings(scorecard.get("open_items"))
    if open_items:
        for item in open_items:
            category = redact_handoff_text(str(item.get("category", "review")))
            message = redact_handoff_text(str(item.get("message", "")))
            lines.append(f"- **{category}:** {message}")
    else:
        lines.append("- None. All automated readiness checks passed.")
    lines.extend(
        [
            "",
            "## Editor guidance",
            "",
            "- Edit page-specific copy and media in the corresponding draft page blocks.",
            "- Edit shared navigation, header, and footer content in global blocks.",
            "- Keep agency-standard block names and categories when creating variants.",
            "- Rerun verification and this handoff after structural or destination changes.",
            "",
        ]
    )
    return "\n".join(lines)


def commit_handoff_outputs(
    scorecard_path: Path,
    scorecard_text: str,
    handoff_path: Path,
    handoff_text: str,
) -> None:
    """Atomically replace a logical output pair, restoring both on failure."""

    if scorecard_path.parent != handoff_path.parent:
        raise HandoffOutputError(
            "handoff_output_invalid",
            "handoff outputs must share one directory",
            "Use the standard qa output paths and rerun handoff.",
        )
    directory = scorecard_path.parent
    directory.mkdir(parents=True, exist_ok=True)
    outputs = (
        _OutputFile(scorecard_path, scorecard_text),
        _OutputFile(handoff_path, handoff_text),
    )
    for output in outputs:
        output.existed = output.final.exists()
        if output.backup.exists():
            raise HandoffOutputError(
                "handoff_recovery_required",
                f"a prior recovery backup remains: {output.backup}",
                "Restore or remove the named backup after reviewing it, then rerun handoff.",
            )
    try:
        for output in outputs:
            _write_staged(output.temporary, output.text)
        for output in outputs:
            if output.existed:
                output.final.replace(output.backup)
        for output in outputs:
            output.temporary.replace(output.final)
    except OSError as exc:
        rollback_errors = _restore_outputs(outputs)
        if rollback_errors:
            details = "; ".join(rollback_errors)
            raise HandoffOutputError(
                "handoff_rollback_failed",
                f"handoff write failed ({exc}); rollback also failed: {details}",
                "Do not use the generated pair. Restore the .handoff-backup files, then rerun handoff.",
            ) from exc
        raise HandoffOutputError(
            "handoff_write_failed",
            f"handoff output pair was not committed: {exc}",
            "Resolve the filesystem error and rerun handoff; prior outputs were restored.",
        ) from exc
    finally:
        for output in outputs:
            output.temporary.unlink(missing_ok=True)
    cleanup_errors: list[str] = []
    for output in outputs:
        try:
            output.backup.unlink(missing_ok=True)
        except OSError as exc:
            cleanup_errors.append(f"{output.backup}: {exc}")
    if cleanup_errors:
        raise HandoffOutputError(
            "handoff_cleanup_required",
            "the new output pair was committed, but backup cleanup failed: "
            + "; ".join(cleanup_errors),
            "Keep the new output pair together, remove the named stale backup after review, then rerun handoff.",
        )


class _OutputFile:
    def __init__(self, final: Path, text: str) -> None:
        self.final = final
        self.text = text
        self.temporary = final.with_name(f".{final.name}.handoff-tmp")
        self.backup = final.with_name(f".{final.name}.handoff-backup")
        self.existed = False


def _write_staged(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _restore_outputs(outputs: tuple[_OutputFile, ...]) -> list[str]:
    errors: list[str] = []
    for output in outputs:
        try:
            if output.backup.exists():
                output.final.unlink(missing_ok=True)
                output.backup.replace(output.final)
            elif not output.existed:
                output.final.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(f"{output.final}: {exc}")
    return errors


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mappings(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _table_text(value: object) -> str:
    return redact_handoff_text(str(value)).replace("|", "\\|").replace("\n", " ")


__all__ = [
    "HandoffOutputError",
    "commit_handoff_outputs",
    "redact_handoff_text",
    "redact_handoff_value",
    "render_handoff",
]
