"""The hand-rolled JSON Patch/Pointer (I2c §4.2, SW-36): a closed RFC 6902
op set over RFC 6901 pointers, fail-loud on everything else, pinned against
the RFC's own examples. No third-party implementation exists behind this
module — these examples are the spec's, quoted from RFC 6902 §4 and
Appendix A and RFC 6901 §3-§5."""

from __future__ import annotations

import pytest

from benchweave_sdk_server.jsonpatch import (
    JSONPatchError,
    apply_patch,
    parse_pointer,
)

# --- RFC 6901 pointers ---------------------------------------------------------


def test_pointer_root_is_empty() -> None:
    assert parse_pointer("") == []


def test_pointer_tokens_split_on_slash() -> None:
    assert parse_pointer("/foo/bar") == ["foo", "bar"]
    # An empty member name is legal (RFC 6901 §3: "" names the root, "/"
    # names the empty-string member).
    assert parse_pointer("/") == [""]


def test_pointer_escapes() -> None:
    """RFC 6901 §3: ``~1`` is ``/`` and ``~0`` is ``~``, in that order —
    ``~01`` is the literal ``~1``, not an escaped slash."""
    assert parse_pointer("/a~1b") == ["a/b"]
    assert parse_pointer("/m~0n") == ["m~n"]
    assert parse_pointer("/~01") == ["~1"]


def test_pointer_rejects_bad_escapes_and_unrooted_paths() -> None:
    with pytest.raises(JSONPatchError):
        parse_pointer("/a~2b")
    with pytest.raises(JSONPatchError):
        parse_pointer("a/b")


# --- RFC 6902 §4 / Appendix A — the operation set ------------------------------


def test_add_object_member_rfc_a1() -> None:
    assert apply_patch(
        {"foo": "bar"}, [{"op": "add", "path": "/baz", "value": "qux"}]
    ) == {"foo": "bar", "baz": "qux"}


def test_add_array_element_rfc_a2() -> None:
    assert apply_patch(
        {"foo": ["bar", "baz"]}, [{"op": "add", "path": "/foo/1", "value": "qux"}]
    ) == {"foo": ["bar", "qux", "baz"]}


def test_add_appends_with_the_dash_token_rfc_a3() -> None:
    assert apply_patch(
        {"foo": ["bar", "baz"]}, [{"op": "add", "path": "/foo/-", "value": "qux"}]
    ) == {"foo": ["bar", "baz", "qux"]}


def test_add_to_the_root_replaces_the_whole_document() -> None:
    assert apply_patch({"foo": "bar"}, [{"op": "add", "path": "", "value": [1]}]) == [1]


def test_remove_object_member_rfc_a4() -> None:
    assert apply_patch(
        {"bar": "baz", "foo": "bar"}, [{"op": "remove", "path": "/bar"}]
    ) == {"foo": "bar"}


def test_remove_array_element_rfc_a5() -> None:
    assert apply_patch(
        {"foo": ["bar", "qux", "baz"]}, [{"op": "remove", "path": "/foo/1"}]
    ) == {"foo": ["bar", "baz"]}


def test_replace_object_member_rfc_a6() -> None:
    assert apply_patch(
        {"bar": "baz", "foo": "bar"},
        [{"op": "replace", "path": "/bar", "value": "qux"}],
    ) == {"bar": "qux", "foo": "bar"}


def test_move_rfc_a9() -> None:
    assert apply_patch(
        {"foo": {"bar": "baz", "waldo": "fred"}, "qux": {"corge": "grault"}},
        [{"op": "move", "from": "/foo/waldo", "path": "/qux/thud"}],
    ) == {"foo": {"bar": "baz"}, "qux": {"corge": "grault", "thud": "fred"}}


def test_move_to_the_same_path_is_a_no_op() -> None:
    doc = {"a": 1}
    assert apply_patch(doc, [{"op": "move", "from": "/a", "path": "/a"}]) == doc


def test_copy() -> None:
    assert apply_patch(
        {"foo": {"bar": "baz"}, "qux": {}},
        [{"op": "copy", "from": "/foo", "path": "/qux/thud"}],
    ) == {"foo": {"bar": "baz"}, "qux": {"thud": {"bar": "baz"}}}


def test_copy_is_deep_not_aliased() -> None:
    result = apply_patch(
        {"src": {"nested": [1]}},
        [{"op": "copy", "from": "/src", "path": "/dst"}],
    )
    assert result["dst"] == result["src"]
    assert result["dst"] is not result["src"]
    result["dst"]["nested"].append(2)
    assert result["src"]["nested"] == [1]


def test_test_op_passes_on_equal_and_fails_on_difference() -> None:
    doc = {"baz": "qux", "foo": ["a", 2, "c"]}
    kept = apply_patch(doc, [{"op": "test", "path": "/baz", "value": "qux"}])
    assert kept == doc
    with pytest.raises(JSONPatchError):
        apply_patch(doc, [{"op": "test", "path": "/foo", "value": "bar"}])


def test_test_distinguishes_bool_from_number() -> None:
    """Python says ``True == 1``; JSON says they differ (RFC 8259 has two
    literal kinds) — the test op must not launder one into the other."""
    with pytest.raises(JSONPatchError):
        apply_patch({"flag": True}, [{"op": "test", "path": "/flag", "value": 1}])
    with pytest.raises(JSONPatchError):
        apply_patch({"flag": 1}, [{"op": "test", "path": "/flag", "value": True}])


