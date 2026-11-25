#!/usr/bin/env python3
"""Tests for the shared minimal YAML list scanner."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ORCHESTRATOR = Path(__file__).resolve().parents[1] / "orchestrator"
sys.path.insert(0, str(ORCHESTRATOR))

from yaml_list import ListItem, parse_list_items, unquote


def span(first: str, **fields: str) -> ListItem:
    return ListItem(first_value=first, fields=fields)


class UnquoteTest(unittest.TestCase):
    def test_double_quoted_with_escapes(self) -> None:
        self.assertEqual(unquote('"a\\"b\\\\c"'), 'a"b\\c')

    def test_single_quoted(self) -> None:
        self.assertEqual(unquote("'abc'"), "abc")

    def test_bare_value_stripped(self) -> None:
        self.assertEqual(unquote("  bare  "), "bare")

    def test_empty(self) -> None:
        self.assertEqual(unquote(""), "")


class ParseListItemsTest(unittest.TestCase):
    def test_normal_item_fields_are_raw(self) -> None:
        content = (
            "delivery:\n"
            "  repos:\n"
            '    - track: "backend"\n'
            '      git_root: "/be"\n'
            "      pushed: true\n"
        )
        items = parse_list_items(content, "delivery", "repos")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].first_value, '"backend"')
        self.assertEqual(items[0].fields["git_root"], ' "/be"')  # raw, not stripped
        self.assertEqual(items[0].fields["pushed"], " true")

    def test_first_value_is_stripped(self) -> None:
        # The first-line value is the only value the scanner strips; readers
        # rely on it for track. Extra spaces must not leak into the record.
        items = parse_list_items("git:\n  endpoints:\n    - track:    a   \n", "git", "endpoints")
        self.assertEqual(items[0].first_value, "a")

    def test_absent_section_returns_empty(self) -> None:
        self.assertEqual(parse_list_items("git:\n  branch: x\n", "delivery", "repos"), [])

    def test_blank_and_comment_lines_ignored(self) -> None:
        content = "delivery:\n\n  # note\n  repos:\n    - track: a\n      # field comment\n      x: y\n"
        self.assertEqual(parse_list_items(content, "delivery", "repos"), [span("a", x=" y")])

    def test_other_section_resets_list_state(self) -> None:
        content = (
            "delivery:\n  repos:\n    - track: a\n"
            "task:\n  id: x\n      stray: ignored\n"
        )
        self.assertEqual(parse_list_items(content, "delivery", "repos"), [span("a")])

    def test_indent2_other_key_closes_list(self) -> None:
        # The indent-2 key closes the list, but a later indent-6 field still
        # lands in the (still open) current item — matching the readers this
        # scanner replaced. Zero-semantics is verified by the differential.
        content = "delivery:\n  repos:\n    - track: a\n  commit: x\n      stray: ignored\n"
        self.assertEqual(
            parse_list_items(content, "delivery", "repos"),
            [span("a", stray=" ignored")],
        )

    def test_indent4_item_still_starts_after_list_closed(self) -> None:
        # Historical quirk: an indent-2 key closes the list, but a later
        # indent-4 `- ` line still starts a new item. Kept verbatim.
        content = "git:\n  endpoints:\n    - track: be\n  branch: x\n    - track: fe\n"
        self.assertEqual(
            [i.first_value for i in parse_list_items(content, "git", "endpoints")],
            ["be", "fe"],
        )

    def test_multiple_items_flush_in_order(self) -> None:
        content = "git:\n  endpoints:\n    - track: be\n    - track: fe\n      activated: false\n"
        items = parse_list_items(content, "git", "endpoints")
        self.assertEqual([i.first_value for i in items], ["be", "fe"])
        self.assertEqual(items[1].fields["activated"], " false")

    def test_first_key_value_becomes_track_even_if_not_track(self) -> None:
        # Historical behaviour: the first value on a `- ` line is the track.
        items = parse_list_items("delivery:\n  repos:\n    - remote: origin\n", "delivery", "repos")
        self.assertEqual(items, [span("origin")])

    def test_indented_track_line_cannot_override_first_value(self) -> None:
        # Regression (review high): main readers took track ONLY from the
        # first line; an indented `track:` field must not replace it. Keeping
        # first_value separate is what makes this impossible to break.
        content = "delivery:\n  repos:\n    - remote: origin\n      track: later\n      git_root: g\n"
        items = parse_list_items(content, "delivery", "repos")
        self.assertEqual(items[0].first_value, "origin")
        self.assertEqual(items[0].fields["track"], " later")

    def test_malformed_lines_do_not_raise(self) -> None:
        # A bare `-` line (no trailing space) does not start an item in the
        # original readers either; indented fields before any item are dropped.
        content = "delivery:\n  repos:\n    - \n      :bad\n      no-colon\n        deep: v\n"
        self.assertEqual(parse_list_items(content, "delivery", "repos"), [])

    def test_malformed_fields_after_an_item_do_not_raise(self) -> None:
        content = "delivery:\n  repos:\n    - track: a\n      :bad\n      no-colon\n        deep: v\n"
        items = parse_list_items(content, "delivery", "repos")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].fields["deep"], " v")

    def test_deeper_indent_is_still_collected(self) -> None:
        content = "git:\n  endpoints:\n    - track: fe\n        deep: v\n"
        self.assertEqual(parse_list_items(content, "git", "endpoints"), [span("fe", deep=" v")])


if __name__ == "__main__":
    unittest.main()
