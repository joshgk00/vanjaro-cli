"""Tests for GrapesJS component tree helpers."""

from __future__ import annotations

import copy

import pytest

from vanjaro_cli.utils.grapesjs import (
    create_component,
    find_component,
    insert_component,
    list_components,
    remove_component,
    render_component,
    render_components,
)

SAMPLE_TREE = [
    {
        "type": "section",
        "attributes": {"id": "s1"},
        "components": [
            {
                "type": "grid",
                "attributes": {"id": "g1"},
                "components": [
                    {
                        "type": "row",
                        "attributes": {"id": "r1"},
                        "components": [
                            {"type": "text", "content": "Hello", "attributes": {"id": "t1"}},
                            {"type": "image", "attributes": {"id": "img1", "src": "/test.png"}},
                        ],
                    }
                ],
            }
        ],
    },
    {"type": "section", "attributes": {"id": "s2"}, "components": []},
]



class TestFindComponent:
    def test_find_root_component(self) -> None:
        result = find_component(SAMPLE_TREE, "s1")
        assert result is not None
        assert result["type"] == "section"
        assert result["attributes"]["id"] == "s1"

    def test_find_nested_component(self) -> None:
        result = find_component(SAMPLE_TREE, "g1")
        assert result is not None
        assert result["type"] == "grid"

    def test_find_deeply_nested_component(self) -> None:
        result = find_component(SAMPLE_TREE, "t1")
        assert result is not None
        assert result["type"] == "text"
        assert result["content"] == "Hello"

    def test_find_second_root_component(self) -> None:
        result = find_component(SAMPLE_TREE, "s2")
        assert result is not None
        assert result["type"] == "section"

    def test_not_found_returns_none(self) -> None:
        assert find_component(SAMPLE_TREE, "nonexistent") is None

    def test_empty_tree(self) -> None:
        assert find_component([], "s1") is None



class TestListComponents:
    def test_flat_list(self) -> None:
        flat = [
            {"type": "text", "attributes": {"id": "a"}, "content": "One"},
            {"type": "image", "attributes": {"id": "b"}},
        ]
        result = list_components(flat)
        assert len(result) == 2
        assert result[0] == {
            "id": "a",
            "type": "text",
            "depth": 0,
            "name": "",
            "content_preview": "One",
            "child_count": 0,
        }
        assert result[1]["id"] == "b"
        assert result[1]["depth"] == 0

    def test_nested_tree_depths(self) -> None:
        result = list_components(SAMPLE_TREE)
        ids_and_depths = [(entry["id"], entry["depth"]) for entry in result]
        assert ids_and_depths == [
            ("s1", 0),
            ("g1", 1),
            ("r1", 2),
            ("t1", 3),
            ("img1", 3),
            ("s2", 0),
        ]

    def test_child_count(self) -> None:
        result = list_components(SAMPLE_TREE)
        by_id = {entry["id"]: entry for entry in result}
        assert by_id["s1"]["child_count"] == 1
        assert by_id["g1"]["child_count"] == 1
        assert by_id["r1"]["child_count"] == 2
        assert by_id["t1"]["child_count"] == 0
        assert by_id["s2"]["child_count"] == 0

    def test_content_preview_truncation(self) -> None:
        long_content = "A" * 100
        tree = [{"type": "text", "attributes": {"id": "x"}, "content": long_content}]
        result = list_components(tree)
        assert len(result[0]["content_preview"]) == 60

    def test_content_preview_strips_whitespace(self) -> None:
        tree = [{"type": "text", "attributes": {"id": "x"}, "content": "  spaced  "}]
        result = list_components(tree)
        assert result[0]["content_preview"] == "spaced"

    def test_name_from_name_field(self) -> None:
        tree = [{"type": "text", "attributes": {"id": "x"}, "name": "My Block"}]
        result = list_components(tree)
        assert result[0]["name"] == "My Block"

    def test_name_from_custom_name(self) -> None:
        tree = [{"type": "text", "attributes": {"id": "x"}, "custom-name": "Custom"}]
        result = list_components(tree)
        assert result[0]["name"] == "Custom"

    def test_empty_tree(self) -> None:
        assert list_components([]) == []



