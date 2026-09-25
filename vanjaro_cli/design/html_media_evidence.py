"""Browser CSSOM acquisition for width-based responsive condition evidence.

Collects, for a set of CSS selectors already identified by
``html_adapter.py``'s rendered capture, every accessible stylesheet
declaration that could apply to each selector's element: which property it
sets, whether it is gated by a supported width-based ``@media`` condition
(bounded ``min-width``/``max-width``, in px, optionally nested/intersected),
and enough cascade metadata (source order, selector specificity,
``!important``) for ``responsive_conditions.resolve_property_condition`` to
decide which declaration wins for a sampled breakpoint.

All CSS parsing/matching happens inside the injected script, using the
browser's own ``CSSOM``/``Element.matches`` -- this module never parses CSS
text in Python. A declaration gated by anything outside the supported
grammar (a comma-separated media list, a non-width feature, ``@supports``,
a container query, or an inaccessible/cross-origin sheet) is reported with
``supported=False`` and an explicit reason instead of being silently
dropped or guessed at.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from vanjaro_cli.design.responsive_conditions import BoundToken, RawDeclaration
from vanjaro_cli.design.style_translation import _CSS_PROPERTY_NAMES

# Every CSS property name the translator (design/style_translation.py) is
# willing to emit -- the only properties whose condition attribution could
# ever matter downstream. Probed explicitly by name (see
# `_MEDIA_EVIDENCE_JS_TEMPLATE`) rather than discovered by enumerating a
# rule's declared properties.
_SUPPORTED_CSS_PROPERTIES: tuple[str, ...] = tuple(sorted(set(_CSS_PROPERTY_NAMES.values())))

__all__ = [
    "MediaEvidenceResult",
    "SectionMediaEvidence",
    "collect_media_condition_evidence",
]


class _EvaluatablePage(Protocol):
    """Small Playwright page surface used by this module.

    Matches ``html_adapter._RenderedBrowserPage``: one string argument only.
    The selector list is embedded into the evaluated expression itself
    (see ``collect_media_condition_evidence``) rather than passed as a
    second ``evaluate`` argument, so this module works with any page object
    that implements that single-argument surface -- real or test double.
    """

    def evaluate(self, expression: str) -> Any: ...


# Executed once per capture (viewport-independent: stylesheet text and rule
# order do not change with the viewport, only which `@media` block currently
# matches -- and this script reads every block's condition text regardless
# of whether it currently matches, since a rule that is inactive at capture
# time may still be the real source-authored threshold for another sampled
# breakpoint).
_MEDIA_EVIDENCE_JS_TEMPLATE = r"""((selectors, properties) => {
    const sheetGaps = [];
    const bySelector = {};
    const targets = [];
    for (const sel of selectors) {
        let el = null;
        try { el = document.querySelector(sel); } catch (e) { el = null; }
        targets.push({ selector: sel, el });
        bySelector[sel] = [];
    }

    const widthFeatureRe = /^\s*\(\s*(min-width|max-width)\s*:\s*([\d.]+)\s*px\s*\)\s*$/i;

    function parseCondition(conditionText) {
        const text = (conditionText || '').trim();
        if (!text) return { bounds: [], supported: true, reason: null };
        if (text.indexOf(',') !== -1) {
            return { bounds: [], supported: false, reason: 'unsupported media list (comma-separated OR): ' + text };
        }
        const parts = text.split(/\s+and\s+/i);
        const bounds = [];
        for (const part of parts) {
            const m = part.match(widthFeatureRe);
            if (!m) {
                return { bounds: [], supported: false, reason: 'unsupported media feature: ' + text };
            }
            bounds.push({
                kind: m[1].toLowerCase() === 'min-width' ? 'min_width' : 'max_width',
                threshold_px: Math.round(parseFloat(m[2])),
            });
        }
        return { bounds, supported: true, reason: null };
    }

    function specificityOf(selectorPart) {
        let text = selectorPart;
        // Strip attribute/pseudo-class argument contents so they are not
        // mistaken for extra class/type tokens by the crude counts below.
        text = text.replace(/\[[^\]]*\]/g, ' [attr] ');
        text = text.replace(/::?[-\w]+(\([^)]*\))?/g, (m) => (m.indexOf('::') === 0 ? ' ' : m));
        const ids = (text.match(/#[-\w]+/g) || []).length;
        const classesAttrsPseudo =
            (text.match(/\.[-\w]+/g) || []).length +
            (text.match(/\[attr\]/g) || []).length +
            (text.match(/:[-\w]+(\([^)]*\))?/g) || []).length;
        const stripped = text
            .replace(/#[-\w]+/g, ' ')
            .replace(/\.[-\w]+/g, ' ')
            .replace(/\[attr\]/g, ' ')
            .replace(/:[-\w]+(\([^)]*\))?/g, ' ');
        const types = (stripped.match(/(^|[\s>+~(])[a-zA-Z][-\w]*/g) || []).length;
        return [ids, classesAttrsPseudo, types];
    }

    let order = 0;

    function walkRules(rules, boundsStack, unsupportedGap) {
        for (const rule of rules) {
            order += 1;
            const ctorName = rule.constructor ? rule.constructor.name : '';
            if (ctorName === 'CSSMediaRule') {
                const parsed = parseCondition(rule.conditionText || (rule.media && rule.media.mediaText));
                let nested;
                try { nested = Array.from(rule.cssRules); } catch (e) { nested = []; }
                if (parsed.supported) {
                    walkRules(nested, boundsStack.concat(parsed.bounds), unsupportedGap);
                } else {
                    walkRules(nested, boundsStack, parsed.reason);
                }
            } else if (ctorName === 'CSSStyleRule') {
                let selectorParts;
                try { selectorParts = rule.selectorText.split(','); } catch (e) { continue; }
                for (const rawSelectorPart of selectorParts) {
                    const selectorPart = rawSelectorPart.trim();
                    if (!selectorPart) continue;
                    for (const target of targets) {
                        if (!target.el) continue;
                        let matches = false;
                        try { matches = target.el.matches(selectorPart); } catch (e) { matches = false; }
                        if (!matches) continue;
                        const style = rule.style;
                        const specificity = specificityOf(selectorPart);
                        // Probe a fixed, known property list via
                        // getPropertyValue rather than enumerating
                        // style.length/style[i]: Chromium's CSSOM expands a
                        // shorthand like `background-position` into its
                        // longhands (`background-position-x`/`-y`) for index
                        // enumeration, so a source declaring the shorthand
                        // never showed up under its own name and silently
                        // lost its condition. getPropertyValue resolves the
                        // shorthand correctly regardless of how the engine
                        // stores it internally.
                        for (const prop of properties) {
                            const value = style.getPropertyValue(prop);
                            if (!value) continue;
                            bySelector[target.selector].push({
                                css_property: prop,
                                value: value,
                                important: style.getPropertyPriority(prop) === 'important',
                                order: order,
                                specificity: specificity,
                                bounds: unsupportedGap ? [] : boundsStack,
                                supported: !unsupportedGap,
                                selector: selectorPart,
                                reason: unsupportedGap || null,
                            });
                        }
                    }
                }
            } else if (ctorName === 'CSSSupportsRule' || ctorName === 'CSSContainerRule') {
                let nested;
                try { nested = Array.from(rule.cssRules); } catch (e) { nested = []; }
                const reason = ctorName === 'CSSContainerRule'
                    ? 'container queries are not supported grammar'
                    : '@supports-gated rules are not supported grammar';
                walkRules(nested, boundsStack, reason);
            }
            // Other rule kinds (@keyframes, @font-face, @import, @page, ...)
            // carry no width-gated declarations of interest and are skipped.
        }
    }

    for (const sheet of Array.from(document.styleSheets)) {
        let rules;
        try {
            rules = sheet.cssRules;
        } catch (e) {
            sheetGaps.push((sheet.href || 'inline') + ': ' + String(e && e.message ? e.message : e));
            continue;
        }
        if (rules == null) {
            sheetGaps.push((sheet.href || 'inline') + ': inaccessible');
            continue;
        }
        walkRules(Array.from(rules), [], null);
    }

    return { by_selector: bySelector, sheet_gaps: sheetGaps };
})(__SELECTORS_JSON__, __PROPERTIES_JSON__)"""


class SectionMediaEvidence:
    """Accessible declaration evidence for one section's selector."""

    __slots__ = ("selector", "declarations")

    def __init__(self, selector: str, declarations: tuple[RawDeclaration, ...]) -> None:
        self.selector = selector
        self.declarations = declarations

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"SectionMediaEvidence(selector={self.selector!r}, declarations={len(self.declarations)})"


