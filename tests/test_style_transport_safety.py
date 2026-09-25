"""HTML-boundary and CSS-obfuscation safety for the scoped-style transport.

Extends the acceptance blocker recorded in
``docs/agency-composed-style-retention-contract.md`` ("Safety blocker from
root review"): an untrusted ``style_declarations`` value must never be able
to break out of the ``<style>`` element ``render_styles`` (utils/grapesjs.py)
writes it into, and an explicitly malformed (as opposed to absent)
``style_declarations``/``style_scope`` must fail closed rather than be
silently treated as a legacy plan with no style metadata.

Reuses the maintained feature-section fixture from ``test_design_planner.py``
(same technique as ``artifacts/test_style_html_boundary_independent.py`` and
``tests/test_composed_style_transport.py``) so these tests exercise the real
planner/emitter/composer, not a synthetic stand-in for them. No payload here
is ever opened in a browser -- rejection is proven by ``BlockLibraryError``
and by string/parser assertions against the actual generated output.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from vanjaro_cli.design.planner import emit_library_plan, plan_design_document
from vanjaro_cli.portal.block_library import (
    BlockLibraryError,
    compose_project_library,
    register_project_library,
)
from vanjaro_cli.portal.page_composition import compose_project_pages
from vanjaro_cli.utils.grapesjs import render_styles

_FIXTURE = runpy.run_path(str(Path(__file__).resolve().parent / "test_design_planner.py"))
_feature_section = _FIXTURE["_feature_section"]
_document = _FIXTURE["_document"]
CATALOG = _FIXTURE["CATALOG"]

_VALID_SCOPE = ".project-proof .section-proof"


def _library_plan() -> list[dict]:
    plan = plan_design_document(_document(_feature_section()), catalog=CATALOG)
    return emit_library_plan(plan)


class _ClientMustNotBeCalled:
    """A fake portal client that fails the test if touched.

    Proves an explicitly malformed style payload is rejected during
    ``compose_project_library``'s preflight, before ``register_project_library``
    ever reaches a portal request -- not merely that the final result is an
    error.
    """

    def get(self, path: str) -> object:  # pragma: no cover - must never run
        raise AssertionError(f"portal GET {path} must not be called for a rejected plan")

    def post_form(self, path: str, form: dict) -> object:  # pragma: no cover - must never run
        raise AssertionError(f"portal POST {path} must not be called for a rejected plan")


# ---------------------------------------------------------------------------
# HTML-boundary breakout: closing </style> plus injected script/image markup.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "</style><script>alert(1)</script><style>",
        "</STYLE><img src=x onerror=alert(1)><style>",
        "Arial, <ScRipt>alert(1)</ScRipt>",
        "Arial, </style/>",
    ],
    ids=["close-style-script", "close-STYLE-img-onerror", "mixed-case-script", "self-closing-style-slash"],
)
def test_html_breakout_font_family_is_rejected_and_never_reaches_page_html(value: str) -> None:
    library = _library_plan()
    library[0]["style_scope"] = _VALID_SCOPE
    library[0]["style_declarations"] = {"font-family": value}

    with pytest.raises(BlockLibraryError):
        compose_project_library(library)
    # Rejection happens in compose_project_library's own preflight, which
    # runs before compose_project_pages ever exists to serialize
    # content_html -- so there is no visitor-facing HTML for this payload
    # to have reached. The raise above is the proof; nothing further to
    # compose.


# ---------------------------------------------------------------------------
# CSS escape and comment obfuscation: cannot smuggle a breakout or a
# forbidden URL scheme past a naive substring check.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        r"Arial, \3c style\3e",  # CSS hex escape for literal < >
        "Arial /* </style><script>alert(1)</script> */, sans-serif",  # comment-wrapped breakout
        "Arial /* unrelated comment */, sans-serif",  # comment with no breakout content
    ],
    ids=["hex-escape", "comment-wrapped-breakout", "benign-comment-still-rejected"],
)
def test_css_escape_or_comment_syntax_is_rejected(value: str) -> None:
    library = _library_plan()
    library[0]["style_scope"] = _VALID_SCOPE
    library[0]["style_declarations"] = {"font-family": value}

    with pytest.raises(BlockLibraryError):
        compose_project_library(library)


@pytest.mark.parametrize(
    "value",
    [
        "url(jav\\61script:alert(1))",  # CSS escape for the 'a' in javascript:
        "url(\\6a avascript:alert(1))",  # CSS escape for the 'j'
    ],
    ids=["escaped-a-in-javascript-scheme", "escaped-j-in-javascript-scheme"],
)
def test_escaped_dangerous_url_scheme_is_rejected(value: str) -> None:
    library = _library_plan()
    library[0]["style_scope"] = _VALID_SCOPE
    library[0]["style_declarations"] = {"background-image": value}

    with pytest.raises(BlockLibraryError):
        compose_project_library(library)


@pytest.mark.parametrize(
    "scheme",
    ["javascript", "vbscript", "data", "file"],
)
def test_forbidden_url_schemes_are_rejected_unescaped(scheme: str) -> None:
    library = _library_plan()
    library[0]["style_scope"] = _VALID_SCOPE
    library[0]["style_declarations"] = {
        "background-image": f"url({scheme}:something)"
    }

    with pytest.raises(BlockLibraryError):
        compose_project_library(library)


# ---------------------------------------------------------------------------
# Safe quoted font families still work -- the hardened validator must not
# be stricter than what legitimate design translation needs.
# ---------------------------------------------------------------------------


def test_safe_quoted_font_family_list_is_accepted_and_reaches_page_html() -> None:
    library = _library_plan()
    library[0]["style_scope"] = _VALID_SCOPE
    library[0]["style_declarations"] = {"font-family": '"Helvetica Neue", Arial, sans-serif'}

    composed = compose_project_library(library)
    css = render_styles(composed[0]["style_json"])
    assert '"Helvetica Neue", Arial, sans-serif' in css

    document = _document(_feature_section())
    pages = compose_project_pages(
        document, composed, {"entries": []}, project_id="style-safety-proof", isolated=True
    )
    page = pages[0]
    assert '"Helvetica Neue", Arial, sans-serif' in page["content_html"]
    assert page["content_html"].startswith("<style>")


# ---------------------------------------------------------------------------
# Explicit malformed metadata must fail closed, not look like an absent
# legacy plan -- and must never reach a portal client call.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("malformed", [False, 0, "", []], ids=["false", "zero", "empty-string", "empty-list"])
def test_explicit_falsy_malformed_style_declarations_fail_closed(malformed: object) -> None:
    library = _library_plan()
    library[0]["style_scope"] = _VALID_SCOPE
    library[0]["style_declarations"] = malformed

    with pytest.raises(BlockLibraryError):
        compose_project_library(library)


@pytest.mark.parametrize("malformed", [False, 0, "", []], ids=["false", "zero", "empty-string", "empty-list"])
def test_malformed_style_declarations_rejected_before_any_portal_client_call(
    malformed: object, tmp_path: Path
) -> None:
    library = _library_plan()
    library[0]["style_scope"] = _VALID_SCOPE
    library[0]["style_declarations"] = malformed

    with pytest.raises(BlockLibraryError):
        register_project_library(
            _ClientMustNotBeCalled(),
            plan=library,
            manifest_path=tmp_path / "block-manifest.json",
        )


def test_empty_dict_style_declarations_is_a_deliberate_no_styles_payload() -> None:
    """An empty dict is the one falsy shape that is a legitimate, explicit
    "no styles to add" payload -- distinct from False/0/''/[], which are
    malformed types, not an empty style set. It must not be blanket
    rejected the way the malformed shapes above are.
    """

    library = _library_plan()
    library[0]["style_scope"] = _VALID_SCOPE
    library[0]["style_declarations"] = {}

    composed = compose_project_library(library)
    assert composed[0]["style_json"] == []


def test_legacy_entry_without_style_metadata_is_still_accepted() -> None:
    library = _library_plan()
    assert "style_declarations" not in library[0]
    assert "style_scope" not in library[0]

    composed = compose_project_library(library)
    assert composed[0]["style_json"] == []
