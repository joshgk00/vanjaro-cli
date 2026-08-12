"""Focused contracts for static HTML boundary and relationship recovery."""

from __future__ import annotations

from bs4 import BeautifulSoup

from vanjaro_cli.design.html_boundaries import (
    append_missing_video_sections,
    enrich_faq_relationships,
    prepare_static_sections,
    static_boundary_candidates,
    static_role,
    unclaimed_boundaries,
)


def test_static_boundaries_require_stable_navigation_and_preserve_order() -> None:
    html = """
    <html><body>
      <nav><a href='/ignored'>Incidental</a></nav>
      <header id='site-header'><nav>
        <a href='/'>Home</a><a href='/about'>About</a>
      </nav></header>
      <main>
        <section id='hero'><h1>Welcome</h1></section>
        <section id='stats'><ul><li><strong>10</strong><span>Clients</span></li>
          <li><strong>20</strong><span>Projects</span></li></ul></section>
      </main>
    </body></html>
    """

    assert [tag.get("id") for tag in static_boundary_candidates(html)] == [
        "site-header",
        "hero",
        "stats",
    ]


def test_prepare_static_sections_attaches_navigation_roles_and_provenance() -> None:
    html = """
    <header id='header'><nav><a href='/'>Home</a><a href='/work'>Work</a></nav></header>
    <main>
      <section id='hero'><h1>Build better sites</h1><p>Agency introduction</p></section>
      <section id='testimonials'><blockquote>Excellent work</blockquote></section>
    </main>
    """
    legacy = [
        {"type": "hero", "content": {"headings": ["Build better sites"], "paragraphs": ["Agency introduction"]}},
        {"type": "testimonial", "content": {"paragraphs": ["Excellent work"]}},
    ]

    prepared = prepare_static_sections(html, legacy)

    assert [section["_static_role"] for section in prepared] == [
        "navigation",
        "hero",
        "testimonials",
    ]
    assert [section["_static_selector"] for section in prepared] == [
        "#header",
        "#hero",
        "#testimonials",
    ]


def test_faq_and_media_only_relationship_repair_is_source_faithful() -> None:
    html = """
    <section id='faq'>
      <details><summary>Question one?</summary><p>Answer one.</p></details>
      <details><summary>Question two?</summary><p>Answer two.</p></details>
    </section>
    <section><video><source src='/media/intro.mp4'></video></section>
    <section><iframe src='https://www.youtube.com/embed/example'></iframe></section>
    """
    sections = [{
        "type": "faq",
        "content": {"headings": ["FAQ"], "paragraphs": []},
    }]

    enrich_faq_relationships(html, sections)
    append_missing_video_sections(html, "https://agency.example/home", sections)

    assert sections[0]["content"]["headings"] == [
        "FAQ",
        "Question one?",
        "Question two?",
    ]
    assert sections[0]["content"]["paragraphs"] == ["Answer one.", "Answer two."]
    assert sections[1]["content"]["videos"] == [
        {"type": "native", "src": "https://agency.example/media/intro.mp4"},
        {"type": "embed", "src": "https://www.youtube.com/embed/example"},
    ]


def _role(markup: str, index: int = 2) -> str:
    element = BeautifulSoup(markup, "html.parser").find(["section", "div"])
    return static_role(element, index)


def test_one_pull_quote_beside_photographs_is_not_testimonials() -> None:
    """A page carrying a single quote among six photographs read as a quote grid
    and lost the photographs, the copy and every link. `_classify_section` has
    always required quotes to be the point; this rule used to override it."""

    role = _role(
        "<section><h2>Lighting</h2>"
        "<blockquote><h3>A line worth quoting</h3><footer><cite>A Poet</cite></footer></blockquote>"
        "<img src='/one.jpg'><img src='/two.jpg'><p>Copy about lighting.</p></section>"
    )

    assert role != "testimonials"


def test_several_quotes_are_still_testimonials() -> None:
    """The guard must not swallow the real thing: a wall of quotes is what the
    role is for, pictures or no pictures."""

    role = _role(
        "<section><h2>What clients say</h2>"
        "<blockquote>First.</blockquote><blockquote>Second.</blockquote>"
        "<img src='/portrait.jpg'></section>"
    )

    assert role == "testimonials"


def test_a_lone_quote_with_nothing_competing_is_testimonials() -> None:
    """One quote and no imagery is a quote section, which is the other half of
    the rule `_classify_section` has always applied."""

    role = _role("<section><h2>Praise</h2><blockquote>The only quote.</blockquote></section>")

    assert role == "testimonials"


