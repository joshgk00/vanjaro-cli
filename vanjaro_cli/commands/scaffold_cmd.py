"""vanjaro blocks scaffold — generate GrapesJS component trees from section patterns."""

from __future__ import annotations

import json

import click

from vanjaro_cli.commands.helpers import exit_error, write_output
from vanjaro_cli.utils.grapesjs import create_component

AVAILABLE_SECTIONS = [
    "hero", "hero-simple", "content", "cards-3", "testimonials",
    "bio", "checklist", "cta", "form", "features-4", "program",
]


@click.command("scaffold")
@click.option(
    "--sections", "-s",
    required=True,
    help=f"Comma-separated section types: {', '.join(AVAILABLE_SECTIONS)}",
)
@click.option("--output", "-o", type=click.Path(), default=None, help="Write to file (default: stdout).")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON (always JSON, flag for consistency).")
def scaffold(sections: str, output: str | None, as_json: bool) -> None:
    """Generate a page layout from predefined section patterns.

    Outputs a GrapesJS-compatible JSON file that can be pushed with `content update`.
    """
    section_names = [s.strip() for s in sections.split(",") if s.strip()]
    if not section_names:
        exit_error("No sections specified.", as_json)

    components: list[dict] = []
    styles: list[dict] = []

    for name in section_names:
        builder = SECTION_BUILDERS.get(name)
        if not builder:
            exit_error(
                f"Unknown section type: '{name}'. "
                f"Available: {', '.join(AVAILABLE_SECTIONS)}",
                as_json,
            )
        section_components, section_styles = builder()
        components.append(section_components)
        styles.extend(section_styles)

    payload = json.dumps({"components": components, "styles": styles}, indent=2)

    if output:
        write_output(output, payload, as_json)
        click.echo(f"Layout written to {output} ({len(section_names)} sections)")
    else:
        click.echo(payload)


# ---------------------------------------------------------------------------
# Section builders — each returns (component_dict, styles_list)
# ---------------------------------------------------------------------------


def _text(content: str, extra_classes: list[str] | None = None) -> dict:
    """Build a text component with Vanjaro's required classes."""
    classes = ["vj-text", "text-dark"]
    if extra_classes:
        classes.extend(extra_classes)
    return create_component("text", content=content, classes=classes)


def _heading(content: str, extra_classes: list[str] | None = None) -> dict:
    """Build a heading component with Vanjaro's required classes."""
    classes = ["vj-heading", "heading-style-1"]
    if extra_classes:
        classes.extend(extra_classes)
    return create_component("heading", content=content, classes=classes)


def _button(label: str, extra_classes: list[str] | None = None) -> dict:
    """Build a button component with Vanjaro's required classes."""
    classes = ["btn", "btn-primary", "vj-btn"]
    if extra_classes:
        classes.extend(extra_classes)
    return create_component("button", content=label, classes=classes)


def _make_section(classes: list[str] | None = None, children: list[dict] | None = None) -> dict:
    """Build a section > grid > row wrapper."""
    section_classes = ["vj-section"]
    if classes:
        section_classes.extend(classes)

    return create_component(
        "section",
        classes=section_classes,
        children=[
            create_component("grid", classes=["container"], children=[
                create_component("row", classes=["row"], children=children or []),
            ]),
        ],
    )


def _make_column(width: int = 12, children: list[dict] | None = None) -> dict:
    """Build a responsive column with all Bootstrap breakpoints Vanjaro expects."""
    col_classes = [f"col-xl-{width}", f"col-md-{width}", f"col-sm-{min(width + 2, 12)}", "col-12"]
    return create_component("column", classes=col_classes, children=children or [])


def _build_hero() -> tuple[dict, list[dict]]:
    left = _make_column(6, children=[
        _heading("Welcome to"),
        _heading("Your Site Name"),
        _text("Your tagline or introductory paragraph goes here. Describe what you offer and why visitors should care."),
        _button("Get Started"),
        _button("Learn More", extra_classes=["btn-outline-secondary"]),
    ])
    right = _make_column(6, children=[
        _text("[Image or video placeholder]", extra_classes=["text-center", "p-5"]),
    ])

    section = _make_section(children=[left, right])
    return section, []


def _build_hero_simple() -> tuple[dict, list[dict]]:
    col = _make_column(8, children=[
        _heading("Page Title"),
        _text("Page subtitle or description"),
    ])
    center_row = create_component("row", classes=["row", "justify-content-center"], children=[col])
    section = create_component("section", classes=["vj-section"], children=[
        create_component("grid", classes=["container"], children=[center_row]),
    ])
    return section, []


def _build_content() -> tuple[dict, list[dict]]:
    col = _make_column(8, children=[
        _heading("Section Heading"),
        _text("First paragraph of content. Describe your mission, values, or the topic of this section."),
        _text("Second paragraph with supporting details. Add as much context as needed."),
        _button("Call to Action"),
    ])
    center_row = create_component("row", classes=["row", "justify-content-center"], children=[col])
    section = create_component("section", classes=["vj-section"], children=[
        create_component("grid", classes=["container"], children=[center_row]),
    ])
    return section, []


