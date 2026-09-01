#!/usr/bin/env python3
"""Publish completed formal task artifacts into the project archive root.

DevFlow runs formal tasks in isolated worktrees at
``<repo_root.parent>/.devflow-worktrees/<repo>/<task-id>/``.  Artifacts written
there (PRD, architecture, scope, test/acceptance reports) stay inside the
worktree.  This module publishes them, on explicit milestone gates, into a
per-task namespace under the project's archive root::

    <project_root>/.devflow/tasks/<task-id>/
        README.md                      # source index (task metadata + artifact map)
        prd-<task-slug>.md             # PRD published under a semantic name
        architecture.md
        test_reports/
        ...

The archive root derives from ``project_root`` (the directory holding
``.devflow/``), while the task worktree location derives from ``repo_root``
(the git repository root).  These two authorities are orthogonal and are passed
in explicitly (``--root`` and ``--repo-root`` on the CLI), never inferred from a
single ambiguous root — form A (project_root == repo_root) and form B
(project_root == repo_root.parent) both resolve correctly.

``collect`` (``worktree_sync.py``) keeps recycling *agent* worktrees under
``.claude/worktrees/agent-*``; ``publish`` here only handles *formal* tasks.
The two never cross: ``collect`` must not flatten formal task artifacts into
``.devflow/``, and ``publish`` must not touch agent worktrees.

Publishing is idempotent and content-addressed: an identical target is skipped,
a differing target is *refused* (never last-writer-wins), and already-published
files are never rolled back.  The module is split into pure, testable functions
(the top half) and a thin ``__main__`` CLI (the bottom half).

Usage:
    python3 artifact_publish.py publish --root <project_root> --repo-root <repo_root> --task <id>
    python3 artifact_publish.py publish --root <project_root> --repo-root <repo_root> --worktree <path>
    python3 artifact_publish.py publish --root <project_root> --repo-root <repo_root> --all-tasks [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from task_state import find_task_files, load_task


# ---------------------------------------------------------------------------
# Publish whitelist
# ---------------------------------------------------------------------------

# Artifact files (relative to a task worktree's ``.devflow/``) that may be
# published.  ``project.yaml`` / ``context.json`` / ``manifest.yaml`` /
# ``rules/`` / ``runs/`` / ``contracts/`` / ``task.yaml`` are never published:
# ``task.yaml`` is task state (read, not copied), the rest are main-workspace
# config or read-only references.
PUBLISHABLE_ARTIFACTS = frozenset({
    "architecture.md",
    "scope.yaml",
    "diagnosis.md",
    "acceptance-report.md",
    "acceptance-scenarios.md",
    "test-report.md",
    "task-report.md",  # implementation report (declared dynamically via scope artifact contract)
    "prd.md",  # published as prd-<task-slug>.md
})

# Artifact directories (relative to ``.devflow/``) walked recursively on publish.
PUBLISHABLE_ARTIFACT_DIRS = frozenset({
    "test_reports",
})

# PRD is the only artifact renamed on publish.  Source (worktree) keeps the
# fixed name ``.devflow/prd.md``; the published target is ``prd-<slug>.md``.
_PRD_SOURCE = "prd.md"


def target_name(source_rel: str, meta: Dict[str, str]) -> str:
    """Return the published file name for *source_rel*.

    ``prd.md`` is the only renamed artifact (→ ``prd-<task-slug>.md``); every
    other artifact keeps its fixed name so scripts can locate it deterministically.
    """
    if source_rel == _PRD_SOURCE:
        return f"prd-{meta['slug']}.md"
    return source_rel


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _worktree_root(repo_root: Path, task_id: str) -> Path:
    """Return the formal task worktree directory for *task_id*."""
    return repo_root.parent / ".devflow-worktrees" / repo_root.name / task_id


def resolve_archive_root(project_root: Path) -> Path:
    """Return the archive root ``project_root/.devflow/tasks``.

    Form-independent: *project_root* is already the directory holding
    ``.devflow/`` (equal to repo_root in form A, repo_root.parent in form B),
    so no existence probing is needed.
    """
    return project_root / ".devflow" / "tasks"


def _is_formal_worktree(worktree: Path) -> bool:
    """Return True when *worktree* sits inside a ``.devflow-worktrees/`` tree."""
    parts = worktree.resolve().parts
    return ".devflow-worktrees" in parts


def _has_legal_task_yaml(worktree: Path) -> bool:
    """Return True when *worktree* contains a parseable ``.devflow/task.yaml``.

    Identification relies on ``task.yaml`` (via ``load_task``), never on the
    directory name.
    """
    task_file = worktree / ".devflow" / "task.yaml"
    if not task_file.is_file():
        return False
    try:
        load_task(task_file)
    except (OSError, ValueError):
        return False
    return True


def discover_task(
    repo_root: Path,
    task_id: Optional[str] = None,
    worktree: Optional[str] = None,
    all_tasks: bool = False,
) -> Path:
    """Locate a formal task worktree by precedence: ``--worktree``, ``--task``,
    then ``--all-tasks``.  Only a directory that is both inside the
    ``.devflow-worktrees/`` tree *and* contains a legal ``.devflow/task.yaml``
    is accepted — the directory name is never trusted on its own.

    *repo_root* is the worktree-location authority (the git repo root); it is
    independent of the archive root (``project_root``).
    """
    repo_root = repo_root.resolve()

    if worktree:
        candidate = Path(worktree).resolve()
        if not _is_formal_worktree(candidate):
            raise ValueError(f"worktree outside .devflow-worktrees/: {candidate}")
        if not _has_legal_task_yaml(candidate):
            raise ValueError(f"no legal .devflow/task.yaml in worktree: {candidate}")
        return candidate

    if task_id:
        candidate = _worktree_root(repo_root, task_id)
        if not _has_legal_task_yaml(candidate):
            raise ValueError(f"formal task worktree not found for task id: {task_id}")
        return candidate

    if all_tasks:
        task_files = find_task_files(repo_root)
        for task_file in task_files:
            worktree_dir = task_file.parent.parent
            if _has_legal_task_yaml(worktree_dir):
                return worktree_dir
        raise ValueError("no formal task worktrees found")

    raise ValueError("one of --task, --worktree, or --all-tasks is required")


def read_task_meta(worktree: Path) -> Dict[str, str]:
    """Extract the publish-relevant metadata from a worktree's ``task.yaml``."""
    record = load_task(worktree / ".devflow" / "task.yaml")
    return {
        "task_id": record.task_id,
        "slug": record.slug,
        "branch": record.branch,
        "base_ref": record.base_ref,
        "base_commit": record.base_commit,
        "kind": record.kind,
    }


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

