"""Tests for vanjaro_cli.migration.sections section classification.

Each test feeds the extractor a small HTML fragment, extracts sections, and
asserts on the resulting ``type`` and ``template`` fields. These tests
exercise the heuristic ladder in ``_classify_section`` end-to-end through
the public ``extract_sections`` API.
"""

from __future__ import annotations

from vanjaro_cli.migration.sections import TEMPLATE_MAP, extract_sections

BASE_URL = "https://example.com/"


def _wrap(body_html: str) -> str:
    return f"<!doctype html><html><body><main>{body_html}</main></body></html>"


def test_classifies_contact_form_section():
    """A section with a real <form> should classify as 'contact'."""
    html = _wrap(
        """
        <section>
          <h2>Get In Touch</h2>
          <p>Send us a message.</p>
          <form>
            <input type="text" name="name">
            <input type="email" name="email">
            <textarea name="message"></textarea>
            <button type="submit">Send</button>
          </form>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)

    assert len(sections) == 1
    assert sections[0]["type"] == "contact"
    assert sections[0]["template"] == TEMPLATE_MAP["contact"]


def test_contact_form_class_with_inputs_outside_form():
    """A contact-classed section with input fields (no <form>) still classifies."""
    html = _wrap(
        """
        <section class="contact-section">
          <h2>Reach Us</h2>
          <input type="email" placeholder="your@email.com">
          <button>Subscribe</button>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    assert sections[0]["type"] == "contact"


def test_empty_form_wrapper_does_not_match_contact():
    """An empty <form> with no inputs should not be misclassified as contact."""
    html = _wrap(
        """
        <section>
          <h2>Newsletter Signup</h2>
          <p>Coming soon.</p>
          <form></form>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    assert sections[0]["type"] != "contact"


def test_classifies_image_gallery_section():
    """≥3 anchor-wrapped images should classify as 'gallery'."""
    html = _wrap(
        """
        <section>
          <h2>My Work</h2>
          <a href="/img/shot-1-full.jpg"><img src="/img/shot-1.jpg" alt="Shot 1"></a>
          <a href="/img/shot-2-full.jpg"><img src="/img/shot-2.jpg" alt="Shot 2"></a>
          <a href="/img/shot-3-full.jpg"><img src="/img/shot-3.jpg" alt="Shot 3"></a>
          <a href="/img/shot-4-full.jpg"><img src="/img/shot-4.jpg" alt="Shot 4"></a>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)

    assert sections[0]["type"] == "gallery"
    assert sections[0]["template"] == TEMPLATE_MAP["gallery"]


def test_two_anchor_images_do_not_match_gallery():
    """Below the ≥3 threshold, anchor-wrapped images should not classify as gallery."""
    html = _wrap(
        """
        <section>
          <h2>Featured</h2>
          <a href="/a.jpg"><img src="/a-thumb.jpg"></a>
          <a href="/b.jpg"><img src="/b-thumb.jpg"></a>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    assert sections[0]["type"] != "gallery"


def test_classifies_blog_card_grid_with_read_more_links():
    """≥3 children with image + heading + 'Read More' should classify as blog_cards."""
    html = _wrap(
        """
        <section>
          <h2>Recent Posts</h2>
          <article>
            <img src="/post-1.jpg">
            <h3>Post One</h3>
            <p>An excerpt for post one.</p>
            <a href="/post/1">Read More</a>
          </article>
          <article>
            <img src="/post-2.jpg">
            <h3>Post Two</h3>
            <p>An excerpt for post two.</p>
            <a href="/post/2">Read More</a>
          </article>
          <article>
            <img src="/post-3.jpg">
            <h3>Post Three</h3>
            <p>An excerpt for post three.</p>
            <a href="/post/3">Read More</a>
          </article>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)

    assert sections[0]["type"] == "blog_cards"
    assert sections[0]["template"] == TEMPLATE_MAP["blog_cards"]


def test_blog_cards_continue_reading_phrase_also_matches():
    """Variant phrasing 'Continue reading' should still match blog_cards."""
    html = _wrap(
        """
        <section>
          <article>
            <img src="/p1.jpg"><h3>One</h3><a href="/1">Continue reading</a>
          </article>
          <article>
            <img src="/p2.jpg"><h3>Two</h3><a href="/2">Continue reading</a>
          </article>
          <article>
            <img src="/p3.jpg"><h3>Three</h3><a href="/3">Continue reading</a>
          </article>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    assert sections[0]["type"] == "blog_cards"


def test_feature_cards_without_read_more_still_match_cards_not_blog_cards():
    """Cards with images and headings but no Read More should classify as plain cards."""
    html = _wrap(
        """
        <section>
          <div>
            <img src="/icon-1.svg"><h3>Speed</h3><p>Fast.</p>
          </div>
          <div>
            <img src="/icon-2.svg"><h3>Safety</h3><p>Secure.</p>
          </div>
          <div>
            <img src="/icon-3.svg"><h3>Simplicity</h3><p>Easy.</p>
          </div>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    assert sections[0]["type"] == "cards"


def test_classifies_bio_about_split_layout():
    """One image + heading + multiple paragraphs should classify as bio."""
    html = _wrap(
        """
        <section>
          <img src="/headshot.jpg" alt="Founder portrait">
          <h2>About the Founder</h2>
          <p>Started the company in 2015 after a decade in industry.</p>
          <p>Believes great design changes the way customers feel about a brand.</p>
          <p>Lives in Philadelphia with her dog.</p>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)

    assert sections[0]["type"] == "bio"
    assert sections[0]["template"] == TEMPLATE_MAP["bio"]


def test_bio_does_not_match_when_too_many_images():
    """Sections with many images should NOT classify as bio (gallery/cards covers them)."""
    html = _wrap(
        """
        <section>
          <h2>Our Team</h2>
          <p>Meet the people behind the work.</p>
          <p>Designers, developers, and strategists.</p>
          <img src="/p1.jpg"><img src="/p2.jpg"><img src="/p3.jpg">
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    assert sections[0]["type"] != "bio"


def test_existing_hero_classification_still_works():
    """Regression: original hero detection (first + heading + button) is intact."""
    html = _wrap(
        """
        <section>
          <h1>Welcome</h1>
          <p>Build great sites.</p>
          <a class="btn" href="/start">Get Started</a>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    assert sections[0]["type"] == "hero"


def test_existing_testimonial_classification_still_works():
    """Regression: blockquote testimonial detection is intact."""
    html = _wrap(
        """
        <section>
          <h2>What clients say</h2>
          <blockquote>"Best vendor we've ever used."</blockquote>
          <p>Happy Customer, ACME Corp</p>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    assert sections[0]["type"] == "testimonial"


def test_classifier_ladder_priority_form_beats_cards():
    """A section with both a form AND ≥3 child blocks should classify as contact."""
    html = _wrap(
        """
        <section>
          <h2>Contact</h2>
          <div><h3>Email</h3></div>
          <div><h3>Phone</h3></div>
          <div><h3>Address</h3></div>
          <form><input type="email" name="email"></form>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    assert sections[0]["type"] == "contact"


def test_classifier_ladder_priority_gallery_beats_cards():
    """A section with anchor-wrapped images should be gallery, not cards."""
    html = _wrap(
        """
        <section>
          <h2>Portfolio</h2>
          <a href="/1.jpg"><img src="/1-thumb.jpg" alt="Project 1"><h3>Project 1</h3></a>
          <a href="/2.jpg"><img src="/2-thumb.jpg" alt="Project 2"><h3>Project 2</h3></a>
          <a href="/3.jpg"><img src="/3-thumb.jpg" alt="Project 3"><h3>Project 3</h3></a>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    assert sections[0]["type"] == "gallery"