def _build_cards_3() -> tuple[dict, list[dict]]:
    cards = []
    for i in range(3):
        card = _make_column(4, children=[
            _heading(f"Service {i + 1}"),
            _text("Description of this service or feature. Explain what it includes and why it matters."),
            create_component("link", content="Learn More →"),
        ])
        cards.append(card)

    section = _make_section(children=cards)

    heading = _heading("Our Services")
    section["components"][0]["components"].insert(0,
        create_component("row", classes=["row", "mb-4"], children=[
            _make_column(12, children=[heading]),
        ])
    )
    return section, []


def _build_testimonials() -> tuple[dict, list[dict]]:
    testimonials = []
    names = ["Sarah M.", "Jennifer K.", "Rebecca L."]
    for i, name in enumerate(names):
        card = _make_column(4, children=[
            _text(f'"Your testimonial quote goes here. Share a real success story from a client."'),
            _text(f"— {name}"),
        ])
        testimonials.append(card)

    section = _make_section(children=testimonials)

    heading = _heading("Success Stories")
    section["components"][0]["components"].insert(0,
        create_component("row", classes=["row", "mb-4"], children=[
            _make_column(12, children=[heading]),
        ])
    )
    return section, []


def _build_bio() -> tuple[dict, list[dict]]:
    photo = _make_column(5, children=[
        _text("[Photo placeholder]", extra_classes=["text-center", "p-5"]),
    ])
    text_col = _make_column(7, children=[
        _heading("About the Founder"),
        _heading("Their story matters."),
        _text("Bio paragraph 1 — introduce the person, their background, and what drives them."),
        _text("Bio paragraph 2 — share their qualifications, experience, and personal connection to the work."),
    ])

    section = _make_section(children=[photo, text_col])
    return section, []


def _build_checklist() -> tuple[dict, list[dict]]:
    col = _make_column(8, children=[
        _heading("Are you ready to..."),
        _text("- Take ownership of your future\n- Build healthier relationships\n- Develop emotional resilience\n- Find your authentic voice\n- Connect with a supportive community"),
        _button("Get Started"),
    ])
    center_row = create_component("row", classes=["row", "justify-content-center"], children=[col])
    section = create_component("section", classes=["vj-section"], children=[
        create_component("grid", classes=["container"], children=[center_row]),
    ])
    return section, []


def _build_cta() -> tuple[dict, list[dict]]:
    col = _make_column(8, children=[
        _heading("Ready to get started?"),
        _text("Book a free discovery call and take the first step."),
        _button("Book Now", extra_classes=["btn-lg"]),
    ])
    center_row = create_component("row", classes=["row", "justify-content-center", "text-center"], children=[col])
    section = create_component("section", classes=["vj-section"], children=[
        create_component("grid", classes=["container"], children=[center_row]),
    ])
    return section, []


def _build_form() -> tuple[dict, list[dict]]:
    form_col = _make_column(8, children=[
        _heading("Contact Us"),
        _text("We'd love to hear from you. Fill out the form below and we'll get back to you shortly."),
        _text("[Contact form — configure via DNN form module or external embed]"),
    ])
    info_col = _make_column(4, children=[
        _heading("Get In Touch"),
        _text("Email: contact@yoursite.com"),
        _text("Follow us on social media for updates and inspiration."),
        _button("Schedule a Call", extra_classes=["btn-outline-primary"]),
    ])

    section = _make_section(children=[form_col, info_col])
    return section, []


def _build_features_4() -> tuple[dict, list[dict]]:
    features = []
    titles = ["Feature 1", "Feature 2", "Feature 3", "Feature 4"]
    for title in titles:
        col = _make_column(3, children=[
            _heading(title),
            _text("Brief description of this value proposition or feature."),
        ])
        features.append(col)

    section = _make_section(children=features)

    heading = _heading("Why Choose Us")
    section["components"][0]["components"].insert(0,
        create_component("row", classes=["row", "mb-4", "text-center"], children=[
            _make_column(12, children=[heading]),
        ])
    )
    return section, []


def _build_program() -> tuple[dict, list[dict]]:
    col = _make_column(8, children=[
        _text("Program 1", extra_classes=["text-uppercase", "small"]),
        _heading("Program Title"),
        _text("Program introduction — describe what this program covers and who it's for."),
        _text("<strong>Week 1: Topic</strong> — Description of what participants will learn."),
        _text("<strong>Week 2: Topic</strong> — Description of what participants will learn."),
        _text("<strong>Week 3: Topic</strong> — Description of what participants will learn."),
        _text("<strong>Week 4: Topic</strong> — Description of what participants will learn."),
        _text("Program summary — what participants will walk away with."),
    ])
    center_row = create_component("row", classes=["row", "justify-content-center"], children=[col])
    section = create_component("section", classes=["vj-section"], children=[
        create_component("grid", classes=["container"], children=[center_row]),
    ])
    return section, []


SECTION_BUILDERS: dict[str, callable] = {
    "hero": _build_hero,
    "hero-simple": _build_hero_simple,
    "content": _build_content,
    "cards-3": _build_cards_3,
    "testimonials": _build_testimonials,
    "bio": _build_bio,
    "checklist": _build_checklist,
    "cta": _build_cta,
    "form": _build_form,
    "features-4": _build_features_4,
    "program": _build_program,
}
