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
class RepoEndpoint:
    """One git repository endpoint a task spans.

    A multi-repo task (separated backend/frontend) touches several independent
    git roots.  Each endpoint carries its own base ref/commit and shares the
    same branch name across repositories.
    """
    track: str
    git_root: str
    base_ref: str
    base_commit: str
    branch: str


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
    endpoints: tuple[RepoEndpoint, ...] = ()


def _yaml_quote(value: Optional[str]) -> str:
    if value is None:
        return "null"
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _render_endpoint_lines(record: TaskRecord) -> list[str]:
    """Render the optional per-repo ``endpoints:`` list under the ``git:``
    section.  Returns ``[]`` for a single-repo task so the output stays
    identical to the legacy shape."""
    if not record.endpoints:
        return []
    lines = ["  endpoints:"]
    for ep in record.endpoints:
        lines.append("    - track: " + _yaml_quote(ep.track))
        lines.append(f"      git_root: {_yaml_quote(ep.git_root)}")
        lines.append(f"      base_ref: {_yaml_quote(ep.base_ref)}")
        lines.append(f"      base_commit: {_yaml_quote(ep.base_commit)}")
        lines.append(f"      branch: {_yaml_quote(ep.branch)}")
    return lines


def render_task_yaml(record: TaskRecord, current_phase: str = "classify") -> str:
    """Render the stable task state as human-readable YAML."""
    lines = [
        "schema_version: 1",
        "",
        "task:",
        f"  id: {_yaml_quote(record.task_id)}",
        f"  slug: {_yaml_quote(record.slug)}",
        f"  kind: {_yaml_quote(record.kind)}",
        f"  description: {_yaml_quote(record.description)}",
        f"  current_phase: {_yaml_quote(current_phase)}",
        "  status: \"active\"",
        "",
        "git:",
        f"  base_ref: {_yaml_quote(record.base_ref)}",
        f"  base_commit: {_yaml_quote(record.base_commit)}",
        f"  branch: {_yaml_quote(record.branch)}",
        f"  worktree: {_yaml_quote(record.worktree)}",
    ]
    lines.extend(_render_endpoint_lines(record))
    lines.extend([
        "",
        f"parent_task_id: {_yaml_quote(record.parent_task_id)}",
        f"source_task_id: {_yaml_quote(record.source_task_id)}",
        "",
        "project_snapshot:",
        "  source: \".devflow/project.yaml\"",
        "",
        "workflow:",
        "  selected_tracks: []",
        "",
        "artifacts:",
        "  prd: null",
        "  architecture: null",
        "  scope: \".devflow/scope.yaml\"",
        "  test_reports: []",
        "  acceptance_report: null",
        "  delivery: \".devflow/delivery.yaml\"",
    ])
    return "\n".join(lines) + "\n"


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


def _read_endpoints(content: str) -> tuple:
    """Parse the optional ``git.endpoints`` list into ``RepoEndpoint`` tuples.

    Fail-safe: any malformed entry is skipped; an absent section yields ``()``.
    The parser walks the ``git:`` section looking for ``endpoints:`` then reads
    each ``- track:`` item's indented scalar fields.
    """
    endpoints = []
    lines = content.splitlines()
    in_git = False
    in_endpoints = False
    current: dict = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0 and stripped.endswith(":"):
            in_git = stripped[:-1] == "git"
            in_endpoints = False
            continue
        if not in_git:
            continue
        if indent == 2 and stripped == "endpoints:":
            in_endpoints = True
            continue
        if in_endpoints:
            if indent == 2 and stripped.endswith(":") and stripped != "endpoints:":
                # left the endpoints list into another git: subkey
                in_endpoints = False
                continue
            if indent == 4 and stripped.startswith("- "):
                if current:
                    endpoints.append(_endpoint_from(current))
                # ``- track: "backend"`` → track value after the first colon
                _, _, track_val = stripped[2:].partition(":")
                current = {"track": _unquote(track_val.strip())}
                continue
            if indent >= 6 and current is not None:
                key, _, val = stripped.partition(":")
                key = key.strip()
                if key in ("git_root", "base_ref", "base_commit", "branch"):
                    current[key] = _unquote(val.strip())
    if current:
        endpoints.append(_endpoint_from(current))
    return tuple(ep for ep in endpoints if ep is not None)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    return value


def _endpoint_from(fields: dict) -> Optional[RepoEndpoint]:
    track = fields.get("track", "")
    git_root = fields.get("git_root", "")
    if not track or not git_root:
        return None
    return RepoEndpoint(
        track=track,
        git_root=git_root,
        base_ref=fields.get("base_ref", ""),
        base_commit=fields.get("base_commit", ""),
        branch=fields.get("branch", ""),
    )


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
        endpoints=_read_endpoints(content),
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
