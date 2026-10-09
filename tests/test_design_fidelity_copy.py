"""RT-37 — copy-presence metric: do the designed words show up in the build?"""

from __future__ import annotations

import pytest

from vanjaro_cli.design.fidelity import FidelityDimension
from vanjaro_cli.design.fidelity_copy import (
    BODY_WEIGHT,
    HEADLINE_WEIGHT,
    CopyExpectation,
    SectionCopy,
    score_section_copy,
    tokenize_copy,
)


def _designed(*lines: str | tuple[str, int]) -> SectionCopy:
    return SectionCopy(
        expected=tuple(
            CopyExpectation(text=line[0], weight=line[1])
            if isinstance(line, tuple)
            else CopyExpectation(text=line)
            for line in lines
        )
    )


def _built(text: str | None) -> SectionCopy:
    return SectionCopy(rendered=text)


def _score(designed: SectionCopy, rendered: str | None):
    return score_section_copy(designed, _built(rendered))


class TestPresence:
    def test_every_designed_line_present_scores_full_marks(self) -> None:
        result = _score(
            _designed("Our Classes", "Prelude", "Learn More"),
            "Our Classes Prelude Learn More",
        )

        assert result.dimension is FidelityDimension.COPY
        assert result.score == 100.0
        assert result.detail is None

    def test_matching_ignores_case_punctuation_and_spacing(self) -> None:
        result = _score(
            _designed("Music is magic!", "Happy \nStudents", "didn’t know"),
            "MUSIC IS MAGIC   Happy Students  didn't know",
        )

        assert result.score == 100.0

    def test_a_missing_card_title_costs_points_and_is_named(self) -> None:
        result = _score(
            _designed("Prelude", "Opening Notes", "Finale", "Symphony"),
            "Opening Notes Finale Symphony",
        )

        assert result.score == 75.0
        assert result.detail == "copy absent from the build: 'Prelude'"

    def test_an_empty_page_scores_zero_when_the_design_states_copy(self) -> None:
        result = _score(_designed("Prelude", "Finale"), "")

        assert result.score == 0.0

    def test_a_word_inside_a_longer_word_is_not_a_match(self) -> None:
        result = _score(_designed("10"), "100 years")

        assert result.score == 0.0

    def test_headline_copy_weighs_three_times_body_copy(self) -> None:
        designed = _designed(("Prelude", HEADLINE_WEIGHT), ("Some body words here", BODY_WEIGHT))

        title_missing = _score(designed, "Some body words here")
        body_missing = _score(designed, "Prelude")

        assert title_missing.score == 25.0
        assert body_missing.score == 75.0


class TestEachRenderedWordServesOneLine:
    def test_four_designed_buttons_need_four_in_the_build(self) -> None:
        designed = _designed("Learn More", "Learn More", "Learn More", "Learn More")

        assert _score(designed, "Learn More").score == 25.0
        assert _score(designed, "Learn More Learn More Learn More Learn More").score == 100.0

    def test_a_longer_line_claims_its_words_before_a_shorter_one_can_borrow_them(self) -> None:
        designed = _designed("Learn More About Us", "Learn More")

        result = _score(designed, "Learn More About Us")

        assert result.score == pytest.approx(50.0)
        assert result.detail == "copy absent from the build: 'Learn More'"

    def test_word_order_within_a_line_matters(self) -> None:
        assert _score(_designed("Opening Notes"), "Notes Opening").score == 0.0


class TestLongPassages:
    PASSAGE = "Canta y Baila Conmigo is a unique program for little ones"

    def test_a_lightly_edited_passage_keeps_most_of_its_credit(self) -> None:
        edited = "Canta y Baila Conmigo is a special program for little ones"

        result = _score(_designed(self.PASSAGE), edited)

        assert result.score == pytest.approx(100 * 10 / 11, abs=0.01)
        assert result.detail == "1 passage(s) only partly present"

    def test_a_short_line_is_present_or_it_is_not(self) -> None:
        assert _score(_designed("Join us today"), "Join us").score == 0.0

    def test_a_passage_with_none_of_its_words_is_absent(self) -> None:
        result = _score(_designed(self.PASSAGE), "Something else entirely")

        assert result.score == 0.0
        assert "copy absent from the build" in (result.detail or "")


class TestUnavailableEvidence:
    def test_a_design_that_states_no_copy_is_unmeasured_not_perfect(self) -> None:
        result = _score(_designed(), "Anything")

        assert result.score is None
        assert result.detail == "the design states no copy for this section"

    def test_lines_with_no_words_in_them_state_nothing(self) -> None:
        assert _score(_designed("|", "→", "  "), "Anything").score is None

    def test_a_build_that_did_not_report_its_text_is_unmeasured_not_empty(self) -> None:
        result = _score(_designed("Prelude"), None)

        assert result.score is None
        assert result.detail == "the build did not report its rendered text"


class TestReporting:
    def test_the_report_lists_at_most_five_missing_lines(self) -> None:
        names = [f"Title{index}" for index in range(8)]

        result = _score(_designed(*names), "")

        assert result.detail is not None
        assert result.detail.endswith("and 3 more")
        assert result.detail.count("'") == 10

    def test_scoring_is_repeatable(self) -> None:
        designed = _designed("Prelude", "Opening Notes", ("Finale Symphony", 3))

        first = _score(designed, "Opening Notes Symphony")
        second = _score(designed, "Opening Notes Symphony")

        assert first == second


def test_tokenize_splits_on_anything_that_is_not_a_letter_or_digit() -> None:
    assert tokenize_copy("Hello, World! It’s 80+ élève_s") == [
        "hello", "world", "it", "s", "80", "élève", "s",
    ]
