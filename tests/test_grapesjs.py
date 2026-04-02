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