class MediaEvidenceResult:
    """Per-selector accessible declaration evidence plus stylesheet gaps."""

    __slots__ = ("by_selector", "sheet_gaps")

    def __init__(
        self,
        by_selector: dict[str, SectionMediaEvidence],
        sheet_gaps: tuple[str, ...],
    ) -> None:
        self.by_selector = by_selector
        self.sheet_gaps = sheet_gaps


def _bounds_from_raw(raw_bounds: Any) -> tuple[BoundToken, ...]:
    if not isinstance(raw_bounds, list):
        return ()
    bounds: list[BoundToken] = []
    for item in raw_bounds:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        threshold = item.get("threshold_px")
        if kind not in ("min_width", "max_width") or not isinstance(threshold, (int, float)):
            continue
        bounds.append((str(kind), int(threshold)))
    return tuple(bounds)


def collect_media_condition_evidence(
    page: _EvaluatablePage, selectors: list[str]
) -> MediaEvidenceResult:
    """Collect accessible width-media declaration evidence for ``selectors``.

    ``selectors`` are the same section selectors ``capture_rendered_observations``
    already derived (``RenderedSectionObservation.selector``). Duplicate
    selectors are de-duplicated (order preserved) before evaluation.
    """

    deduped = list(dict.fromkeys(selectors))
    expression = _MEDIA_EVIDENCE_JS_TEMPLATE.replace(
        "__SELECTORS_JSON__", json.dumps(deduped)
    ).replace("__PROPERTIES_JSON__", json.dumps(list(_SUPPORTED_CSS_PROPERTIES)))
    raw = page.evaluate(expression)
    if not isinstance(raw, dict):
        return MediaEvidenceResult(by_selector={}, sheet_gaps=())

    raw_by_selector = raw.get("by_selector")
    by_selector: dict[str, SectionMediaEvidence] = {}
    if isinstance(raw_by_selector, dict):
        for selector, raw_declarations in raw_by_selector.items():
            if not isinstance(raw_declarations, list):
                continue
            declarations: list[RawDeclaration] = []
            for item in raw_declarations:
                if not isinstance(item, dict):
                    continue
                specificity_raw = item.get("specificity")
                specificity = (
                    tuple(int(value) for value in specificity_raw)
                    if isinstance(specificity_raw, list) and len(specificity_raw) == 3
                    else (0, 0, 0)
                )
                declarations.append(
                    RawDeclaration(
                        css_property=str(item.get("css_property") or ""),
                        value=str(item.get("value") or ""),
                        important=bool(item.get("important")),
                        order=int(item.get("order") or 0),
                        specificity=specificity,  # type: ignore[arg-type]
                        bounds=_bounds_from_raw(item.get("bounds")),
                        supported=bool(item.get("supported")),
                        selector=str(item.get("selector") or ""),
                        reason=item.get("reason"),
                    )
                )
            by_selector[str(selector)] = SectionMediaEvidence(str(selector), tuple(declarations))

    raw_gaps = raw.get("sheet_gaps")
    sheet_gaps = tuple(str(gap) for gap in raw_gaps) if isinstance(raw_gaps, list) else ()
    return MediaEvidenceResult(by_selector=by_selector, sheet_gaps=sheet_gaps)
