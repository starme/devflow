#!/usr/bin/env python3
"""Create DevFlow tasks in the main workspace and discover live task state."""

from __future__ import annotations

import re
import subprocess
import sys
import uuid
from pathlib import Path

from task_state import (
    RepoEndpoint,
    TaskRecord,
    _read_scalar,
    archive_task_state,
    find_task_files,
    render_task_yaml,
)

# ``core/workspace.py`` owns the single rule for project-root discovery; share
# it with the hooks so task creation and the guards name the same directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workspace import resolve_project_root as _discover_project_root


class WorktreeError(RuntimeError):
    """Raised when a task cannot be created safely."""


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


def _is_git(path: Path) -> bool:
    """True when *path* is inside a git work tree; False otherwise.

    Git is optional per directory, so this never raises — a missing repository
    or a missing ``git`` binary simply means "no version control here".
    """
    try:
        _git(path, "rev-parse", "--show-toplevel")
        return True
    except WorktreeError:
        return False


def _is_git_root(path: Path) -> bool:
    """True when *path* is itself the top level of a git work tree.

    ``_is_git`` is true for any subdirectory of a repository (``rev-parse``
    walks up); an endpoint must own its repository, so a directory that is
    merely nested inside another repository is not a usable endpoint.
    """
    try:
        top = Path(_git(path, "rev-parse", "--show-toplevel")).resolve()
        return top == Path(path).resolve()
    except WorktreeError:
        return False


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


def _active_in_place_task(root: Path, state_root: Path | None = None) -> bool:
    """True when the main workspace already holds an unfinished task.

    *state_root* is the directory owning ``.devflow/``; it differs from *root*
    when the repository is nested inside the project. Either location counts:
    a task left unfinished under the old location must still block a second
    in-place task, or the two would fight over the same branch.
    """
    candidates = [root]
    if state_root is not None and state_root != root:
        candidates.append(state_root)
    for base in candidates:
        path = base / ".devflow" / "task.yaml"
        if not path.is_file():
            continue
        try:
            status = _read_scalar(path.read_text(encoding="utf-8"), "status", "task")
        except OSError:
            return True
        if status != "done":
            return True
    return False


def _resolve_endpoints(project_root: Path) -> list[dict]:
    """Resolve the multi-repo endpoints declared in ``project.yaml``.

    Returns a list of ``{track, git_root, remote, base_branch}`` dicts, or an
    empty list when the project is single-repo (no ``workspaces:`` section).
    ``git_root`` is resolved relative to *project_root* — the workspace that
    owns ``.devflow/`` — so a frontend repository declared as ``./frontend``
    lands beside the anchor regardless of which repository started the task.
    """
    path = project_root / ".devflow" / "project.yaml"
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
            git_root = project_root / git_root
        resolved.append(
            {
                "track": track,
                "git_root": str(git_root.resolve()),
                "remote": ep.get("remote", "origin"),
                "base_branch": ep.get("base_branch", ""),
            }
        )
    return resolved


def _seed_task_devflow(dest_devflow: Path, record: TaskRecord) -> None:
    """Write the task's ``task.yaml`` into *dest_devflow*, snapshotting the old.

    v2 (ADR-0005): only ``task.yaml`` is written. The runtime
    ``context.json`` is retired — ``task.yaml`` (with ``git.endpoints`` for
    multi-repo tasks) is self-sufficient.

    Config files (``project.yaml`` / ``redlines.yaml`` / ``rules/``) are no
    longer copied: the only copy site was a latercomer worktree, and every task
    now works where that configuration already lives.
    """
    dest_devflow.mkdir(parents=True, exist_ok=True)
    # Snapshot the previous task before overwriting it: every task shares one
    # task.yaml, so without this the old id/branch/parent chain is gone the
    # moment the next task starts.
    archive_task_state(dest_devflow / "task.yaml")
    (dest_devflow / "task.yaml").write_text(render_task_yaml(record), encoding="utf-8")


