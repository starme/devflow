#!/usr/bin/env python3
"""Task state records used by DevFlow's isolated worktree mode.

The parser intentionally handles only the scalar fields written by this module.
It keeps the task manager dependency-free while allowing users to inspect the
YAML with ordinary tools.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Optional


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    slug: str
    kind: str
    description: str
    base_ref: str
    base_commit: str
    branch: str
    worktree: str
    parent_task_id: Optional[str] = None
    source_task_id: Optional[str] = None


def _yaml_quote(value: Optional[str]) -> str:
    if value is None:
        return "null"
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_task_yaml(record: TaskRecord, current_phase: str = "classify") -> str:
    """Render the stable task state as human-readable YAML."""
    return (
        "schema_version: 1\n"
        "\n"
        "task:\n"
        f"  id: {_yaml_quote(record.task_id)}\n"
        f"  slug: {_yaml_quote(record.slug)}\n"
        f"  kind: {_yaml_quote(record.kind)}\n"
        f"  description: {_yaml_quote(record.description)}\n"
        f"  current_phase: {_yaml_quote(current_phase)}\n"
        "  status: \"active\"\n"
        "\n"
        "git:\n"
        f"  base_ref: {_yaml_quote(record.base_ref)}\n"
        f"  base_commit: {_yaml_quote(record.base_commit)}\n"
        f"  branch: {_yaml_quote(record.branch)}\n"
        f"  worktree: {_yaml_quote(record.worktree)}\n"
        "\n"
        f"parent_task_id: {_yaml_quote(record.parent_task_id)}\n"
        f"source_task_id: {_yaml_quote(record.source_task_id)}\n"
        "\n"
        "project_snapshot:\n"
        "  source: \".devflow/project.yaml\"\n"
        "\n"
        "workflow:\n"
        "  selected_tracks: []\n"
        "\n"
        "artifacts:\n"
        "  prd: null\n"
        "  architecture: null\n"
        "  scope: \".devflow/scope.yaml\"\n"
        "  test_reports: []\n"
        "  acceptance_report: null\n"
        "  delivery: \".devflow/delivery.yaml\"\n"
    )


def _read_scalar(content: str, key: str, section: Optional[str] = None) -> Optional[str]:
    in_section = section is None
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if section is not None:
            if indent == 0 and stripped.endswith(":"):
                in_section = stripped[:-1] == section
                continue
            if not in_section or indent < 2:
                continue
        match = re.match(rf"{re.escape(key)}:\s*(.*)$", stripped)
        if not match:
            continue
        value = match.group(1).strip()
        if value in {"null", "~"}:
            return None
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        return value
    return None


def load_task(path: Path) -> TaskRecord:
    """Load a task record, raising a useful error for malformed state."""
    content = path.read_text(encoding="utf-8")
    values = {
        "task_id": _read_scalar(content, "id", "task"),
        "slug": _read_scalar(content, "slug", "task"),
        "kind": _read_scalar(content, "kind", "task"),
        "description": _read_scalar(content, "description", "task"),
        "base_ref": _read_scalar(content, "base_ref", "git"),
        "base_commit": _read_scalar(content, "base_commit", "git"),
        "branch": _read_scalar(content, "branch", "git"),
        "worktree": _read_scalar(content, "worktree", "git"),
        "parent_task_id": _read_scalar(content, "parent_task_id"),
        "source_task_id": _read_scalar(content, "source_task_id"),
    }
    required = ("task_id", "slug", "kind", "base_ref", "base_commit", "branch", "worktree")
    missing = [key for key in required if not values[key]]
    if missing:
        raise ValueError(f"invalid task state {path}: missing {', '.join(missing)}")
    return TaskRecord(
        task_id=values["task_id"],
        slug=values["slug"],
        kind=values["kind"],
        description=values["description"] or "",
        base_ref=values["base_ref"],
        base_commit=values["base_commit"],
        branch=values["branch"],
        worktree=values["worktree"],
        parent_task_id=values["parent_task_id"],
        source_task_id=values["source_task_id"],
    )


def find_task_files(root: Path) -> list[Path]:
    """Find task state files in the main workspace and managed worktrees."""
    found = []
    in_place = root / ".devflow" / "task.yaml"
    if in_place.is_file():
        found.append(in_place)
    parent = root.parent / ".devflow-worktrees" / root.name
    if parent.is_dir():
        found.extend(
            path / ".devflow" / "task.yaml"
            for path in parent.iterdir()
            if path.is_dir() and (path / ".devflow" / "task.yaml").is_file()
        )
    return sorted(found)