def test_a_section_that_calls_itself_a_testimonial_is_believed() -> None:
    """The author's own word outranks the inference, however much else is on the
    page."""

    role = _role(
        "<section class='testimonial-band'><h2>Voices</h2>"
        "<blockquote>Only one.</blockquote><img src='/a.jpg'><img src='/b.jpg'></section>"
    )

    assert role == "testimonials"


_TWO_PANES = (
    "<header id='header'><nav><a href='/'>Home</a><a href='/work'>Work</a></nav></header>"
    "<div id='dnn_wrapper'>"
    "  <div id='dnn_TopPane' class='Pane'><h1>Contact Us</h1><p>Ask us anything.</p></div>"
    "  <div id='dnn_SidePane' class='Pane'><h2>Give us a call</h2>"
    "    <address>PO Box 773</address><a href='tel:+1'>Call now</a></div>"
    "</div>"
)
_ONLY_THE_FIRST_PANE = [
    {"type": "rich_text", "content": {"headings": ["Contact Us"], "paragraphs": ["Ask us anything."]}},
]


def test_a_boundary_no_section_claimed_is_reported() -> None:
    dropped = unclaimed_boundaries(_TWO_PANES, _ONLY_THE_FIRST_PANE)

    assert [tag.get("id") for tag in dropped] == ["dnn_SidePane"]


def test_a_claimed_boundary_is_not_reported() -> None:
    claimed = [
        *_ONLY_THE_FIRST_PANE,
        {
            "type": "rich_text",
            "content": {"headings": ["Give us a call"], "list_items": ["PO Box 773"]},
        },
    ]

    assert unclaimed_boundaries(_TWO_PANES, claimed) == []


def test_unclaimed_chrome_is_not_reported_because_it_is_appended_anyway() -> None:
    """The header matches no raw section here, and `prepare_static_sections`
    appends it regardless — so reporting it would name content that arrives."""

    dropped = unclaimed_boundaries(_TWO_PANES, _ONLY_THE_FIRST_PANE)
    prepared = prepare_static_sections(_TWO_PANES, _ONLY_THE_FIRST_PANE)

    assert "header" not in {tag.name for tag in dropped}
    assert "navigation" in {section.get("_static_role") for section in prepared}


def test_an_empty_boundary_is_not_reported_as_dropped_content() -> None:
    html = _TWO_PANES.replace(
        "<h2>Give us a call</h2>"
        "    <address>PO Box 773</address><a href='tel:+1'>Call now</a>",
        "",
    )

    assert unclaimed_boundaries(html, _ONLY_THE_FIRST_PANE) == []


_BANNER_PAGE = (
    "<header id='header'><nav><a href='/'>Home</a><a href='/work'>Work</a></nav></header>"
    "<div id='dnn_BannerPane' class='Pane'><img src='/Portals/0/banner.jpg'></div>"
    "<div id='dnn_TopPane' class='Pane'><h1>Contact Us</h1><p>Ask us anything.</p></div>"
)


def test_a_section_of_pure_imagery_pairs_by_picture_not_by_document_order() -> None:
    """Promoting a leading image-only pane to a hero background leaves a section
    with no words at all, so every candidate scored zero and the pairing fell to
    document order — handing the banner to the header, whose chrome role then
    replaced the section outright."""

    promoted_banner = {
        "type": "hero",
        "content": {"background_image": "https://example.invalid/Portals/0/banner.jpg"},
    }
    copy = {"type": "content", "content": {"headings": ["Contact Us"], "paragraphs": ["Ask us anything."]}}

    prepared = prepare_static_sections(_BANNER_PAGE, [promoted_banner, copy])

    assert [section.get("_static_selector") for section in prepared] == [
        "#header",
        "#dnn_BannerPane",
        "#dnn_TopPane",
    ]
    assert [section.get("_static_role") for section in prepared] == [
        "navigation",
        "photo_band",
        "rich_text",
    ]


def test_a_section_sharing_nothing_claims_nothing() -> None:
    """A section wearing a stranger's DOM is worse than a section keeping its
    own content: enrichment rebuilds content from the claimed subtree."""

    stranger = {"type": "content", "content": {"paragraphs": ["Entirely unrelated copy here."]}}

    prepared = prepare_static_sections(_BANNER_PAGE, [stranger])

    kept = [section for section in prepared if section.get("type") == "content"]
    assert kept[0].get("_static_selector") is None
    assert kept[0]["content"]["paragraphs"] == ["Entirely unrelated copy here."]


