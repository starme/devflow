#!/usr/bin/env python3
"""Create and discover isolated DevFlow task worktrees."""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import uuid

from typing import Optional

from task_state import TaskRecord, find_task_files, render_task_yaml


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


def _ensure_clean(root: Path) -> None:
    if _git(root, "status", "--porcelain"):
        raise WorktreeError(f"main workspace has uncommitted changes: {root}")


def create_task(
    start_path: Path,
    description: str,
    kind: str,
    base_ref: Optional[str] = None,
    parent_task_id: Optional[str] = None,
    source_task_id: Optional[str] = None,
) -> TaskRecord:
    """Create a unique branch, worktree, and task state atomically enough for CLI use."""
    root = _repo_root(start_path.resolve())
    _ensure_clean(root)
    ref = base_ref or _git(root, "branch", "--show-current") or "HEAD"
    base_commit = _git(root, "rev-parse", f"{ref}^{{commit}}")
    task_id = f"{_slugify(description) or 'task'}-{uuid.uuid4().hex[:6]}"
    branch_prefix = "fix" if kind == "bugfix" else kind
    branch = f"{branch_prefix}/{task_id}"
    worktree = root.parent / ".devflow-worktrees" / root.name / task_id
    if worktree.exists():
        raise WorktreeError(f"task worktree already exists: {worktree}")
    worktree.parent.mkdir(parents=True, exist_ok=True)

    try:
        _git(root, "worktree", "add", "-b", branch, str(worktree), base_commit)
        devflow = worktree / ".devflow"
        devflow.mkdir(parents=True, exist_ok=True)
        project_config = root / ".devflow" / "project.yaml"
        if project_config.is_file():
            shutil.copy2(project_config, devflow / "project.yaml")
        record = TaskRecord(
            task_id=task_id,
            slug=_slugify(description) or "task",
            kind=kind,
            description=description,
            base_ref=ref,
            base_commit=base_commit,
            branch=branch,
            worktree=str(worktree),
            parent_task_id=parent_task_id,
            source_task_id=source_task_id,
        )
        (devflow / "task.yaml").write_text(render_task_yaml(record), encoding="utf-8")
        return record
    except Exception:
        try:
            _git(root, "worktree", "remove", "--force", str(worktree))
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
