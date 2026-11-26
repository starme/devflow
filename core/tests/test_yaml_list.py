#!/usr/bin/env python3
"""Tests for the shared minimal YAML list scanner."""

from __future__ import annotations

import sys
from pathlib import Path

ORCHESTRATOR = Path(__file__).resolve().parents[1] / "orchestrator"
sys.path.insert(0, str(ORCHESTRATOR))

from yaml_list import ListItem, parse_list_items, unquote


def span(first: str, **fields: str) -> ListItem:
    return ListItem(first_value=first, fields=fields)


def test_double_quoted_with_escapes() -> None:
    assert unquote('"a\\"b\\\\c"') == 'a"b\\c'


def test_single_quoted() -> None:
    assert unquote("'abc'") == "abc"


def test_bare_value_stripped() -> None:
    assert unquote("  bare  ") == "bare"


def test_empty() -> None:
    assert unquote("") == ""


def test_normal_item_fields_are_raw() -> None:
    content = (
        "delivery:\n"
        "  repos:\n"
        '    - track: "backend"\n'
        '      git_root: "/be"\n'
        "      pushed: true\n"
    )
    items = parse_list_items(content, "delivery", "repos")
    assert len(items) == 1
    assert items[0].first_value == '"backend"'
    assert items[0].fields["git_root"] == ' "/be"'  # raw, not stripped
    assert items[0].fields["pushed"] == " true"


def test_first_value_is_stripped() -> None:
    # The first-line value is the only value the scanner strips; readers
    # rely on it for track. Extra spaces must not leak into the record.
    items = parse_list_items("git:\n  endpoints:\n    - track:    a   \n", "git", "endpoints")
    assert items[0].first_value == "a"


def test_absent_section_returns_empty() -> None:
    assert parse_list_items("git:\n  branch: x\n", "delivery", "repos") == []


def test_blank_and_comment_lines_ignored() -> None:
    content = "delivery:\n\n  # note\n  repos:\n    - track: a\n      # field comment\n      x: y\n"
    assert parse_list_items(content, "delivery", "repos") == [span("a", x=" y")]


def test_other_section_resets_list_state() -> None:
    content = (
        "delivery:\n  repos:\n    - track: a\n"
        "task:\n  id: x\n      stray: ignored\n"
    )
    assert parse_list_items(content, "delivery", "repos") == [span("a")]


def test_indent2_other_key_closes_list() -> None:
    # The indent-2 key closes the list, but a later indent-6 field still
    # lands in the (still open) current item — matching the readers this
    # scanner replaced. Zero-semantics is verified by the differential.
    content = "delivery:\n  repos:\n    - track: a\n  commit: x\n      stray: ignored\n"
    assert parse_list_items(content, "delivery", "repos") == [span("a", stray=" ignored")]


def test_indent4_item_still_starts_after_list_closed() -> None:
    # Historical quirk: an indent-2 key closes the list, but a later
    # indent-4 `- ` line still starts a new item. Kept verbatim.
    content = "git:\n  endpoints:\n    - track: be\n  branch: x\n    - track: fe\n"
    assert [i.first_value for i in parse_list_items(content, "git", "endpoints")] == ["be", "fe"]


def test_multiple_items_flush_in_order() -> None:
    content = "git:\n  endpoints:\n    - track: be\n    - track: fe\n      activated: false\n"
    items = parse_list_items(content, "git", "endpoints")
    assert [i.first_value for i in items] == ["be", "fe"]
    assert items[1].fields["activated"] == " false"


def test_first_key_value_becomes_track_even_if_not_track() -> None:
    # Historical behaviour: the first value on a `- ` line is the track.
    items = parse_list_items("delivery:\n  repos:\n    - remote: origin\n", "delivery", "repos")
    assert items == [span("origin")]


def test_indented_track_line_cannot_override_first_value() -> None:
    # Regression (review high): main readers took track ONLY from the
    # first line; an indented `track:` field must not replace it. Keeping
    # first_value separate is what makes this impossible to break.
    content = "delivery:\n  repos:\n    - remote: origin\n      track: later\n      git_root: g\n"
    items = parse_list_items(content, "delivery", "repos")
    assert items[0].first_value == "origin"
    assert items[0].fields["track"] == " later"


def test_malformed_lines_do_not_raise() -> None:
    # A bare `-` line (no trailing space) does not start an item in the
    # original readers either; indented fields before any item are dropped.
    content = "delivery:\n  repos:\n    - \n      :bad\n      no-colon\n        deep: v\n"
    assert parse_list_items(content, "delivery", "repos") == []


def test_malformed_fields_after_an_item_do_not_raise() -> None:
    content = "delivery:\n  repos:\n    - track: a\n      :bad\n      no-colon\n        deep: v\n"
    items = parse_list_items(content, "delivery", "repos")
    assert len(items) == 1
    assert items[0].fields["deep"] == " v"


def test_deeper_indent_is_still_collected() -> None:
    content = "git:\n  endpoints:\n    - track: fe\n        deep: v\n"
    assert parse_list_items(content, "git", "endpoints") == [span("fe", deep=" v")]

