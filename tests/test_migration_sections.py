"""Tests for vanjaro_cli.migration.sections section classification.

Each test feeds the extractor a small HTML fragment, extracts sections, and
asserts on the resulting ``type`` and ``template`` fields. These tests
exercise the heuristic ladder in ``_classify_section`` end-to-end through
the public ``extract_sections`` API.
"""

from __future__ import annotations

from vanjaro_cli.migration.sections import (
    TEMPLATE_MAP,
    collect_image_urls,
    extract_global_element,
    extract_sections,
)

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


def test_extract_content_includes_list_items():
    """List items from <ul> and <ol> should appear in content.list_items."""
    html = _wrap(
        """
        <section>
          <h2>Quick Links</h2>
          <ul>
            <li>Home</li>
            <li>About</li>
            <li>Services</li>
          </ul>
          <ol>
            <li>Step One</li>
            <li>Step Two</li>
          </ol>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)

    assert len(sections) == 1
    list_items = sections[0]["content"]["list_items"]
    assert list_items == ["Home", "About", "Services", "Step One", "Step Two"]


def test_extract_content_skips_empty_list_items():
    """Empty <li> elements should be excluded from list_items."""
    html = _wrap(
        """
        <section>
          <h2>Links</h2>
          <ul>
            <li>Valid</li>
            <li>  </li>
            <li>Also Valid</li>
          </ul>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    assert sections[0]["content"]["list_items"] == ["Valid", "Also Valid"]


def test_extract_content_empty_list_items_when_no_lists():
    """Sections without lists should have an empty list_items array."""
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
    assert sections[0]["content"]["list_items"] == []


def test_extract_blockquotes():
    """Blockquotes should be extracted with text and citation."""
    html = _wrap(
        """
        <section>
          <h2>Testimonials</h2>
          <blockquote>
            Great service and fast delivery.
            <cite>Jane Doe</cite>
          </blockquote>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    blockquotes = sections[0]["content"]["blockquotes"]

    assert len(blockquotes) == 1
    assert blockquotes[0]["text"] == "Great service and fast delivery."
    assert blockquotes[0]["citation"] == "Jane Doe"


def test_extract_blockquote_without_citation():
    """Blockquotes without citation should have empty citation field."""
    html = _wrap(
        """
        <section>
          <h2>Quote</h2>
          <blockquote>Just a simple quote.</blockquote>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    bq = sections[0]["content"]["blockquotes"][0]
    assert bq["text"] == "Just a simple quote."
    assert bq["citation"] == ""


def test_extract_tables():
    """Tables should be extracted as arrays of rows."""
    html = _wrap(
        """
        <section>
          <h2>Pricing</h2>
          <table>
            <tr><th>Plan</th><th>Price</th></tr>
            <tr><td>Basic</td><td>$10/mo</td></tr>
            <tr><td>Pro</td><td>$25/mo</td></tr>
          </table>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    tables = sections[0]["content"]["tables"]

    assert len(tables) == 1
    assert tables[0][0] == ["Plan", "Price"]
    assert tables[0][1] == ["Basic", "$10/mo"]
    assert tables[0][2] == ["Pro", "$25/mo"]


def test_extract_videos_native():
    """Native video elements should be extracted with type=native."""
    html = _wrap(
        """
        <section>
          <h2>Demo</h2>
          <video src="/demo.mp4"></video>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    videos = sections[0]["content"]["videos"]

    assert len(videos) == 1
    assert videos[0]["type"] == "native"
    assert videos[0]["src"] == "https://example.com/demo.mp4"


def test_extract_videos_iframe_embed():
    """Iframe embeds (YouTube, Vimeo) should be extracted with type=embed."""
    html = _wrap(
        """
        <section>
          <h2>Watch</h2>
          <iframe src="https://www.youtube.com/embed/abc123"></iframe>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    videos = sections[0]["content"]["videos"]

    assert len(videos) == 1
    assert videos[0]["type"] == "embed"
    assert videos[0]["src"] == "https://www.youtube.com/embed/abc123"


def test_extract_video_source_element():
    """Video with <source> child should extract the source src."""
    html = _wrap(
        """
        <section>
          <h2>Video</h2>
          <video><source src="/clip.webm" type="video/webm"></video>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    videos = sections[0]["content"]["videos"]

    assert len(videos) == 1
    assert videos[0]["src"] == "https://example.com/clip.webm"


def test_extract_figure_with_caption():
    """Figure with figcaption should add caption to the image entry."""
    html = _wrap(
        """
        <section>
          <h2>Gallery</h2>
          <figure>
            <img src="/photo.jpg" alt="Sunset">
            <figcaption>A beautiful sunset over the lake.</figcaption>
          </figure>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    images = sections[0]["content"]["images"]

    # The img is extracted by the normal img loop, then figure loop adds caption
    sunset_img = [i for i in images if "photo.jpg" in i["src"]][0]
    assert sunset_img["caption"] == "A beautiful sunset over the lake."
    assert sunset_img["alt"] == "Sunset"


def test_extract_empty_new_content_types():
    """Sections without blockquotes/tables/videos should have empty arrays."""
    html = _wrap(
        """
        <section>
          <h1>Simple</h1>
          <p>Just text.</p>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    content = sections[0]["content"]
    assert content["blockquotes"] == []
    assert content["tables"] == []
    assert content["videos"] == []


def test_classifies_faq_with_details_elements():
    """3+ <details> elements should classify as faq."""
    html = _wrap(
        """
        <section>
          <h2>FAQ</h2>
          <details><summary>Question 1</summary><p>Answer 1</p></details>
          <details><summary>Question 2</summary><p>Answer 2</p></details>
          <details><summary>Question 3</summary><p>Answer 3</p></details>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    assert sections[0]["type"] == "faq"
    assert sections[0]["template"] == TEMPLATE_MAP["faq"]


def test_classifies_faq_with_accordion_class():
    """Section with accordion class and 3+ children should classify as faq."""
    html = _wrap(
        """
        <section class="accordion">
          <div><h3>Q1</h3><p>A1</p></div>
          <div><h3>Q2</h3><p>A2</p></div>
          <div><h3>Q3</h3><p>A3</p></div>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    assert sections[0]["type"] == "faq"


def test_classifies_faq_with_accordion_item_children():
    """Children with accordion-item class should classify as faq."""
    html = _wrap(
        """
        <section>
          <h2>Questions</h2>
          <div class="accordion-item"><h3>Q1</h3><p>A1</p></div>
          <div class="accordion-item"><h3>Q2</h3><p>A2</p></div>
          <div class="accordion-item"><h3>Q3</h3><p>A3</p></div>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    assert sections[0]["type"] == "faq"


def test_two_details_do_not_match_faq():
    """Below the 3-element threshold, details should not classify as faq."""
    html = _wrap(
        """
        <section>
          <details><summary>Q1</summary><p>A1</p></details>
          <details><summary>Q2</summary><p>A2</p></details>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    assert sections[0]["type"] != "faq"


def test_classifies_pricing_by_class_name():
    """Section with 'pricing' class should classify as pricing."""
    html = _wrap(
        """
        <section class="pricing-section">
          <h2>Our Plans</h2>
          <div><h3>Basic</h3><p>$10/mo</p></div>
          <div><h3>Pro</h3><p>$25/mo</p></div>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    assert sections[0]["type"] == "pricing"


def test_classifies_pricing_by_currency_symbols():
    """3+ children with currency+digit patterns should classify as pricing."""
    html = _wrap(
        """
        <section>
          <h2>Plans</h2>
          <div><h3>Starter</h3><span>$9</span><p>Basic features</p></div>
          <div><h3>Growth</h3><span>$29</span><p>More features</p></div>
          <div><h3>Enterprise</h3><span>$99</span><p>All features</p></div>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    assert sections[0]["type"] == "pricing"


def test_classifies_stats_by_digit_headings():
    """3+ children with mostly-digit headings should classify as stats."""
    html = _wrap(
        """
        <section>
          <div><h3>500+</h3><p>Clients Served</p></div>
          <div><h3>1,200</h3><p>Projects Completed</p></div>
          <div><h3>99%</h3><p>Satisfaction Rate</p></div>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    assert sections[0]["type"] == "stats"
    assert sections[0]["template"] == TEMPLATE_MAP["stats"]


def test_stats_needs_three_digit_blocks():
    """Two stat blocks should not classify as stats."""
    html = _wrap(
        """
        <section>
          <div><span>42</span><p>Employees</p></div>
          <div><span>7</span><p>Offices</p></div>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    assert sections[0]["type"] != "stats"


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


# -- Responsive image extraction (srcset, <picture>) --


def test_extract_img_srcset_and_sizes():
    """img tags with srcset and sizes should capture those attributes."""
    html = _wrap(
        """
        <section>
          <h2>Hero</h2>
          <img src="/hero.jpg" alt="Hero"
               srcset="/hero-400.jpg 400w, /hero-800.jpg 800w"
               sizes="(max-width: 600px) 400px, 800px">
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    img = sections[0]["content"]["images"][0]

    assert img["src"] == "https://example.com/hero.jpg"
    assert img["srcset"] == "/hero-400.jpg 400w, /hero-800.jpg 800w"
    assert img["sizes"] == "(max-width: 600px) 400px, 800px"
    assert "https://example.com/hero-400.jpg" in img["srcset_urls"]
    assert "https://example.com/hero-800.jpg" in img["srcset_urls"]


def test_extract_img_without_srcset_has_no_srcset_key():
    """Plain img tags without srcset should not have srcset/sizes keys."""
    html = _wrap(
        """
        <section>
          <h2>Simple</h2>
          <img src="/photo.jpg" alt="Photo">
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    img = sections[0]["content"]["images"][0]

    assert "srcset" not in img
    assert "sizes" not in img
    assert "srcset_urls" not in img


def test_extract_picture_source_elements():
    """<picture> with <source> elements should extract each source entry."""
    html = _wrap(
        """
        <section>
          <h2>Responsive</h2>
          <picture>
            <source srcset="/hero.webp 1x, /hero@2x.webp 2x" type="image/webp">
            <source srcset="/hero.jpg 1x, /hero@2x.jpg 2x" type="image/jpeg">
            <img src="/hero.jpg" alt="Fallback">
          </picture>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    images = sections[0]["content"]["images"]

    # The <img> inside <picture> is extracted by the normal img loop
    fallback = [i for i in images if i["src"] == "https://example.com/hero.jpg" and i.get("role") != "picture_source"]
    assert len(fallback) == 1

    # Each <source> also generates an entry
    sources = [i for i in images if i.get("role") == "picture_source"]
    assert len(sources) == 2
    assert sources[0]["source_type"] == "image/webp"
    assert "https://example.com/hero.webp" in sources[0]["srcset_urls"]
    assert sources[1]["source_type"] == "image/jpeg"


def test_collect_image_urls_includes_srcset_urls():
    """collect_image_urls should include all srcset URLs in the manifest."""
    html = _wrap(
        """
        <section>
          <h2>Gallery</h2>
          <img src="/photo.jpg" alt="Photo"
               srcset="/photo-sm.jpg 400w, /photo-lg.jpg 800w">
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    urls = collect_image_urls(sections)

    assert "https://example.com/photo.jpg" in urls
    assert "https://example.com/photo-sm.jpg" in urls
    assert "https://example.com/photo-lg.jpg" in urls


# -- CSS background-image extraction --


def test_extract_background_image_from_inline_style():
    """Elements with background-image in inline style should add to images."""
    html = _wrap(
        """
        <section>
          <div style="background-image: url('/hero-bg.jpg'); height: 400px;">
            <h1>Welcome</h1>
          </div>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    images = sections[0]["content"]["images"]

    bg_images = [i for i in images if i.get("role") == "background"]
    assert len(bg_images) == 1
    assert bg_images[0]["src"] == "https://example.com/hero-bg.jpg"


def test_extract_background_image_with_quotes():
    """background-image url() with double quotes should be parsed."""
    html = _wrap(
        """
        <section>
          <div style='background-image: url("/banner.png")'>
            <h2>Banner</h2>
          </div>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    bg_images = [i for i in sections[0]["content"]["images"] if i.get("role") == "background"]

    assert len(bg_images) == 1
    assert bg_images[0]["src"] == "https://example.com/banner.png"


def test_extract_background_image_no_quotes():
    """background-image url() without quotes should be parsed."""
    html = _wrap(
        """
        <section>
          <div style="background-image: url(https://cdn.example.com/bg.jpg)">
            <h2>CDN Image</h2>
          </div>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    bg_images = [i for i in sections[0]["content"]["images"] if i.get("role") == "background"]

    assert len(bg_images) == 1
    assert bg_images[0]["src"] == "https://cdn.example.com/bg.jpg"


def test_extract_background_image_deduplicates():
    """Duplicate background-image URLs within a section should appear once."""
    html = _wrap(
        """
        <section>
          <div style="background-image: url('/bg.jpg')">
            <div style="background-image: url('/bg.jpg')">
              <h2>Nested</h2>
            </div>
          </div>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    bg_images = [i for i in sections[0]["content"]["images"] if i.get("role") == "background"]

    assert len(bg_images) == 1


def test_no_background_image_when_no_inline_styles():
    """Sections without inline styles should not have background role images."""
    html = _wrap(
        """
        <section>
          <h1>Plain</h1>
          <p>No background images here.</p>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    bg_images = [i for i in sections[0]["content"]["images"] if i.get("role") == "background"]

    assert len(bg_images) == 0


def test_collect_image_urls_includes_background_images():
    """collect_image_urls should include background-image URLs."""
    html = _wrap(
        """
        <section>
          <div style="background-image: url('/hero-bg.jpg')">
            <h1>Hero</h1>
            <img src="/logo.png" alt="Logo">
          </div>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)
    urls = collect_image_urls(sections)

    assert "https://example.com/logo.png" in urls
    assert "https://example.com/hero-bg.jpg" in urls


# --- Header nav_items extraction ---


def _header_html(nav_markup: str) -> str:
    return f"<!doctype html><html><body><header>{nav_markup}</header></body></html>"


def test_header_extracts_flat_nav_items():
    """Top-level nav links become a flat nav_items list."""
    html = _header_html(
        """
        <nav>
          <ul>
            <li><a href="/">Home</a></li>
            <li><a href="/about">About</a></li>
            <li><a href="/contact">Contact</a></li>
          </ul>
        </nav>
        """
    )

    header = extract_global_element(html, BASE_URL, "header")

    assert header is not None
    nav_items = header["content"]["nav_items"]
    labels = [item["label"] for item in nav_items]
    assert labels == ["Home", "About", "Contact"]
    assert all(item["children"] == [] for item in nav_items)
    assert nav_items[1]["href"] == "https://example.com/about"


def test_header_extracts_nested_dropdown_as_children():
    """A <li> containing a nested <ul> produces a children array."""
    html = _header_html(
        """
        <nav>
          <ul>
            <li><a href="/services">Services</a>
              <ul>
                <li><a href="/services/web">Web Design</a></li>
                <li><a href="/services/seo">SEO</a></li>
              </ul>
            </li>
          </ul>
        </nav>
        """
    )

    nav_items = extract_global_element(html, BASE_URL, "header")["content"]["nav_items"]

    assert len(nav_items) == 1
    services = nav_items[0]
    assert services["label"] == "Services"
    assert len(services["children"]) == 2
    assert services["children"][0]["label"] == "Web Design"
    assert services["children"][1]["href"] == "https://example.com/services/seo"


def test_header_skips_hash_only_anchors():
    """Hash-only hrefs like #home aren't real pages and must be dropped."""
    html = _header_html(
        """
        <nav>
          <ul>
            <li><a href="#home">Home</a></li>
            <li><a href="/about">About</a></li>
            <li><a href="#contact">Contact</a></li>
          </ul>
        </nav>
        """
    )

    nav_items = extract_global_element(html, BASE_URL, "header")["content"]["nav_items"]

    labels = [item["label"] for item in nav_items]
    assert labels == ["About"]


def test_header_skips_protocol_links():
    """mailto:, tel:, and javascript: links are dropped from the nav tree."""
    html = _header_html(
        """
        <nav>
          <ul>
            <li><a href="mailto:hi@example.com">Email</a></li>
            <li><a href="tel:+15551234567">Call</a></li>
            <li><a href="javascript:void(0)">Do thing</a></li>
            <li><a href="/real-page">Real Page</a></li>
          </ul>
        </nav>
        """
    )

    nav_items = extract_global_element(html, BASE_URL, "header")["content"]["nav_items"]

    labels = [item["label"] for item in nav_items]
    assert labels == ["Real Page"]


def test_header_without_nav_returns_empty_nav_items():
    """A header with no <nav> element still returns nav_items=[]."""
    html = "<!doctype html><html><body><header><h1>Hi</h1></header></body></html>"

    header = extract_global_element(html, BASE_URL, "header")

    assert header["content"]["nav_items"] == []


def test_header_with_empty_nav_returns_empty_nav_items():
    """A <nav> with no <ul> returns nav_items=[]."""
    html = _header_html("<nav></nav>")

    header = extract_global_element(html, BASE_URL, "header")

    assert header["content"]["nav_items"] == []


def test_footer_does_not_get_nav_items():
    """Only headers get nav_items — footers keep the existing flat links list."""
    html = (
        "<!doctype html><html><body><footer>"
        "<nav><ul><li><a href='/privacy'>Privacy</a></li></ul></nav>"
        "</footer></body></html>"
    )

    footer = extract_global_element(html, BASE_URL, "footer")

    assert "nav_items" not in footer["content"]


# -- Per-card content rescoping --


def test_blog_cards_realign_heading_to_image_per_card():
    """Blog card sections should pair each heading with the image inside its own card.

    Regression: the cmw blog index had header logos and chamber-of-commerce
    images ahead of the blog cards in document order. The flat extractor put
    those images at positions 1-4 in ``images[]`` while the real blog card
    headings started at position 1 in ``headings[]``, so ``image_N`` for
    each card resolved to the wrong URL (all cards shared the site logo).
    """
    # The scenario: the source page wraps everything in a single <form> with
    # chrome imagery before the blog cards. The anchor-wrapped thumbnails on
    # the cards make the gallery classifier fire first (same as cmw's live
    # blog index), so the rescope must still find the per-card wrappers.
    html = _wrap(
        """
        <section>
          <img src="/site-logo.png" alt="Site Logo">
          <img src="/banner.jpg" alt="Site Banner">
          <article>
            <a href="/post/1"><img src="/post-1-featured.jpg" alt="Post 1"></a>
            <h2>Post One</h2>
            <p>Excerpt one.</p>
          </article>
          <article>
            <a href="/post/2"><img src="/post-2-featured.jpg" alt="Post 2"></a>
            <h2>Post Two</h2>
            <p>Excerpt two.</p>
          </article>
          <article>
            <a href="/post/3"><img src="/post-3-featured.jpg" alt="Post 3"></a>
            <h2>Post Three</h2>
            <p>Excerpt three.</p>
          </article>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)

    assert len(sections) == 1
    content = sections[0]["content"]
    assert content["headings"] == ["Post One", "Post Two", "Post Three"]
    assert [img["src"] for img in content["images"]] == [
        "https://example.com/post-1-featured.jpg",
        "https://example.com/post-2-featured.jpg",
        "https://example.com/post-3-featured.jpg",
    ]
    assert content["paragraphs"] == ["Excerpt one.", "Excerpt two.", "Excerpt three."]


def test_feature_cards_realign_per_card_with_sibling_img_and_heading():
    """Feature cards with sibling img/heading inside each card wrapper should align."""
    html = _wrap(
        """
        <section>
          <h1>Page Title</h1>
          <img src="/site-logo.png" alt="Logo">
          <div class="features">
            <div>
              <img src="/speed.svg"><h3>Speed</h3><p>Fast.</p>
            </div>
            <div>
              <img src="/safety.svg"><h3>Safety</h3><p>Secure.</p>
            </div>
            <div>
              <img src="/simplicity.svg"><h3>Simplicity</h3><p>Easy.</p>
            </div>
          </div>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)

    content = sections[0]["content"]
    assert content["headings"] == ["Speed", "Safety", "Simplicity"]
    assert [img["src"] for img in content["images"]] == [
        "https://example.com/speed.svg",
        "https://example.com/safety.svg",
        "https://example.com/simplicity.svg",
    ]


def test_anchor_gallery_falls_back_to_alt_text_when_no_per_card_headings():
    """Plain anchor-wrapped image galleries (no per-card headings) use alt text.

    Regression guard: ``_find_cards_by_heading`` returns nothing for a pure
    gallery, so the fallback path that treats each ``<a>`` as a card must
    still produce aligned per-image entries.
    """
    html = _wrap(
        """
        <section>
          <h2>Portfolio</h2>
          <a href="/full-1.jpg"><img src="/thumb-1.jpg" alt="Shot One"></a>
          <a href="/full-2.jpg"><img src="/thumb-2.jpg" alt="Shot Two"></a>
          <a href="/full-3.jpg"><img src="/thumb-3.jpg" alt="Shot Three"></a>
          <a href="/full-4.jpg"><img src="/thumb-4.jpg" alt="Shot Four"></a>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)

    assert sections[0]["type"] == "gallery"
    content = sections[0]["content"]
    assert [img["src"] for img in content["images"]] == [
        "https://example.com/thumb-1.jpg",
        "https://example.com/thumb-2.jpg",
        "https://example.com/thumb-3.jpg",
        "https://example.com/thumb-4.jpg",
    ]
    assert content["headings"] == [
        "Shot One",
        "Shot Two",
        "Shot Three",
        "Shot Four",
    ]


def test_rescoping_only_applies_to_card_like_section_types():
    """Non-card sections (e.g. bio) should keep the flat extraction untouched."""
    html = _wrap(
        """
        <section>
          <img src="/headshot.jpg" alt="Founder">
          <h2>About the Founder</h2>
          <p>Started the company in 2015.</p>
          <p>Designs for clients across the country.</p>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)

    assert sections[0]["type"] == "bio"
    content = sections[0]["content"]
    # Flat extraction preserved — single image, single heading, two paragraphs
    assert len(content["images"]) == 1
    assert content["images"][0]["src"] == "https://example.com/headshot.jpg"


def test_blog_cards_without_per_card_buttons_preserve_alignment():
    """Cards missing button slots emit None placeholders so remaining buttons stay aligned.

    Card 1 has no button, card 2 has "Read More". The overrides mapper must
    still associate the button with card 2 (button_2), not card 1, so the
    template doesn't render a stray "Read More" on the first post card.
    """
    # Preceding hero section prevents the cards section from being is_first,
    # which would otherwise trigger the hero classifier and skip card rescoping.
    html = _wrap(
        """
        <section>
          <h1>Welcome</h1>
          <a class="btn" href="/start">Get Started</a>
        </section>
        <section>
          <article>
            <img src="/p1.jpg"><h3>Post One</h3><p>No button here.</p>
          </article>
          <article>
            <img src="/p2.jpg"><h3>Post Two</h3><p>Has a button.</p>
            <a class="btn" href="/post/2">Read More</a>
          </article>
          <article>
            <img src="/p3.jpg"><h3>Post Three</h3><p>Also no button.</p>
          </article>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)

    assert sections[1]["type"] == "cards"
    buttons = sections[1]["content"]["buttons"]
    assert buttons[0] is None
    assert buttons[1] == {
        "text": "Read More",
        "href": "https://example.com/post/2",
    }
    assert buttons[2] is None


# ---------------------------------------------------------------------------
# Wrapper descent (_top_level_sections via extract_sections)
# ---------------------------------------------------------------------------


def test_webforms_form_wrapper_yields_per_section_output():
    """ASP.NET pages wrap the whole body in <form>; sections must still split."""
    html = (
        "<!doctype html><html><body>"
        '<form id="Form" method="post">'
        '<input type="hidden" name="__VIEWSTATE" value="x">'
        '<div class="page-wrap">'
        "<section><h1>Big Welcome</h1><p>Intro paragraph.</p>"
        '<a class="btn" href="/start">Start</a></section>'
        "<section><h2>Get In Touch</h2><form><input type=\"text\" name=\"name\">"
        '<input type="email" name="email"><textarea name="m"></textarea>'
        "<button type=\"submit\">Send</button></form></section>"
        "</div></form></body></html>"
    )

    sections = extract_sections(html, BASE_URL)

    assert len(sections) == 2
    assert sections[0]["type"] == "hero"
    assert sections[1]["type"] == "contact"


def test_deep_single_wrapper_chain_descends_to_content():
    """div > div > main chains collapse to the real section list."""
    html = (
        "<!doctype html><html><body><div><div>"
        "<section><h1>Hello There</h1><p>One.</p><a class=\"btn\" href=\"/go\">Go</a></section>"
        "<section><h2>Stats</h2><p>10+ years</p><p>200 clients</p><p>99% uptime</p></section>"
        "</div></div></body></html>"
    )

    sections = extract_sections(html, BASE_URL)

    assert len(sections) >= 2
    assert sections[0]["type"] == "hero"


def test_page_header_and_footer_sections_are_excluded():
    """In-page chrome is supplied by global block wrapping — never as sections."""
    html = _wrap(
        """
        <header><img src="/logo.png" alt="Logo"><nav><a href="/a">A</a></nav></header>
        <section><h1>Main Headline</h1><p>Body text here.</p>
        <a class="btn" href="/cta">CTA</a></section>
        <footer><p>© 2026 Example</p><a href="/privacy">Privacy</a></footer>
        """
    )

    sections = extract_sections(html, BASE_URL)

    assert len(sections) == 1
    assert sections[0]["type"] == "hero"


def test_dnn_chrome_siblings_with_dominant_content_pane():
    """DNN layout: header/footer siblings + one content pane holding all the
    real sections. The pane must split; chrome must be excluded."""
    html = (
        "<!doctype html><html><body>"
        '<form id="Form"><div class="aspNetHidden">'
        '<input type="hidden" name="__VIEWSTATE" value="x"></div>'
        '<div class="dnngo-main"><div id="dnn_wrapper">'
        '<header class="header_bg"><img src="/logo.png" alt="Logo">'
        '<nav><a href="/a">A</a><a href="/b">B</a></nav></header>'
        '<section id="dnn_content">'
        '<div class="TopOutPane"><h1>Welcome to the Site</h1>'
        "<p>We build great websites for you.</p>"
        '<a class="btn" href="/start">Get Started</a></div>'
        '<div class="dnn_layout clearfix"><h2>Our Prices</h2>'
        "<p>$99 Website Only plan with hosting.</p>"
        "<p>$249 Branding Package with logo design.</p>"
        "<p>$10 monthly maintenance plan included.</p></div>"
        "</section>"
        '<footer class="footer_box"><p>© 2026 Example Co</p></footer>'
        "</div></div></form></body></html>"
    )

    sections = extract_sections(html, BASE_URL)

    types = [s["type"] for s in sections]
    assert "header" not in types and "footer" not in types
    assert len(sections) == 2
    assert sections[0]["type"] == "hero"
    assert "Welcome to the Site" in sections[0]["content"]["headings"]
    assert "Our Prices" in sections[1]["content"]["headings"]


# ---------------------------------------------------------------------------
# Section background extraction
# ---------------------------------------------------------------------------

SECTION_BG_CSS = """
.dark-band { background-color: #640f0d; color: #ffffff; }
.btn { background: #20a3f0; }
"""


def test_css_background_resolves_onto_section():
    html = _wrap(
        """
        <section class="dark-band">
          <h2>Get started on your website today!</h2>
          <p>Call us now to begin.</p>
          <a class="btn" href="/contact">Contact</a>
        </section>
        <section>
          <h2>Plain Section</h2><p>No background here.</p>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL, css_text=SECTION_BG_CSS)

    assert sections[0]["content"]["background_color"] == "#640f0d"
    assert sections[0]["content"]["text_color"] == "#ffffff"
    assert "background_color" not in sections[1]["content"]


def test_button_background_does_not_leak_to_section():
    html = _wrap(
        """
        <section>
          <h2>Heading Here</h2><p>Some content text for this section.</p>
          <a class="btn" href="/go">Go</a>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL, css_text=SECTION_BG_CSS)

    assert "background_color" not in sections[0]["content"]


def test_inline_style_background_wins():
    html = _wrap(
        """
        <section style="background-color: #111111">
          <h2>Inline Styled</h2><p>Content.</p>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL, css_text=SECTION_BG_CSS)

    assert sections[0]["content"]["background_color"] == "#111111"


def test_background_on_inner_band_wrapper_is_found():
    """Backgrounds often sit on an inner full-width band div, not the pane."""
    html = _wrap(
        """
        <div class="pane">
          <div class="dark-band">
            <h2>Banded Content</h2><p>Lots of text living inside the band.</p>
          </div>
        </div>
        <section><h2>Sibling</h2><p>Keeps this from being one section.</p></section>
        """
    )

    sections = extract_sections(html, BASE_URL, css_text=SECTION_BG_CSS)

    banded = next(s for s in sections if "Banded Content" in s["content"]["headings"])
    assert banded["content"]["background_color"] == "#640f0d"


def test_white_and_transparent_backgrounds_are_dropped():
    """Page-default backgrounds add style noise without visual value."""
    css = ".pane { background: #FFF; } .clear { background-color: transparent; }"
    html = _wrap(
        """
        <div class="pane"><h2>White Pane</h2><p>Content text.</p></div>
        <div class="clear"><h2>Clear Pane</h2><p>More text.</p></div>
        """
    )

    sections = extract_sections(html, BASE_URL, css_text=css)

    for section in sections:
        assert "background_color" not in section["content"]


def test_rendered_dom_attributes_resolve_backgrounds_and_image():
    """Rendered crawls stamp data-migrate-* attrs directly — no CSS needed."""
    html = _wrap(
        """
        <section data-migrate-bg="rgb(100, 15, 13)" data-migrate-color="rgb(255, 255, 255)"
                 data-migrate-bg-image="/images/blueprint.jpg">
          <h2>Each Website Includes</h2><p>Checklist content here.</p>
        </section>
        <section data-migrate-bg="rgb(255, 255, 255)">
          <h2>White Section</h2><p>Default background must be dropped.</p>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)

    assert sections[0]["content"]["background_color"] == "rgb(100, 15, 13)"
    assert sections[0]["content"]["text_color"] == "rgb(255, 255, 255)"
    assert sections[0]["content"]["background_image"] == "https://example.com/images/blueprint.jpg"
    assert "background_color" not in sections[1]["content"]


def test_collect_image_urls_includes_background_images():
    sections = [
        {"content": {"images": [{"src": "https://example.com/a.jpg"}],
                     "background_image": "https://example.com/band.jpg"}},
    ]

    urls = collect_image_urls(sections)

    assert "https://example.com/band.jpg" in urls


def test_dominance_ignores_chrome_text_in_denominator():
    """Rendered DOMs duplicate nav text in mobile menus; chrome text must not
    keep the content pane below the expansion threshold."""
    nav_links = "".join(f'<a href="/p{i}">Menu Item Number {i}</a>' for i in range(20))
    html = (
        "<!doctype html><html><body><div><div>"
        f'<header class="header_bg"><img src="/logo.png" alt="L"><nav>{nav_links}</nav></header>'
        f'<div class="mobile_header visible-xs">{nav_links}</div>'
        '<section id="dnn_content">'
        '<div class="TopOutPane"><h1>Welcome Headline</h1><p>Intro paragraph text.</p>'
        '<a class="btn" href="/go">Go</a></div>'
        '<div class="dnn_layout clearfix"><h2>Second Band</h2><p>More content text.</p></div>'
        "</section>"
        '<footer class="footer_box"><p>© 2026</p></footer>'
        "</div></div></body></html>"
    )

    sections = extract_sections(html, BASE_URL)

    types = [s["type"] for s in sections]
    assert "header" not in types and "footer" not in types
    assert len(sections) == 2
    assert "Welcome Headline" in sections[0]["content"]["headings"]
    assert "Second Band" in sections[1]["content"]["headings"]


def test_js_injected_body_siblings_do_not_block_descent():
    """Offcanvas menus injected at body level defeat the single-wrapper chain;
    the dominant form must still unwrap down to the real sections."""
    html = (
        "<!doctype html><html><body>"
        '<div class="mobile_menu mm-menu"><a href="/a">A</a><a href="/b">B</a></div>'
        '<form id="Form" class="mm-page">'
        '<div class="dnngo-main"><div id="dnn_wrapper">'
        '<header class="header_bg"><img src="/logo.png" alt="L"></header>'
        '<section id="dnn_content">'
        '<div class="TopOutPane"><h1>Main Headline</h1><p>Intro text here.</p>'
        '<a class="btn" href="/go">Go</a></div>'
        '<div class="dnn_layout clearfix"><h2>Second Band</h2><p>Band content text.</p></div>'
        "</section>"
        '<footer class="footer_box"><p>© 2026</p></footer>'
        "</div></div></form>"
        '<div id="overlay_right">x</div>'
        "</body></html>"
    )

    sections = extract_sections(html, BASE_URL)

    headings = [h for s in sections for h in s["content"].get("headings", [])]
    assert "Main Headline" in headings
    assert "Second Band" in headings
    types = [s["type"] for s in sections]
    assert "header" not in types and "footer" not in types


# ---------------------------------------------------------------------------
# _find_sibling_card_group: deep card grids under CMS wrapper markup
# ---------------------------------------------------------------------------


def test_deeply_nested_image_heading_grid_classifies_as_gallery():
    """Same-class sibling blocks with img + heading buried under module chrome."""
    items = "".join(
        f'<div class="element sc-element"><img src="/work/{n}.jpg" alt="">'
        f"<h4>Project {n}</h4></div>"
        for n in range(1, 5)
    )
    html = _wrap(
        f"""
        <section>
          <div class="DnnModule"><div class="contentpane">
            <div class="portfolio-grid">{items}</div>
          </div></div>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)

    assert len(sections) == 1
    assert sections[0]["type"] == "gallery"
    content = sections[0]["content"]
    assert content["headings"] == [f"Project {n}" for n in range(1, 5)]
    assert [i["src"] for i in content["images"]] == [
        f"{BASE_URL}work/{n}.jpg" for n in range(1, 5)
    ]


def test_imageless_icon_card_row_classifies_as_cards():
    """Icon-font feature columns (heading + text, no <img>) are still cards."""
    cols = "".join(
        f'<div class="col-sm-4 sc-elem"><i class="icon-star"></i>'
        f"<h3>Benefit {n}</h3><p>Why benefit {n} matters.</p></div>"
        for n in range(1, 4)
    )
    html = _wrap(
        f"""
        <section>
          <div class="container"><div class="row">{cols}</div></div>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)

    assert len(sections) == 1
    assert sections[0]["type"] == "cards"
    content = sections[0]["content"]
    assert content["headings"] == ["Benefit 1", "Benefit 2", "Benefit 3"]
    assert content["paragraphs"] == [f"Why benefit {n} matters." for n in range(1, 4)]


def test_headingless_image_strip_does_not_classify_as_cards():
    """Badge/logo rows (images only, no headings) must not become galleries."""
    badges = "".join(
        f'<div class="col col-sm-4"><img src="/badge{n}.png" alt=""></div>'
        for n in range(1, 4)
    )
    html = _wrap(
        f"""
        <section>
          <div class="wrap"><div class="row">{badges}</div></div>
          <p>Proud members of these organizations.</p>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)

    assert len(sections) == 1
    assert sections[0]["type"] not in ("cards", "gallery")


def test_article_body_with_repeated_headings_stays_content():
    """Free-flowing article markup (headings not wrapped in sibling cards)."""
    body = "".join(
        f"<h2>Subhead {n}</h2><p>Paragraph for subhead {n}.</p>" for n in range(1, 5)
    )
    html = _wrap(f'<section><div class="article-body">{body}</div></section>')

    sections = extract_sections(html, BASE_URL)

    assert len(sections) == 1
    assert sections[0]["type"] == "content"


# ---------------------------------------------------------------------------
# layout bands must split apart (not read as uniform card grids)
# ---------------------------------------------------------------------------


def test_repeated_layout_bands_split_into_sections():
    """DNN layout bands sharing a class are sections, not a card grid."""
    html = _wrap(
        """
        <header class="header_bg"><img src="/logo.png" alt="logo"></header>
        <section>
          <div class="dnn_layout clearfix"><div class="row"><div class="col-sm-12">
            <h2>Websites from Concept to Creation</h2>
            <p>The foundation for your business is a well-designed site with plenty of explanatory text to carry weight.</p>
          </div></div></div>
          <div class="Full_Screen_PaneE"><div class="DnnModule"><div class="White">
            <h2>Each Website Includes</h2>
            <ul><li>Hosting</li><li>Design</li><li>SEO</li></ul>
          </div></div></div>
          <div class="dnn_layout clearfix"><div class="row"><div class="col-sm-12">
            <h2>Our Prices</h2>
            <p>Website Only and Branding Package plans with long descriptive copy for each plan offered here.</p>
          </div></div></div>
        </section>
        <footer class="footer_box"><p>Copyright</p></footer>
        """
    )

    sections = extract_sections(html, BASE_URL)

    assert len(sections) == 3
    first_headings = [s["content"]["headings"][0] for s in sections]
    assert first_headings == [
        "Websites from Concept to Creation",
        "Each Website Includes",
        "Our Prices",
    ]


def test_uniform_card_grid_still_not_split():
    """A real card grid (uniform col children) stays one section."""
    cards = "".join(
        f'<div class="col-md-4 feature"><h3>Card {n}</h3><p>Text {n}.</p></div>'
        for n in range(1, 4)
    )
    html = _wrap(f'<section><div class="cards">{cards}</div></section>')

    sections = extract_sections(html, BASE_URL)

    assert len(sections) == 1
    assert len(sections[0]["content"]["headings"]) == 3


# ---------------------------------------------------------------------------
# hidden-content stripping (rendered crawl visibility + aria-hidden)
# ---------------------------------------------------------------------------


def test_hidden_stamped_subtrees_are_dropped():
    """data-migrate-hidden subtrees (inactive tab panes) never extract."""
    html = _wrap(
        """
        <section>
          <h2>What Clients Say</h2>
          <div class="tab-pane active"><p>Visible testimonial quote.</p></div>
          <div class="tab-pane" data-migrate-hidden="1">
            <p>Hidden testimonial one with a very long body.</p>
            <p>Hidden testimonial two with a very long body.</p>
          </div>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)

    assert len(sections) == 1
    paragraphs = sections[0]["content"]["paragraphs"]
    assert paragraphs == ["Visible testimonial quote."]


def test_aria_hidden_subtrees_are_dropped():
    """aria-hidden carousel clones never extract."""
    html = _wrap(
        """
        <section>
          <h2>Recent Posts</h2>
          <div class="owl-item"><h3>Post One</h3><p>Excerpt one.</p></div>
          <div class="owl-item cloned" aria-hidden="true"><h3>Post One</h3><p>Excerpt one.</p></div>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)

    assert len(sections) == 1
    content = sections[0]["content"]
    assert content["headings"] == ["Recent Posts", "Post One"]
    assert content["paragraphs"] == ["Excerpt one."]


def test_global_element_carries_band_colors():
    """Header/footer extraction picks up rendered-crawl background stamps."""
    html = (
        "<!doctype html><html><body>"
        '<header class="header_bg" data-migrate-bg="rgb(20, 20, 20)" data-migrate-color="rgb(255, 255, 255)">'
        '<img src="/logo.png" alt="Logo"><ul><li><a href="/">Home</a></li></ul>'
        "</header>"
        "<main><section><h1>Body</h1><p>Text</p></section></main>"
        "</body></html>"
    )

    result = extract_global_element(html, BASE_URL, "header")

    assert result is not None
    assert result["content"]["background_color"] == "rgb(20, 20, 20)"
    assert result["content"]["text_color"] == "rgb(255, 255, 255)"


def test_multi_element_text_keeps_separators():
    """Stacked spans/lines inside one element must not concatenate run-on."""
    html = _wrap(
        """
        <section>
          <h2><span>NEED TO TALK TO SOMEONE?</span><span>GIVE US A CALL</span></h2>
          <p><strong>What is the newest update?</strong>Google Chrome flags HTTP pages.</p>
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)

    content = sections[0]["content"]
    assert content["headings"][0] == "NEED TO TALK TO SOMEONE? GIVE US A CALL"
    assert content["paragraphs"][0] == "What is the newest update? Google Chrome flags HTTP pages."


def test_article_body_with_featured_image_is_not_bio():
    """A full article (1 image + many long paragraphs) must stay content."""
    paragraphs = "".join(
        f"<p>Paragraph {n} of the article body, long enough that the page is "
        f"clearly a written article and not a short about-us blurb at all.</p>"
        for n in range(1, 9)
    )
    html = _wrap(
        f"""
        <section>
          <h1>It's Time to Get Serious About Security</h1>
          <img src="/security-promo.jpg" alt="Security">
          {paragraphs}
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)

    assert sections[0]["type"] == "content"


def test_footer_extraction_captures_social_and_copyright():
    html = (
        "<!doctype html><html><body><main><section><h1>Body</h1><p>Text</p></section></main>"
        '<footer class="footer_box">'
        '<a href="https://www.facebook.com/cmw"><i class="fa-facebook"></i></a>'
        '<a href="https://twitter.com/cmw"><i class="fa-twitter"></i></a>'
        '<span class="footer">Copyright 2026 by Clicks &amp; Mortar Websites</span>'
        "</footer></body></html>"
    )

    result = extract_global_element(html, BASE_URL, "footer")

    content = result["content"]
    assert content["social_links"] == [
        {"label": "Facebook", "href": "https://www.facebook.com/cmw"},
        {"label": "Twitter", "href": "https://twitter.com/cmw"},
    ]
    assert content["copyright_text"] == "Copyright 2026 by Clicks & Mortar Websites"


def test_post_body_gains_date_and_tag_meta_line():
    """Blog byline (detail-date + label spans) leads the content paragraphs."""
    paragraphs = "".join(
        f"<p>Paragraph {n} of the security article, long enough to keep this "
        f"section out of the bio classification path entirely.</p>"
        for n in range(1, 8)
    )
    html = _wrap(
        f"""
        <section>
          <div class="detail-date">21 Sep</div>
          <span class="label label-default">Website Security</span>
          <span class="label label-default">Website Updates</span>
          <h1>It's Time to Get Serious About Security</h1>
          {paragraphs}
        </section>
        """
    )

    sections = extract_sections(html, BASE_URL)

    assert sections[0]["type"] == "content"
    assert sections[0]["content"]["paragraphs"][0] == "21 Sep — Website Security, Website Updates"


def test_sections_without_byline_markup_are_unchanged():
    html = _wrap("<section><h2>About</h2><p>First paragraph.</p><p>Second one.</p><p>Third paragraph here to avoid bio.</p></section>")

    sections = extract_sections(html, BASE_URL)

    assert sections[0]["content"]["paragraphs"][0] == "First paragraph."
