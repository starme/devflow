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

from task_state import RepoEndpoint, TaskRecord, _read_scalar, find_task_files, render_task_yaml


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


def _workspace_snapshot(repo_root: Path) -> dict:
    """Read workspace paths from project.yaml (legacy: manifest.yaml)."""
    ws = {"root": str(repo_root), "backend": "", "frontend": ""}
    for name in ("project.yaml", "manifest.yaml"):
        path = repo_root / ".devflow" / name
        if not path.is_file():
            continue
        current = None
        try:
            for raw in path.read_text(encoding="utf-8").splitlines():
                stripped = raw.strip()
                indent = len(raw) - len(raw.lstrip())
                if indent == 0 and stripped == "workspace:":
                    current = "workspace"
                    continue
                if current == "workspace" and indent == 0 and stripped.endswith(":"):
                    break
                if current == "workspace" and indent == 2 and ":" in stripped:
                    key, _, val = stripped.partition(":")
                    key, val = key.strip(), val.strip().strip("\"'")
                    if key == "root" and val:
                        ws["root"] = val
                    elif key in ("backend", "frontend"):
                        current = key
                        if val:
                            ws[key] = val
                elif current in ("backend", "frontend") and indent >= 4 and stripped.startswith("path:"):
                    ws[current] = stripped.split(":", 1)[1].strip().strip("\"'")
                    current = "workspace"
        except OSError:
            continue
        break
    return ws


def _resolve_endpoints(repo_root: Path) -> list[dict]:
    """Resolve the multi-repo endpoints declared in ``project.yaml``.

    Returns a list of ``{track, git_root, remote, base_branch}`` dicts, or an
    empty list when the project is single-repo (no ``workspaces:`` section).
    ``git_root`` is resolved relative to ``repo_root`` so a separated
    frontend repository referenced as ``../frontend`` lands outside the anchor.
    """
    path = repo_root / ".devflow" / "project.yaml"
    if not path.is_file():
        return []
    endpoints: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    in_workspaces = False
    current: dict = {}
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent == 0 and stripped == "workspaces:":
            in_workspaces = True
            current = {}
            continue
        if in_workspaces:
            if indent == 0 and stripped.endswith(":"):
                break
            if indent == 2 and stripped.startswith("- "):
                if current:
                    endpoints.append(current)
                # ``- track: "frontend"`` → track value after the first colon
                _, _, track_val = stripped[2:].partition(":")
                current = {"track": track_val.strip().strip("\"'")}
                continue
            if indent >= 4 and current is not None and ":" in stripped:
                key, _, val = stripped.partition(":")
                key = key.strip()
                val = val.strip().strip("\"'")
                if key in ("git_root", "remote", "base_branch") and val:
                    current[key] = val
    if current:
        endpoints.append(current)

    resolved = []
    for ep in endpoints:
        track = ep.get("track", "")
        raw_root = ep.get("git_root", "")
        if not track or not raw_root:
            continue
        git_root = Path(raw_root)
        if not git_root.is_absolute():
            git_root = repo_root / git_root
        resolved.append({
            "track": track,
            "git_root": str(git_root.resolve()),
            "remote": ep.get("remote", "origin"),
            "base_branch": ep.get("base_branch", ""),
        })
    return resolved


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
        "workspace": _workspace_snapshot(repo_root),
    }
    if record.endpoints:
        ctx["endpoints"] = [
            {
                "track": ep.track,
                "git_root": ep.git_root,
                "branch": ep.branch,
                "base_ref": ep.base_ref,
                "base_commit": ep.base_commit,
            }
            for ep in record.endpoints
        ]
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

    Multi-repo projects (a ``workspaces:`` list in ``project.yaml``) create the
    same feature branch across every endpoint repository; each endpoint freezes
    its own ``base_commit``. The anchor repository (where ``.devflow/`` lives)
    also gets the in-place checkout or the latercomer worktree.
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

    endpoints = _build_endpoints(root, branch, base_ref)
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
        endpoints=tuple(endpoints),
    )

    created_branches: list[tuple[Path, str, str]] = []
    try:
        if isolate:
            _git(root, "worktree", "add", "-b", branch, str(worktree), base_commit)
            _seed_task_devflow(root, worktree / ".devflow", record, copy_config=True)
        else:
            _git(root, "checkout", "-b", branch, base_commit)
            _seed_task_devflow(root, root / ".devflow", record, copy_config=False)
        for ep in endpoints:
            _git(Path(ep.git_root), "checkout", "-b", branch, ep.base_commit)
            created_branches.append((Path(ep.git_root), branch, ep.base_ref))
        return record
    except Exception:
        for ep_root, ep_branch, ep_ref in reversed(created_branches):
            try:
                _git(ep_root, "checkout", "--force", ep_ref)
                _git(ep_root, "branch", "-D", ep_branch)
            except WorktreeError:
                pass
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


def _build_endpoints(root: Path, branch: str, base_ref: Optional[str]) -> list[RepoEndpoint]:
    """Resolve project endpoints and freeze each one's base commit.

    The anchor repository itself is not re-listed as an endpoint — endpoints are
    the *additional* repositories a multi-repo task spans. Each endpoint shares
    the task's branch name but freezes its own base commit.
    """
    endpoints = []
    for ep in _resolve_endpoints(root):
        ep_root = Path(ep["git_root"])
        if ep_root == root:
            continue
        try:
            ep_ref = base_ref or ep.get("base_branch") or _git(ep_root, "branch", "--show-current") or "HEAD"
            ep_commit = _git(ep_root, "rev-parse", f"{ep_ref}^{{commit}}")
        except WorktreeError:
            raise
        endpoints.append(RepoEndpoint(
            track=ep["track"],
            git_root=str(ep_root),
            base_ref=ep_ref,
            base_commit=ep_commit,
            branch=branch,
        ))
    return endpoints


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