def test_a_page_section_sharing_a_word_with_the_nav_does_not_become_the_nav() -> None:
    """A site's footer block repeats the phone number its header carries. That
    single shared token was enough to claim the header, and claiming chrome
    replaces the section with chrome — which cost wwo its tagline, email and
    telephone."""

    footer_copy = {
        "type": "content",
        "content": {
            "paragraphs": ["We make easy and affordable websites for small businesses."],
            "links": ["(248) 690-6559"],
        },
    }
    page = _BANNER_PAGE.replace(
        "<a href='/work'>Work</a>", "<a href='/work'>Work</a><span>(248) 690-6559</span>"
    )

    prepared = prepare_static_sections(page, [footer_copy])

    kept = [section for section in prepared if section.get("type") == "content"]
    assert kept[0].get("_static_role") != "navigation"
    assert kept[0]["content"]["paragraphs"] == [
        "We make easy and affordable websites for small businesses."
    ]


def test_a_section_that_is_the_nav_still_claims_it() -> None:
    """Withholding the header entirely is the other failure: the section then
    goes looking for another subtree, which is how a header came to wear the
    footer's DOM."""

    nav_section = {"type": "navigation", "content": {"links": ["Home", "Work"]}}

    prepared = prepare_static_sections(_BANNER_PAGE, [nav_section])

    assert [section.get("_static_role") for section in prepared] == ["navigation"]
    assert prepared[0]["_static_selector"] == "#header"


def test_words_decide_before_pictures() -> None:
    """Pictures break ties; they do not overrule copy. A section whose words
    belong to one pane and whose stock photograph also appears in another must
    follow its words."""

    page = (
        "<div id='dnn_TextPane' class='Pane'><h2>Our Services</h2>"
        "<p>Lighting, patios and plantings.</p></div>"
        "<div id='dnn_PhotoPane' class='Pane'><img src='/Portals/0/shared.jpg'></div>"
    )
    section = {
        "type": "content",
        "content": {
            "headings": ["Our Services"],
            "paragraphs": ["Lighting, patios and plantings."],
            "images": [{"src": "https://example.invalid/Portals/0/shared.jpg"}],
        },
    }

    prepared = prepare_static_sections(page, [section])

    assert prepared[0]["_static_selector"] == "#dnn_TextPane"


def test_an_asset_reference_is_compared_as_a_path_not_as_a_string() -> None:
    """The raw section carries the URL resolved against the page and the DOM
    carries it as authored, so a cache-busting query alone would leave a banner
    matching nothing."""

    page = (
        "<div id='dnn_BannerPane' class='Pane'><img src='/Portals/0/banner.jpg'></div>"
        "<div id='dnn_TopPane' class='Pane'><h1>Contact Us</h1><p>Ask us anything.</p></div>"
    )
    banner = {
        "type": "hero",
        "content": {"background_image": "https://example.invalid/Portals/0/banner.jpg?v=2"},
    }

    prepared = prepare_static_sections(page, [banner])

    assert prepared[0]["_static_selector"] == "#dnn_BannerPane"


def test_one_filename_ending_inside_another_is_not_the_same_picture() -> None:
    """`xbanner.jpg` ends with `banner.jpg`. Without a path boundary the two
    read as one asset and a section pairs with the wrong pane."""

    page = (
        "<div id='dnn_FirstPane' class='Pane'><img src='/Portals/0/banner.jpg'></div>"
        "<div id='dnn_SecondPane' class='Pane'><img src='/Portals/0/xbanner.jpg'></div>"
    )
    section = {"type": "content", "content": {"images": [{"src": "xbanner.jpg"}]}}

    prepared = prepare_static_sections(page, [section])

    assert prepared[0]["_static_selector"] == "#dnn_SecondPane"


def test_a_section_with_no_words_cannot_claim_the_chrome_by_sharing_a_logo() -> None:
    """A header carries the site logo and so does the banner beneath it. With
    only pictures to go on the two tie, and the tie-break prefers the earlier
    candidate — which is the header, whose chrome role then replaces the
    section. A section that says nothing is not the nav."""

    page = (
        "<header id='header'><nav><a href='/'><img src='/Portals/0/logo.png'>Home</a>"
        "<a href='/work'>Work</a></nav></header>"
        "<div id='dnn_BannerPane' class='Pane'><img src='/Portals/0/logo.png'></div>"
    )
    wordless = {
        "type": "hero",
        "content": {"background_image": "https://example.invalid/Portals/0/logo.png"},
    }

    prepared = prepare_static_sections(page, [wordless])

    assert [section.get("_static_selector") for section in prepared] == [
        "#header",
        "#dnn_BannerPane",
    ]
    assert prepared[1]["_static_role"] == "photo_band"