class TestInsertComponent:
    def test_insert_at_root_end(self) -> None:
        new = {"type": "divider", "attributes": {"id": "d1"}}
        result = insert_component(SAMPLE_TREE, new)
        assert len(result) == 3
        assert result[-1]["attributes"]["id"] == "d1"

    def test_insert_at_root_position(self) -> None:
        new = {"type": "divider", "attributes": {"id": "d1"}}
        result = insert_component(SAMPLE_TREE, new, position=0)
        assert result[0]["attributes"]["id"] == "d1"
        assert len(result) == 3

    def test_insert_into_parent(self) -> None:
        new = {"type": "button", "attributes": {"id": "btn1"}}
        result = insert_component(SAMPLE_TREE, new, parent_id="r1")
        row = find_component(result, "r1")
        assert row is not None
        assert len(row["components"]) == 3
        assert row["components"][-1]["attributes"]["id"] == "btn1"

    def test_insert_into_parent_at_position(self) -> None:
        new = {"type": "button", "attributes": {"id": "btn1"}}
        result = insert_component(SAMPLE_TREE, new, parent_id="r1", position=0)
        row = find_component(result, "r1")
        assert row is not None
        assert row["components"][0]["attributes"]["id"] == "btn1"
        assert len(row["components"]) == 3

    def test_insert_parent_not_found_raises(self) -> None:
        new = {"type": "button", "attributes": {"id": "btn1"}}
        with pytest.raises(ValueError, match="not found"):
            insert_component(SAMPLE_TREE, new, parent_id="nonexistent")

    def test_insert_does_not_mutate_original(self) -> None:
        original = copy.deepcopy(SAMPLE_TREE)
        new = {"type": "divider", "attributes": {"id": "d1"}}
        insert_component(SAMPLE_TREE, new)
        assert SAMPLE_TREE == original

    def test_insert_into_parent_without_components_key(self) -> None:
        tree = [{"type": "section", "attributes": {"id": "bare"}}]
        new = {"type": "text", "attributes": {"id": "child"}}
        result = insert_component(tree, new, parent_id="bare")
        parent = find_component(result, "bare")
        assert parent is not None
        assert len(parent["components"]) == 1



class TestRemoveComponent:
    def test_remove_leaf(self) -> None:
        result = remove_component(SAMPLE_TREE, "t1")
        assert find_component(result, "t1") is None
        row = find_component(result, "r1")
        assert row is not None
        assert len(row["components"]) == 1

    def test_remove_node_with_children(self) -> None:
        result = remove_component(SAMPLE_TREE, "g1")
        assert find_component(result, "g1") is None
        assert find_component(result, "r1") is None
        assert find_component(result, "t1") is None

    def test_remove_root_component(self) -> None:
        result = remove_component(SAMPLE_TREE, "s2")
        assert len(result) == 1
        assert find_component(result, "s2") is None

    def test_remove_not_found_raises(self) -> None:
        with pytest.raises(ValueError, match="not found"):
            remove_component(SAMPLE_TREE, "nonexistent")

    def test_remove_does_not_mutate_original(self) -> None:
        original = copy.deepcopy(SAMPLE_TREE)
        remove_component(SAMPLE_TREE, "t1")
        assert SAMPLE_TREE == original