def test_operations_apply_in_order_and_see_each_others_results() -> None:
    assert apply_patch(
        {"a": 1},
        [
            {"op": "add", "path": "/b", "value": 2},
            {"op": "test", "path": "/b", "value": 2},
            {"op": "move", "from": "/a", "path": "/c"},
        ],
    ) == {"b": 2, "c": 1}


def test_the_input_document_is_never_mutated() -> None:
    original = {"foo": ["bar", "baz"]}
    apply_patch(original, [{"op": "add", "path": "/foo/-", "value": "qux"}])
    assert original == {"foo": ["bar", "baz"]}


def test_a_failed_operation_writes_nothing_partial() -> None:
    """A patch whose SECOND operation fails leaves the document untouched:
    the caller gets an error, not a half-applied result (SW-36's
    failing-patch-writes-nothing rule, in-memory half)."""
    doc = {"foo": 1, "bar": 2}
    with pytest.raises(JSONPatchError):
        apply_patch(
            doc,
            [
                {"op": "remove", "path": "/foo"},
                {"op": "remove", "path": "/nope"},
            ],
        )
    assert doc == {"foo": 1, "bar": 2}


# --- fail-loud arms --------------------------------------------------------------


def test_unknown_op_is_refused_by_name() -> None:
    with pytest.raises(JSONPatchError) as caught:
        apply_patch({}, [{"op": "merge", "path": "/a", "value": 1}])
    assert "merge" in str(caught.value)


def test_non_list_patch_is_refused() -> None:
    with pytest.raises(JSONPatchError):
        apply_patch({}, {"op": "add", "path": "/a"})


def test_operation_without_a_path_is_refused() -> None:
    with pytest.raises(JSONPatchError):
        apply_patch({}, [{"op": "add", "value": 1}])


def test_add_into_a_missing_parent_is_refused() -> None:
    with pytest.raises(JSONPatchError):
        apply_patch({}, [{"op": "add", "path": "/a/b", "value": 1}])


def test_add_into_a_scalar_member_is_refused() -> None:
    with pytest.raises(JSONPatchError):
        apply_patch({"a": 1}, [{"op": "add", "path": "/a/b", "value": 1}])


def test_remove_and_replace_require_the_target_to_exist() -> None:
    with pytest.raises(JSONPatchError):
        apply_patch({}, [{"op": "remove", "path": "/a"}])
    with pytest.raises(JSONPatchError):
        apply_patch({}, [{"op": "replace", "path": "/a", "value": 1}])


def test_array_indices_are_bounded_and_unpadded() -> None:
    doc = {"foo": ["a", "b"]}
    with pytest.raises(JSONPatchError):
        apply_patch(doc, [{"op": "add", "path": "/foo/3", "value": "c"}])
    with pytest.raises(JSONPatchError):
        apply_patch(doc, [{"op": "remove", "path": "/foo/2"}])
    with pytest.raises(JSONPatchError):
        apply_patch(doc, [{"op": "remove", "path": "/foo/-"}])
    with pytest.raises(JSONPatchError):
        apply_patch(doc, [{"op": "add", "path": "/foo/01", "value": "c"}])


def test_walk_through_a_scalar_is_refused() -> None:
    with pytest.raises(JSONPatchError):
        apply_patch({"a": 1}, [{"op": "add", "path": "/a/0/b", "value": 1}])


def test_move_from_a_missing_location_is_refused() -> None:
    with pytest.raises(JSONPatchError):
        apply_patch({"a": {}}, [{"op": "move", "from": "/nope", "path": "/a/b"}])


def test_move_into_own_subtree_is_refused() -> None:
    """RFC 6902 §4.4: the from-location is removed first, so a target inside
    the moved subtree is unreachable — a loud refusal, not a corrupt tree."""
    with pytest.raises(JSONPatchError):
        apply_patch(
            {"a": {"b": {"c": 1}}},
            [{"op": "move", "from": "/a/b", "path": "/a/b/c"}],
        )


def test_move_of_a_whole_array_into_its_own_slot_is_refused() -> None:
    """The CLASS, not the dict instance (the lanes' FOLD-C): re-indexing
    defeats the dict form's structural failure — removing /foo first
    leaves a shorter list whose /foo/1 still RESOLVES, so the array form
    silently accepted a move of a value into itself. The proper-prefix
    check is pointer-level: no container form escapes it."""
    with pytest.raises(JSONPatchError) as caught:
        apply_patch(
            {"foo": [1, 2, 3]},
            [{"op": "move", "from": "/foo", "path": "/foo/1"}],
        )
    assert "move_into_self" in str(caught.value)


def test_move_of_an_array_element_into_its_own_descendant_is_refused() -> None:
    """The second array repro: the element being moved is itself a list,
    and the destination is inside that list — accepted today because the
    removal re-indexes the parent before the add resolves."""
    with pytest.raises(JSONPatchError):
        apply_patch(
            {"outer": [[10, 20], [30]]},
            [{"op": "move", "from": "/outer/0", "path": "/outer/0/1"}],
        )


def test_intra_array_reordering_still_moves() -> None:
    """The boundary the prefix check must NOT cross: moving an element
    within its own PARENT (neither path a prefix of the other) is the
    RFC's own remove-then-add rotation and stays legal."""
    assert apply_patch(
        {"foo": ["a", "b", "c"]},
        [{"op": "move", "from": "/foo/0", "path": "/foo/2"}],
    ) == {"foo": ["b", "c", "a"]}


def test_remove_of_the_root_is_refused() -> None:
    with pytest.raises(JSONPatchError):
        apply_patch({"a": 1}, [{"op": "remove", "path": ""}])