def resolve_project_root(repo_root: Path) -> Path:
    """Return the directory that owns ``.devflow/`` for *repo_root*.

    Delegates to the shared resolver (``core/workspace.py``) so this agrees with
    the hooks: the root is *repo_root* itself when it contains ``.devflow/``,
    and there is no upward search.  A directory without its own ``.devflow/``
    falls back to itself so task creation still has a working directory; the
    init decision belongs to the caller, not here.
    """
    repo_root = repo_root.resolve()
    root = _discover_project_root(repo_root)
    return root if root is not None else repo_root


def create_task(
    start_path: Path,
    description: str,
    kind: str,
    base_ref: str | None = None,
    parent_task_id: str | None = None,
    source_task_id: str | None = None,
    title: str | None = None,
    project_root: Path | None = None,
) -> TaskRecord:
    """Create a task in-place, refusing when the workspace is already busy.

    Every task works in the main workspace on its own branch. A second formal
    task cannot share that checkout: both would write the same
    ``.devflow/task.yaml`` and edit the same files. Rather than moving a
    latercomer into an external worktree (retired — it only ever served a
    concurrency model the serial lifecycle does not provide), reject the
    request and let the caller finish or archive the active task first.

    Multi-repo projects (a ``workspaces:`` list in ``project.yaml``) create the
    same feature branch across every endpoint repository; each endpoint freezes
    its own ``base_commit``. The anchor repository (where ``.devflow/`` lives)
    gets the in-place checkout.

    *project_root* is the directory that owns ``.devflow/`` — the archive
    authority that ``artifact_publish`` publishes into. It defaults to
    ``resolve_project_root(repo_root)``.

    Git is optional per repository: neither the root nor an endpoint has to be
    a git repository.  When a directory is not under version control, branch
    creation and ``base_commit`` freezing are skipped for it and the task still
    records that directory as its ``working_dir``.  Skipping is announced via
    :func:`describe_git_skips` so the caller can surface it unless the project
    opted into silent skipping (``workspace.git_policy: auto_skip``).
    """
    start = start_path.resolve()
    # The root is the session's launch directory.  Resolve to the repository
    # top level only when the launch directory *is* that top level; a start
    # directory merely nested inside a repository is its own root (and has no
    # git of its own), never the parent repository.
    root = _repo_root(start) if _is_git_root(start) else start
    state_root = (project_root or resolve_project_root(root)).resolve()
    if _active_in_place_task(root, state_root):
        raise WorktreeError(
            "main workspace already holds an unfinished task; "
            "run /devflow next to finish or archive it before starting another"
        )
    root_is_git = _is_git_root(root)
    if root_is_git:
        _ensure_clean(root)
        ref = base_ref or _git(root, "branch", "--show-current") or "HEAD"
        base_commit = _git(root, "rev-parse", f"{ref}^{{commit}}")
    else:
        ref = base_ref or ""
        base_commit = ""
    task_id = f"{_slugify(description) or 'task'}-{uuid.uuid4().hex[:6]}"
    branch_prefix = "fix" if kind == "bugfix" else kind
    branch = f"{branch_prefix}/{task_id}"

    endpoints = _build_endpoints(root, branch, base_ref)
    record = TaskRecord(
        task_id=task_id,
        slug=_slugify(description) or "task",
        kind=kind,
        description=description,
        base_ref=ref,
        base_commit=base_commit,
        branch=branch,
        working_dir=str(root.resolve()),
        parent_task_id=parent_task_id,
        source_task_id=source_task_id,
        endpoints=tuple(endpoints),
        title=title or "",
    )

    created_branches: list[tuple[Path, str, str]] = []
    try:
        if root_is_git:
            _git(root, "checkout", "-b", branch, base_commit)
        for ep in endpoints:
            _git(Path(ep.git_root), "checkout", "-b", branch, ep.base_commit)
            created_branches.append((Path(ep.git_root), branch, ep.base_ref))
        # Write state only after every endpoint checkout succeeded: seeding
        # earlier leaves a task.yaml pointing at branches the rollback then
        # deletes, and the previous task's state already archived over it.
        # In-place state belongs to the project root, not the nested repo: it
        # is the same directory artifact_publish archives into.
        _seed_task_devflow(state_root / ".devflow", record)
        for message in describe_git_skips(state_root):
            print(f"[DevFlow] {message}")
        return record
    except Exception:
        for ep_root, ep_branch, ep_ref in reversed(created_branches):
            try:
                _git(ep_root, "checkout", "--force", ep_ref)
                _git(ep_root, "branch", "-D", ep_branch)
            except WorktreeError:
                pass
        if root_is_git:
            try:
                current = _git(root, "branch", "--show-current")
                if current == branch:
                    _git(root, "checkout", "--force", ref)
                _git(root, "branch", "-D", branch)
            except WorktreeError:
                pass
        raise