class TestCreateComponent:
    def test_basic_creation(self) -> None:
        result = create_component("text", content="Hello")
        assert result["type"] == "text"
        assert result["content"] == "Hello"
        assert "id" in result["attributes"]

    def test_auto_generates_id(self) -> None:
        result = create_component("divider")
        assert len(result["attributes"]["id"]) == 5

    def test_preserves_given_id(self) -> None:
        result = create_component("text", attributes={"id": "my-id"})
        assert result["attributes"]["id"] == "my-id"

    def test_with_classes(self) -> None:
        result = create_component("section", classes=["vj-section", "wide"])
        assert result["classes"] == [
            {"name": "vj-section", "active": False},
            {"name": "wide", "active": False},
        ]

    def test_with_children(self) -> None:
        child = create_component("text", content="child")
        result = create_component("row", children=[child])
        assert len(result["components"]) == 1
        assert result["components"][0]["type"] == "text"

    def test_no_content_key_when_empty(self) -> None:
        result = create_component("divider")
        assert "content" not in result

    def test_no_classes_key_when_none(self) -> None:
        result = create_component("divider")
        assert "classes" not in result

    def test_no_components_key_when_no_children(self) -> None:
        result = create_component("divider")
        assert "components" not in result

    def test_does_not_mutate_input_attributes(self) -> None:
        attrs = {"id": "keep", "data-custom": "value"}
        original_attrs = dict(attrs)
        create_component("text", attributes=attrs)
        assert attrs == original_attrs