# Sensitive/credential files that must never be published, regardless of source.
_SENSITIVE_PATTERNS = (
    ".env",
    ".pem",
    "secrets.",
    ".key",
)


def _is_sensitive_name(name: str) -> bool:
    """Return True for file names matching sensitive patterns.

    ``.env*``, ``*.pem``, ``secrets.*``, and ``*.key`` are all rejected.
    """
    lowered = name.lower()
    if lowered.startswith(".env"):
        return True
    if lowered.endswith(".pem"):
        return True
    if lowered.startswith("secrets."):
        return True
    if lowered.endswith(".key"):
        return True
    return False


def is_safe_source(src: Path, root: Path) -> bool:
    """Return True when *src* may be copied; False for symlinks, path escape,
    sensitive files, or anything resolving outside *root*.

    Symlinks (files *and* directories) are always refused and must never be
    followed.  Path escape is detected by comparing ``resolve()`` results.
    """
    try:
        if src.is_symlink():
            return False
        resolved = src.resolve()
        root_resolved = root.resolve()
        resolved.relative_to(root_resolved)
    except (OSError, ValueError):
        return False
    if _is_sensitive_name(src.name):
        return False
    return True


# ---------------------------------------------------------------------------
# Publishable file iteration
# ---------------------------------------------------------------------------

def iter_publishable_files(worktree: Path) -> List[str]:
    """Return the relative paths (forward slashes, relative to ``.devflow/``)
    of all publishable artifacts in *worktree*, sorted for determinism.

    Only whitelisted files are included; whitelisted directories are walked
    recursively.  Symlinks, sensitive files, and anything that escapes the
    ``.devflow/`` root are skipped.
    """
    devflow = worktree / ".devflow"
    root_resolved = devflow.resolve()
    found: List[str] = []

    for name in sorted(PUBLISHABLE_ARTIFACTS):
        candidate = devflow / name
        if candidate.is_file() and is_safe_source(candidate, devflow):
            found.append(name)

    for dirname in sorted(PUBLISHABLE_ARTIFACT_DIRS):
        candidate = devflow / dirname
        if not candidate.is_dir() or not is_safe_source(candidate, devflow):
            continue
        for src_path in sorted(candidate.rglob("*")):
            if not is_safe_source(src_path, devflow):
                continue
            if not src_path.is_file():
                continue
            rel = src_path.relative_to(devflow)
            found.append(str(rel).replace(os.sep, "/"))

    return found


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------

