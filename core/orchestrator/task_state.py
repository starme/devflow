#!/usr/bin/env python3
"""Task state records used by DevFlow's isolated worktree mode.

The parser intentionally handles only the scalar fields written by this module.
It keeps the task manager dependency-free while allowing users to inspect the
YAML with ordinary tools.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path


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
    parent_task_id: str | None = None
    source_task_id: str | None = None
    endpoints: tuple[RepoEndpoint, ...] = ()
    # Human-readable card title. Empty means "derive from description", so
    # existing construction sites keep working unchanged.
    title: str = ""

    @property
    def display_title(self) -> str:
        """Title shown in task.yaml — explicit title, else the first line."""
        if self.title.strip():
            return self.title.strip()
        return self.description.strip().splitlines()[0] if self.description.strip() else ""


def _yaml_quote(value: str | None) -> str:
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


def render_task_yaml(record: TaskRecord, current_phase: str = "qa") -> str:
    """Render the stable task state as human-readable YAML.

    v2 (ADR-0005): ``current_phase`` takes one of six values
    (qa / prd_review / plan_review / working / deliver_confirm / done);
    hooks read it for hints only and never block on it.
    """
    lines = [
        "schema_version: 2",
        "",
        "task:",
        f"  id: {_yaml_quote(record.task_id)}",
        f"  slug: {_yaml_quote(record.slug)}",
        f"  title: {_yaml_quote(record.display_title)}",
        f"  kind: {_yaml_quote(record.kind)}",
        f"  description: {_yaml_quote(record.description)}",
        f"  current_phase: {_yaml_quote(current_phase)}",
        '  status: "active"',
        "",
        "git:",
        f"  base_ref: {_yaml_quote(record.base_ref)}",
        f"  base_commit: {_yaml_quote(record.base_commit)}",
        f"  branch: {_yaml_quote(record.branch)}",
        f"  worktree: {_yaml_quote(record.worktree)}",
    ]
    lines.extend(_render_endpoint_lines(record))
    lines.extend(
        [
            "",
            f"parent_task_id: {_yaml_quote(record.parent_task_id)}",
            f"source_task_id: {_yaml_quote(record.source_task_id)}",
            "",
            "artifacts:",
            "  prd: null",
            "  card: null",
            "  verification: null",
            '  delivery: ".devflow/delivery.yaml"',
        ]
    )
    return "\n".join(lines) + "\n"


def _read_scalar(content: str, key: str, section: str | None = None) -> str | None:
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


def _endpoint_from(fields: dict) -> RepoEndpoint | None:
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
    # The guard above rejects any falsy required key, so these are non-None
    # here; ``or ""`` documents that for the type checker.
    return TaskRecord(
        task_id=values["task_id"] or "",
        slug=values["slug"] or "",
        kind=values["kind"] or "",
        description=values["description"] or "",
        base_ref=values["base_ref"] or "",
        base_commit=values["base_commit"] or "",
        branch=values["branch"] or "",
        worktree=values["worktree"] or "",
        parent_task_id=values["parent_task_id"],
        source_task_id=values["source_task_id"],
        endpoints=_read_endpoints(content),
    )


# Task ids end up as a directory name under ``.devflow/tasks/``, so anything
# that could escape that directory (separators, traversal) makes the state
# unsnapshotable rather than dangerous.
_UNSAFE_TASK_ID = re.compile(r"[\\/]|^\.\.?$")


def archive_task_state(task_file: Path) -> Path | None:
    """Copy an existing ``task.yaml`` into its own archive directory.

    In-place tasks all share ``repo_root/.devflow/task.yaml``, so starting a new
    task overwrites the previous one. Snapshotting before the overwrite keeps
    the id/branch/parent chain recoverable.

    Returns the archive path when a copy was written, or ``None`` when there is
    nothing to do: no source file, unreadable/malformed state, an unusable task
    id, or an archive that already exists (published archives win — they are
    the delivery record, not a scratch copy).
    """
    if not task_file.is_file():
        return None
    try:
        record = load_task(task_file)
    except (OSError, ValueError):
        return None
    if not record.task_id or _UNSAFE_TASK_ID.search(record.task_id):
        return None

    archive = task_file.parent / "tasks" / record.task_id / "task.yaml"
    if archive.exists():
        return None
    try:
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(task_file, archive)
    except OSError:
        return None
    return archive


def find_task_files(root: Path, state_root: Path | None = None) -> list[Path]:
    """Find task state files in the main workspace and managed worktrees.

    *state_root* is the directory owning ``.devflow/`` when it differs from
    *root* — a project whose repository is nested inside it keeps in-place state
    with the project, not with the repository. It is omitted for ordinary
    projects so the search looks in one place only.
    """
    found = []
    for base in (root, state_root):
        if base is None:
            continue
        in_place = base / ".devflow" / "task.yaml"
        if in_place.is_file() and in_place not in found:
            found.append(in_place)
    parent = root.parent / ".devflow-worktrees" / root.name
    if parent.is_dir():
        found.extend(
            path / ".devflow" / "task.yaml"
            for path in parent.iterdir()
            if path.is_dir() and (path / ".devflow" / "task.yaml").is_file()
        )
    return sorted(found)
