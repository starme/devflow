#!/usr/bin/env python3
"""Create and discover isolated DevFlow task worktrees."""
from __future__ import annotations

from pathlib import Path
import json
import re
import shutil
import subprocess
import uuid

from typing import Optional

from task_state import TaskRecord, _read_scalar, find_task_files, render_task_yaml


class WorktreeError(RuntimeError):
    """Raised when a task worktree cannot be created safely."""


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, text=True, capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise WorktreeError(f"git {' '.join(args)} failed in {root}: {detail.strip()}") from exc
    return result.stdout.strip()


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40] or "task"


def _repo_root(path: Path) -> Path:
    return Path(_git(path, "rev-parse", "--show-toplevel")).resolve()


# Porcelain XY status characters that mark a *tracked* change.  Untracked
# (``??``) and ignored (``!!``) files are deliberately excluded: they are
# exactly the sort of residue (a prior task's unpublished artifacts) that must
# not block starting a new task.
_TRACKED_CHANGE_FLAGS = frozenset({"M", "A", "D", "R", "C"})


def _ensure_clean(root: Path) -> None:
    """Raise only when tracked files have uncommitted changes (M/A/D/R/C).

    Untracked (``??``) and ignored (``!!``) entries leave the workspace "clean"
    enough to start a new task — git doesn't risk silently committing them into
    a new worktree because they simply won't be tracked there either.
    """
    status = _git(root, "status", "--porcelain")
    for line in status.splitlines():
        xy = line[:2]
        if xy[0] in _TRACKED_CHANGE_FLAGS or xy[1] in _TRACKED_CHANGE_FLAGS:
            raise WorktreeError(f"main workspace has uncommitted changes: {root}")


def _active_in_place_task(root: Path) -> bool:
    """True when the main workspace already holds an unfinished task."""
    path = root / ".devflow" / "task.yaml"
    if not path.is_file():
        return False
    try:
        status = _read_scalar(path.read_text(encoding="utf-8"), "status", "task")
    except OSError:
        return True
    return status != "done"


def _seed_task_devflow(repo_root: Path, dest_devflow: Path, record: TaskRecord, copy_config: bool) -> None:
    dest_devflow.mkdir(parents=True, exist_ok=True)
    src = repo_root / ".devflow"
    if copy_config and src.is_dir():
        for name in ("project.yaml", "redlines.yaml"):
            item = src / name
            if item.is_file():
                shutil.copy2(item, dest_devflow / name)
        rules = src / "rules"
        if rules.is_dir():
            shutil.copytree(rules, dest_devflow / "rules", dirs_exist_ok=True)
    (dest_devflow / "task.yaml").write_text(render_task_yaml(record), encoding="utf-8")
    ctx = {
        "task_id": record.task_id,
        "current_phase": "classify",
        "current_agent": "manager",
        "cwd": record.worktree,
        "project_root": str(repo_root),
        "repo_root": str(repo_root),
        "task_root": str(dest_devflow),
        "branch": record.branch,
    }
    (dest_devflow / "context.json").write_text(
        json.dumps(ctx, indent=2) + "\n", encoding="utf-8"
    )


def create_task(
    start_path: Path,
    description: str,
    kind: str,
    base_ref: Optional[str] = None,
    parent_task_id: Optional[str] = None,
    source_task_id: Optional[str] = None,
) -> TaskRecord:
    """Create a task in-place, or isolate a latercomer in a worktree.

    The first unfinished task occupies the main workspace. A second formal
    task that would take the working tree gets an external worktree so the
    in-progress demand is not moved.
    """
    root = _repo_root(start_path.resolve())
    isolate = _active_in_place_task(root)
    if not isolate:
        _ensure_clean(root)
    ref = base_ref or _git(root, "branch", "--show-current") or "HEAD"
    base_commit = _git(root, "rev-parse", f"{ref}^{{commit}}")
    task_id = f"{_slugify(description) or 'task'}-{uuid.uuid4().hex[:6]}"
    branch_prefix = "fix" if kind == "bugfix" else kind
    branch = f"{branch_prefix}/{task_id}"
    worktree = (
        root.parent / ".devflow-worktrees" / root.name / task_id
        if isolate
        else root
    )
    if isolate:
        if worktree.exists():
            raise WorktreeError(f"task worktree already exists: {worktree}")
        worktree.parent.mkdir(parents=True, exist_ok=True)

    record = TaskRecord(
        task_id=task_id,
        slug=_slugify(description) or "task",
        kind=kind,
        description=description,
        base_ref=ref,
        base_commit=base_commit,
        branch=branch,
        worktree=str(worktree.resolve()),
        parent_task_id=parent_task_id,
        source_task_id=source_task_id,
    )

    try:
        if isolate:
            _git(root, "worktree", "add", "-b", branch, str(worktree), base_commit)
            _seed_task_devflow(root, worktree / ".devflow", record, copy_config=True)
        else:
            _git(root, "checkout", "-b", branch, base_commit)
            _seed_task_devflow(root, root / ".devflow", record, copy_config=False)
        return record
    except Exception:
        if isolate:
            try:
                _git(root, "worktree", "remove", "--force", str(worktree))
            except WorktreeError:
                pass
        else:
            try:
                current = _git(root, "branch", "--show-current")
                if current == branch:
                    _git(root, "checkout", "--force", ref)
                _git(root, "branch", "-D", branch)
            except WorktreeError:
                pass
        raise


def discover_tasks(root: Path) -> list[TaskRecord]:
    """Read all task records belonging to the repository's managed worktrees."""
    records = []
    for path in find_task_files(_repo_root(root.resolve())):
        try:
            from task_state import load_task
            records.append(load_task(path))
        except (OSError, ValueError):
            continue
    return records