def content_hash(src: Path, root: Path) -> str:
    """Return a stable sha256 for *src*.

    A directory is hashed as its sorted relative-path set plus each file's
    hash, so filesystem enumeration order never causes a false conflict.
    """
    h = hashlib.sha256()
    if src.is_dir():
        root_resolved = root.resolve()
        entries = sorted(
            p for p in src.rglob("*")
            if p.is_file() and is_safe_source(p, root)
        )
        for path in entries:
            rel = path.relative_to(root_resolved).as_posix()
            h.update(rel.encode("utf-8"))
            h.update(b"\x00")
            h.update(_file_sha256(path))
            h.update(b"\x00")
    else:
        h.update(_file_sha256(src))
    return h.hexdigest()


def _file_sha256(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.digest()


# ---------------------------------------------------------------------------
# Publish planning
# ---------------------------------------------------------------------------

# action kinds
ACTION_CREATE = "create"
ACTION_SKIP = "skip"
ACTION_CONFLICT = "conflict"


def plan_publish(worktree: Path, target_dir: Path) -> Tuple[List[Dict[str, str]], Dict[str, str]]:
    """Plan publication of *worktree*'s artifacts into *target_dir*.

    Returns ``(actions, published_map)`` where each action describes the source,
    semantic target name, action (create/skip/conflict), and reason.  A target
    is skipped when its content hash matches the existing file (idempotent) and
    conflicts when content differs (refused, never overwritten).
    """
    devflow = worktree / ".devflow"
    meta = read_task_meta(worktree)
    publishable = iter_publishable_files(worktree)

    actions: List[Dict[str, str]] = []
    published_map: Dict[str, str] = {}

    for source_rel in publishable:
        name = target_name(source_rel, meta)
        src_path = devflow / source_rel
        dst_path = target_dir / name

        action: Dict[str, str] = {
            "source": source_rel,
            "target": name,
            "action": ACTION_CREATE,
        }

        if dst_path.exists():
            src_hash = content_hash(src_path, devflow)
            dst_hash = content_hash(dst_path, target_dir)
            if src_hash == dst_hash:
                action["action"] = ACTION_SKIP
                action["reason"] = "content unchanged"
            else:
                action["action"] = ACTION_CONFLICT
                action["reason"] = "target exists with different content"
        actions.append(action)

        # Record the semantic published path (``.devflow/tasks/<task-id>/<target>``)
        # for README / task.yaml references.
        published_map[source_rel] = f".devflow/tasks/{target_dir.name}/{name}"

    return actions, published_map


# ---------------------------------------------------------------------------
# README index
# ---------------------------------------------------------------------------

# Semantic artifact keys for the README index, in a stable order that is easy
# for humans and scripts to scan.  ``prd`` maps to the renamed PRD; the
# ``test_reports`` entry collapses the walked directory into one entry.
_README_ARTIFACT_KEYS = [
    ("prd.md", "prd"),
    ("architecture.md", "architecture"),
    ("scope.yaml", "scope"),
    ("diagnosis.md", "diagnosis"),
    ("acceptance-report.md", "acceptance_report"),
    ("acceptance-scenarios.md", "acceptance_scenarios"),
    ("test-report.md", "test_report"),
    ("task-report.md", "task_report"),
    ("test_reports/", "test_reports"),
]


def render_readme(meta: Dict[str, str], published_map: Dict[str, str]) -> str:
    """Render the machine-and-human readable source index for a task namespace.

    Absolute worktree paths are deliberately omitted (they break across
    machines); only stable task metadata and a semantic artifact map remain.
    ``published_map`` values are full ``.devflow/tasks/<id>/<target>`` paths;
    the README records just the target name (as in the 2.5 example) while
    keeping the semantic ``prd-<slug>.md`` name for the PRD.
    """
    artifact_lines = ""
    for prefix, key in _README_ARTIFACT_KEYS:
        source_rel, published = _match_artifact(prefix, published_map)
        if source_rel is None:
            continue
        # Record the target name within the task namespace, not the absolute
        # worktree path nor the ``.devflow/tasks/<id>/`` prefix.
        target_name = published.rsplit("/", 1)[-1]
        if key == "test_reports":
            target_name = "test_reports/"
        artifact_lines += f'  {key}: "{target_name}"\n'

    return (
        "# Task Artifacts\n"
        "\n"
        "```yaml\n"
        "source:\n"
        f'  task_id: "{meta["task_id"]}"\n'
        f'  slug: "{meta["slug"]}"\n'
        f'  branch: "{meta["branch"]}"\n'
        f'  base_ref: "{meta["base_ref"]}"\n'
        f'  base_commit: "{meta["base_commit"]}"\n'
        f'  kind: "{meta["kind"]}"\n'
        "artifacts:\n"
        f"{artifact_lines}"
        "```\n"
    )


def _match_artifact(
    prefix: str, published_map: Dict[str, str]
) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(source_rel, published)`` for the first entry whose relative
    path starts with *prefix* (collapsing ``test_reports/`` entries)."""
    for source_rel, published in published_map.items():
        if prefix.endswith("/"):
            if source_rel.startswith(prefix):
                return source_rel, published
        elif source_rel == prefix:
            return source_rel, published
    return None, None


# ---------------------------------------------------------------------------
# task.yaml artifact reference update
# ---------------------------------------------------------------------------

def _read_scalar_fields(content: str, section: str) -> Dict[str, str]:
    """Extract top-level scalar ``key: "value"`` fields from a YAML *section*.

    Only handles the ``artifacts:`` block's simple scalar entries (like
    ``delivery: ".devflow/delivery.yaml"``); nested maps/lists are ignored.
    """
    fields: Dict[str, str] = {}
    in_section = False
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0 and stripped == f"{section}:":
            in_section = True
            continue
        if in_section:
            if indent == 0 and stripped.endswith(":"):
                break
            if indent == 2 and ":" in stripped:
                key, _, value = stripped.partition(":")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if value in ("null", "~", ""):
                    continue
                fields[key] = value
    return fields


def update_task_artifact_refs(
    worktree: Path,
    task_id: str,
    slug: str,
    published_map: Dict[str, str],
) -> Path:
    """Rewrite the ``artifacts`` section of *worktree*'s ``.devflow/task.yaml``
    to the dual-path form (worktree + published).  Only the task's own worktree
    task.yaml is touched; the project-root ``.devflow/task.yaml`` is never
    created or written (AC-7).

    Existing non-publishable fields (notably ``delivery``, which points at the
    delivery sub-state, not a published artifact) are preserved unchanged; only
    publishable artifacts are upgraded to the scheme-A ``worktree`` +
    ``published`` form.  The rewrite is textual and preserves ``schema_version``
    and indentation.
    """
    task_file = worktree / ".devflow" / "task.yaml"
    content = task_file.read_text(encoding="utf-8")

    # Publishable artifact keys, in a stable order, mapped from their worktree
    # source file.  ``acceptance-report.md`` and ``acceptance-scenarios.md``
    # get distinct keys — emitting two entries under one key would produce
    # duplicate YAML keys, silently dropping the first reference.
    ordered = [
        ("prd.md", "prd"),
        ("architecture.md", "architecture"),
        ("scope.yaml", "scope"),
        ("test-report.md", "test_report"),
        ("acceptance-report.md", "acceptance_report"),
        ("acceptance-scenarios.md", "acceptance_scenarios"),
        ("diagnosis.md", "diagnosis"),
    ]

    # Preserve legacy scalar fields that are NOT publishable artifacts
    # (e.g. ``delivery``).  These are re-emitted as-is so delivery sub-state
    # recovery stays intact.
    preserved = _read_scalar_fields(content, "artifacts")
    preserved_lines: List[str] = []
    for key in ("delivery",):
        value = preserved.get(key)
        if value is not None:
            preserved_lines.append(f'  {key}: "{value}"')

    artifact_entries: List[str] = []
    for source_rel, key in ordered:
        published = published_map.get(source_rel)
        if not published:
            continue
        artifact_entries.append(
            f'  {key}:\n    worktree: ".devflow/{source_rel}"\n    published: "{published}"'
        )

    # ``test_reports/`` directory, if published, is recorded as a single ref
    # pointing at the directory (the walked file entries share its prefix).
    for source_rel in published_map:
        if source_rel.startswith("test_reports/"):
            first_published = published_map[source_rel]
            dir_published = first_published.rsplit("/", 1)[0] + "/"
            artifact_entries.append(
                f'  test_reports:\n    worktree: ".devflow/test_reports/"\n'
                f'    published: "{dir_published}"'
            )
            break

    # Preserved legacy fields come after the upgradable dual-path entries.
    artifact_entries.extend(preserved_lines)

    if not artifact_entries:
        return task_file

    artifacts_block = "artifacts:\n" + "\n".join(artifact_entries) + "\n"

    # Replace the existing ``artifacts:`` section (from its header to the next
    # top-level key) or append it when absent.
    lines = content.splitlines()
    start = None
    end = len(lines)
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "artifacts:":
            start = idx
            continue
        if start is not None and line and not line[0].isspace() and stripped.endswith(":"):
            end = idx
            break

    if start is None:
        if content and not content.endswith("\n"):
            content += "\n"
        rewritten = content + artifacts_block
    else:
        rewritten = "\n".join(lines[:start] + [artifacts_block.rstrip("\n")] + lines[end:])

    task_file.write_text(rewritten, encoding="utf-8")
    return task_file


# ---------------------------------------------------------------------------
# Publish command
# ---------------------------------------------------------------------------

def publish(
    project_root: Path,
    worktree: Path,
    dry_run: bool = False,
) -> Dict[str, object]:
    """Publish a single formal task's artifacts into
    ``<project_root>/.devflow/tasks/<task-id>/``.

    *project_root* is the archive authority (the dir holding ``.devflow/``);
    the worktree is already located via ``discover_task`` (which keys off
    ``repo_root``).  Returns a result dict with ``published`` / ``skipped`` /
    ``conflicts`` lists and an ``errors`` list.  Conflicts abort before any
    write so no partial publish occurs (atomic at the plan level); each file
    write is then idempotent and never overwrites a differing target.
    """
    meta = read_task_meta(worktree)
    task_id = meta["task_id"]
    target_dir = resolve_archive_root(project_root) / task_id

    actions, published_map = plan_publish(worktree, target_dir)

    result: Dict[str, object] = {
        "task_id": task_id,
        "published": [],
        "skipped": [],
        "conflicts": [],
        "errors": [],
    }

    conflicts = [a for a in actions if a["action"] == ACTION_CONFLICT]
    if conflicts:
        result["conflicts"] = [
            {"source": a["source"], "target": a["target"], "reason": a.get("reason", "")}
            for a in conflicts
        ]
        return result

    if dry_run:
        for a in actions:
            bucket = {
                ACTION_CREATE: "published",
                ACTION_SKIP: "skipped",
                ACTION_CONFLICT: "conflicts",
            }[a["action"]]
            result[bucket].append({"source": a["source"], "target": a["target"]})
        return result

    devflow = worktree / ".devflow"
    target_dir.mkdir(parents=True, exist_ok=True)

    for a in actions:
        source_rel = a["source"]
        name = a["target"]
        src_path = devflow / source_rel
        dst_path = target_dir / name

        if a["action"] == ACTION_SKIP:
            result["skipped"].append({"source": source_rel, "target": name})
            continue

        try:
            if not is_safe_source(src_path, devflow):
                result["errors"].append(f"{source_rel}: unsafe source")
                continue
            if src_path.is_dir():
                if dst_path.exists():
                    shutil.rmtree(str(dst_path))
                shutil.copytree(str(src_path), str(dst_path))
            else:
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src_path), str(dst_path))
            result["published"].append({"source": source_rel, "target": name})
        except OSError as exc:
            result["errors"].append(f"{source_rel}: {exc}")

    if not result["errors"]:
        readme = render_readme(meta, published_map)
        (target_dir / "README.md").write_text(readme, encoding="utf-8")
        update_task_artifact_refs(worktree, task_id, meta["slug"], published_map)

    return result


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="DevFlow formal task artifact publish")
    sub = parser.add_subparsers(dest="command", required=True)

    p_publish = sub.add_parser("publish", help="Publish task artifacts into .devflow/tasks/")
    p_publish.add_argument(
        "--root", required=True,
        help="Project root (= .devflow/ parent, the archive authority)",
    )
    p_publish.add_argument(
        "--repo-root", required=True,
        help="Git repository root (the worktree-location authority)",
    )
    group = p_publish.add_mutually_exclusive_group(required=True)
    group.add_argument("--task", help="Publish by task id")
    group.add_argument("--worktree", help="Publish by explicit worktree path")
    group.add_argument("--all-tasks", action="store_true", help="Publish the first discovered task")
    p_publish.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    project_root = Path(args.root).resolve()
    repo_root = Path(args.repo_root).resolve()

    if not project_root.is_dir():
        print(json.dumps({"error": f"root not found: {project_root}"}))
        return 1
    if not repo_root.is_dir():
        print(json.dumps({"error": f"repo root not found: {repo_root}"}))
        return 1

    try:
        worktree = discover_task(
            repo_root,
            task_id=args.task,
            worktree=args.worktree,
            all_tasks=args.all_tasks,
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1

    result = publish(project_root, worktree, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["errors"] or result["conflicts"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())