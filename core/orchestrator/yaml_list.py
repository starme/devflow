"""Shared minimal YAML list scanner for DevFlow's handwritten state readers.

``delivery.yaml`` / ``task.yaml`` carry optional indented lists (``repos:`` /
``endpoints:``). Two readers used to keep near-identical copies of the same
indentation state machine; PR #34 showed how easily a fix to one copy missed
the other. This module owns that one state machine and nothing else.

It is deliberately *not* a YAML parser: it only recognises the shapes emitted
by ``render_delivery_yaml`` / ``render_task_yaml`` and the legacy files they
read. Values are handed back as raw strings — unquoting, null handling and
type conversion stay with each caller, because the callers differ subtly and
preserving those differences is what makes this refactor zero-semantics.
"""

from __future__ import annotations

from dataclasses import dataclass


def unquote(value: str) -> str:
    """Strip surrounding quotes (and their escapes) from a YAML scalar."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    return value


@dataclass(frozen=True)
class ListItem:
    """One ``- `` item: its first-line value and its indented raw fields.

    Why separate: in the readers this replaces, the first-line value is the
    *only* source of ``track``; an indented ``track:`` line was never a
    whitelisted field and therefore could not change it. Keeping the two apart
    makes that historical rule impossible to break by a key-name collision.
    """

    first_value: str
    fields: dict[str, str]


def parse_list_items(content: str, section: str, list_key: str) -> list[ListItem]:
    """Return the items of ``section.list_key`` with raw, unstripped values.

    Fail-safe, matching the readers this replaces:
    * blank/comment lines are ignored;
    * a top-level ``key:`` switches (or leaves) the section;
    * ``  <list_key>:`` opens the list; another indent-2 ``key:`` closes it;
    * ``    - <anything>`` starts a new item whose first value is kept apart
      from the indented fields (the historical behaviour — not "fixed");
    * deeper ``key: value`` lines add raw fields to the current item.

    Values are NOT stripped or unquoted here. ``val`` is exactly the text
    after the first colon, so callers keep their own whitespace/quoting rules.
    """
    items: list[ListItem] = []
    lines = content.splitlines()
    in_section = False
    in_list = False
    current: ListItem | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0 and stripped.endswith(":"):
            in_section = stripped[:-1] == section
            in_list = False
            continue
        if not in_section:
            continue
        if indent == 2 and stripped == f"{list_key}:":
            in_list = True
            continue
        if in_list:
            if indent == 2 and stripped.endswith(":") and stripped != f"{list_key}:":
                in_list = False
                continue
            if indent == 4 and stripped.startswith("- "):
                if current is not None:
                    items.append(current)
                _, _, first_val = stripped[2:].partition(":")
                current = ListItem(first_value=first_val.strip(), fields={})
                continue
            if indent >= 6 and current is not None:
                key, _, val = stripped.partition(":")
                current.fields[key.strip()] = val
    if current is not None:
        items.append(current)
    return items