class TestRenderComponents:
    """Serialize GrapesJS component trees to the HTML shape Vanjaro expects."""

    def test_empty_list_returns_empty_string(self) -> None:
        assert render_components([]) == ""

    def test_section_type_maps_to_section_tag(self) -> None:
        component = {"type": "section", "attributes": {"id": "s1"}}
        assert render_component(component) == '<section id="s1"></section>'

    def test_tagname_overrides_type_mapping(self) -> None:
        component = {"type": "heading", "tagName": "h1", "attributes": {"id": "h"}}
        assert render_component(component) == '<h1 id="h"></h1>'

    def test_classes_are_serialized_from_active_array_shape(self) -> None:
        component = {
            "type": "section",
            "attributes": {"id": "s"},
            "classes": [
                {"name": "vj-section", "active": True},
                {"name": "py-5", "active": False},
            ],
        }
        # Both names serialized — active flag is GrapesJS runtime state, not HTML
        assert render_component(component) == '<section id="s" class="vj-section py-5"></section>'

    def test_classes_accept_plain_string_entries(self) -> None:
        component = {"type": "section", "attributes": {"id": "s"}, "classes": ["alpha", "beta"]}
        assert render_component(component) == '<section id="s" class="alpha beta"></section>'

    def test_attribute_order_puts_data_before_id_before_class(self) -> None:
        """Matches the byte shape the Vanjaro editor emits."""
        component = {
            "type": "section",
            "attributes": {"id": "s", "data-role": "main", "role": "region"},
            "classes": ["vj-section"],
        }
        assert render_component(component) == (
            '<section data-role="main" id="s" role="region" class="vj-section"></section>'
        )

    def test_published_attribute_is_stripped_as_internal_state(self) -> None:
        component = {
            "type": "section",
            "attributes": {"id": "s", "published": True},
        }
        assert "published" not in render_component(component)

    def test_text_content_is_rendered_inside_tag(self) -> None:
        component = {"type": "heading", "tagName": "h2", "content": "Hello", "attributes": {"id": "h"}}
        assert render_component(component) == '<h2 id="h">Hello</h2>'

    def test_nested_components_are_rendered_recursively(self) -> None:
        component = {
            "type": "section",
            "attributes": {"id": "s"},
            "components": [
                {"type": "grid", "attributes": {"id": "g"}, "components": [
                    {"type": "heading", "tagName": "h3", "content": "Nested", "attributes": {"id": "h"}},
                ]},
            ],
        }
        result = render_component(component)
        assert result == '<section id="s"><div id="g"><h3 id="h">Nested</h3></div></section>'

    def test_void_elements_are_self_closing_with_no_children(self) -> None:
        component = {"type": "image", "attributes": {"id": "i", "src": "/a.png", "alt": "Alt"}}
        assert render_component(component) == '<img id="i" src="/a.png" alt="Alt">'

    def test_globalblockwrapper_renders_as_empty_div(self) -> None:
        """Vanjaro expands these server-side by their data-guid reference."""
        component = {
            "type": "globalblockwrapper",
            "name": "Global: Header",
            "attributes": {
                "data-block-type": "global",
                "data-block-guid": "7a4be0f2-56ab-410a-9422-6bc91b488150",
                "data-guid": "20020077-89f8-468f-a488-017421ce5a0b",
                "id": "hdr",
                "published": True,
            },
            "components": [{"type": "section", "content": "ignored at render"}],
        }
        result = render_component(component)
        assert result == (
            '<div data-block-type="global" '
            'data-block-guid="7a4be0f2-56ab-410a-9422-6bc91b488150" '
            'data-guid="20020077-89f8-468f-a488-017421ce5a0b" id="hdr"></div>'
        )

    def test_textnode_emits_content_without_wrapping_tag(self) -> None:
        component = {"type": "textnode", "content": "bare text"}
        assert render_component(component) == "bare text"

    def test_textnode_escapes_html_entities(self) -> None:
        component = {"type": "textnode", "content": "<script>x</script>"}
        assert render_component(component) == "&lt;script&gt;x&lt;/script&gt;"

    def test_attribute_values_are_quote_escaped(self) -> None:
        component = {"type": "section", "attributes": {"id": "s", "data-q": 'a"b'}}
        assert 'data-q="a&quot;b"' in render_component(component)

    def test_multiple_top_level_components_concatenated(self) -> None:
        components = [
            {"type": "section", "attributes": {"id": "s1"}},
            {"type": "section", "attributes": {"id": "s2"}},
        ]
        assert render_components(components) == '<section id="s1"></section><section id="s2"></section>'

    def test_non_dict_entries_are_skipped(self) -> None:
        components = [
            {"type": "section", "attributes": {"id": "s"}},
            "invalid",
            None,
            42,
        ]
        assert render_components(components) == '<section id="s"></section>'

    def test_full_ui_page_roundtrip_matches_server_output(self) -> None:
        """Header + empty section + footer — the minimal Vanjaro page shape.

        This exact byte shape was captured from a UI-created test page on
        ``vanjarocli.local`` and is what Vanjaro's server-side renderer expects
        as ``contentHtml``. Regressing the byte shape would break rendering
        for migrated sites.
        """
        components = [
            {
                "type": "globalblockwrapper",
                "name": "Global: Header",
                "attributes": {
                    "data-block-type": "global",
                    "data-block-guid": "7a4be0f2-56ab-410a-9422-6bc91b488150",
                    "data-guid": "20020077-89f8-468f-a488-017421ce5a0b",
                    "id": "inp2m",
                    "published": True,
                },
            },
            {
                "type": "section",
                "content": "\n\t\t\t\t",
                "classes": [{"name": "vj-section", "active": True}],
                "attributes": {"id": "ihtp1"},
            },
            {
                "type": "globalblockwrapper",
                "name": "Global: Footer",
                "attributes": {
                    "data-block-type": "global",
                    "data-block-guid": "7a4be0f2-56ab-410a-9422-6bc91b488150",
                    "data-guid": "fe37ff48-2c99-4201-85fc-913cac94914d",
                    "id": "i2orf",
                    "published": True,
                },
            },
        ]
        expected = (
            '<div data-block-type="global" '
            'data-block-guid="7a4be0f2-56ab-410a-9422-6bc91b488150" '
            'data-guid="20020077-89f8-468f-a488-017421ce5a0b" id="inp2m"></div>'
            '<section id="ihtp1" class="vj-section">\n\t\t\t\t</section>'
            '<div data-block-type="global" '
            'data-block-guid="7a4be0f2-56ab-410a-9422-6bc91b488150" '
            'data-guid="fe37ff48-2c99-4201-85fc-913cac94914d" id="i2orf"></div>'
        )
        assert render_components(components) == expected
