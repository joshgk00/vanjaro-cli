"""The two measurement scripts must sample the same elements.

One reads the design, the other reads the built page, and the score is the
difference between them. If they sample different elements the difference is
not a defect in the build — it is a defect in the measurement, and it looks
exactly like a real one.
"""

from __future__ import annotations

from vanjaro_cli.design import fidelity_measure, html_adapter


def _analysis() -> str:
    return html_adapter._RENDERED_OBSERVATION_JS


def _built() -> str:
    return fidelity_measure.MEASURE_SCRIPT


def test_both_scripts_take_the_most_prominent_heading() -> None:
    """Taking the first means a section led by a small kicker compares the
    kicker's font against the headline's and reports a defect that is not one."""

    for script in (_analysis(), _built()):
        assert "headingElement" in script
        start = script.index("const headingElement")
        assert "reduce" in script[start : start + 800]


def test_both_scripts_require_an_action_to_carry_a_label() -> None:
    """An action with no label is not the call: a thumbnail wrapped in a link
    must not supply the accent colour on either side."""

    for script in (_analysis(), _built()):
        assert "querySelectorAll('a, button')" in script
        assert "querySelector('a, button')" not in script


def test_both_scripts_walk_ancestors_for_a_painted_background() -> None:
    for script in (_analysis(), _built()):
        assert "effectiveBackground" in script
        start = script.index("const effectiveBackground")
        assert "parentElement" in script[start : start + 400]


def test_both_scripts_measure_rhythm_the_same_way() -> None:
    for script in (_analysis(), _built()):
        assert "elementGap" in script
        start = script.index("const elementGap")
        assert "single-child wrappers" in script[start : start + 600]
