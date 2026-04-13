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