def test_a_relative_filename_matches_on_a_path_boundary() -> None:
    """`hero-banner.jpg` ends with `banner.jpg`. Matching on the bare suffix
    pairs the section with whichever pane comes first."""

    page = (
        "<div id='dnn_FirstPane' class='Pane'><img src='/Portals/0/hero-banner.jpg'></div>"
        "<div id='dnn_SecondPane' class='Pane'><img src='/Portals/0/banner.jpg'></div>"
    )
    section = {"type": "content", "content": {"images": [{"src": "banner.jpg"}]}}

    prepared = prepare_static_sections(page, [section])

    assert prepared[0]["_static_selector"] == "#dnn_SecondPane"


def test_a_video_pairs_the_same_way_a_picture_does() -> None:
    """`append_missing_video_sections` builds sections whose only asset is a
    video, so the raw side must read videos wherever it reads images."""

    page = (
        "<div id='dnn_TextPane' class='Pane'><p>Some unrelated copy.</p></div>"
        "<div id='dnn_MediaPane' class='Pane'><video src='/media/intro.mp4'></video></div>"
    )
    section = {
        "type": "content",
        "content": {"videos": [{"src": "https://example.invalid/media/intro.mp4"}]},
    }

    prepared = prepare_static_sections(page, [section])

    assert prepared[0]["_static_selector"] == "#dnn_MediaPane"


_TWO_CARDS_IN_ONE_PANE = (
    "<div id='dnn_BottomPane' class='Pane'>"
    "<div class='card'><h3>Website Only</h3><ul><li>Unlimited Web Pages</li>"
    "<li>One Add On</li></ul></div>"
    "<div class='card'><h3>Branding Package</h3><ul><li>Logo Design</li>"
    "<li>Business Card Design</li></ul></div>"
    "</div>"
)
_CARD_SECTIONS = [
    {"type": "content", "content": {"headings": ["Website Only"],
                                    "list_items": ["Unlimited Web Pages", "One Add On"]}},
    {"type": "content", "content": {"headings": ["Branding Package"],
                                    "list_items": ["Logo Design", "Business Card Design"]}},
]


def test_a_pane_holding_two_sections_is_claimed_by_neither() -> None:
    """Enrichment rebuilds a claimed section's content from its subtree, so
    pairing a section to the pane that also holds its sibling replaces what the
    extractor read correctly with a flattening of both — wwo's two pricing cards
    became one section with two headings, one paragraph and no prices."""

    prepared = prepare_static_sections(_TWO_CARDS_IN_ONE_PANE, _CARD_SECTIONS)

    assert [section.get("_static_selector") for section in prepared] == [None, None]
    assert prepared[0]["content"]["list_items"] == ["Unlimited Web Pages", "One Add On"]
    assert prepared[1]["content"]["list_items"] == ["Logo Design", "Business Card Design"]


def test_a_pane_holding_one_section_is_still_claimed() -> None:
    """The rule withholds containers, not panes. Withholding every pane would
    cost every section its role, its selector and its rendered pairing."""

    prepared = prepare_static_sections(_TWO_CARDS_IN_ONE_PANE, _CARD_SECTIONS[:1])

    assert prepared[0]["_static_selector"] == "#dnn_BottomPane"


def test_sections_with_no_words_do_not_make_every_pane_a_container() -> None:
    """An empty set is a subset of everything. Counting wordless sections would
    make two image-only panes turn every boundary on the page into a container
    and unclaim the entire document."""

    wordless = [
        {"type": "hero", "content": {"background_image": "https://x.invalid/a.jpg"}},
        {"type": "content", "content": {"images": [{"src": "https://x.invalid/b.jpg"}]}},
    ]
    page = (
        "<div id='dnn_BannerPane' class='Pane'><img src='/a.jpg'></div>"
        "<div id='dnn_PhotoPane' class='Pane'><img src='/b.jpg'></div>"
    )

    prepared = prepare_static_sections(page, wordless)

    assert [section.get("_static_selector") for section in prepared] == [
        "#dnn_BannerPane",
        "#dnn_PhotoPane",
    ]