def _build_endpoints(root: Path, branch: str, base_ref: str | None) -> list[RepoEndpoint]:
    """Resolve project endpoints and freeze each one's base commit.

    The anchor repository itself is not re-listed as an endpoint — endpoints are
    the *additional* repositories a multi-repo task spans. Each endpoint shares
    the task's branch name but freezes its own base commit.

    A declared endpoint that is not a git repository is a configuration error,
    not an optional-git situation: ``workspaces:`` is an explicit intent to
    branch that repository, so a missing or broken repository raises rather than
    silently dropping cross-repo capability.
    """
    endpoints = []
    for ep in _resolve_endpoints(root):
        ep_root = Path(ep["git_root"])
        if ep_root == root:
            continue
        if not _is_git_root(ep_root):
            raise WorktreeError(
                f"declared workspace endpoint is not a git repository root: {ep_root}"
            )
        ep_ref = base_ref or ep.get("base_branch") or _git(
            ep_root, "branch", "--show-current"
        )
        ep_ref = ep_ref or "HEAD"
        ep_commit = _git(ep_root, "rev-parse", f"{ep_ref}^{{commit}}")
        endpoints.append(
            RepoEndpoint(
                track=ep["track"],
                git_root=str(ep_root),
                base_ref=ep_ref,
                base_commit=ep_commit,
                branch=branch,
            )
        )
    return endpoints


def describe_git_skips(project_root: Path) -> list[str]:
    """Return the messages to surface when git operations were skipped.

    Only the project root can be non-git by design (a pure aggregation
    directory).  Declared endpoints must be git repositories — ``_build_endpoints``
    raises for those — so this reports the root only.

    ``workspace.git_policy: auto_skip`` in ``project.yaml`` suppresses the
    report (explicit opt-in to silence); anything else, including an absent
    config, defaults to reporting.  The skip is never silent without that
    opt-in.
    """
    root = resolve_project_root(project_root) or Path(project_root).resolve()
    project_file = root / ".devflow" / "project.yaml"
    try:
        policy = _read_scalar(project_file.read_text(encoding="utf-8"), "git_policy", "workspace")
    except OSError:
        policy = None
    if (policy or "").strip().strip("\"'") == "auto_skip":
        return []
    if _is_git_root(root):
        return []
    return [f"not a git repository: {root} (no branch, no base_commit)"]


def discover_tasks(root: Path) -> list[TaskRecord]:
    """Read the live task record(s) for the repository.

    At most one task is unfinished at a time, so this normally returns a single
    record. State recorded under the project root counts too: that is where
    in-place tasks live when the repository is nested inside the project.
    Legacy ``.devflow-worktrees/`` task state still appears until it is
    archived (read-only compatibility).
    """
    resolved = root.resolve()
    repo_root = _repo_root(resolved) if _is_git_root(resolved) else resolved
    records = []
    for path in find_task_files(repo_root, state_root=resolve_project_root(repo_root)):
        try:
            from task_state import load_task

            records.append(load_task(path))
        except (OSError, ValueError):
            continue
    return records
