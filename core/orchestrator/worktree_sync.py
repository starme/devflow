#!/usr/bin/env python3
"""DevFlow worktree artifact sync.

Claude Code's Task tool runs subagents in isolated git worktrees under
``.claude/worktrees/agent-<id>/``.  Agents write their ``.devflow/``
artifacts (scope.yaml, task reports, test reports, contracts, etc.) inside
their worktree, so these files do not automatically appear in the main
workspace.

This script is called by the Manager **after** one or more Task dispatches
complete.  It scans every worktree that has a ``.devflow/`` directory and
copies process artifacts back to the main workspace's ``.devflow/``.

Protected configuration (rules/, redlines.yaml, manifest.yaml, context.json)
is never overwritten — those belong to the main workspace and are read by
agents via the main workspace path.

Usage:
    python3 worktree_sync.py collect --root /path/to/project [--worktree /path/to/task-wt]
    python3 worktree_sync.py prepare --root /path/to/project --worktree /path/to/wt

Commands:
    collect   Recycle artifacts from ALL worktrees into main .devflow/
    prepare   Copy config (rules, redlines, manifest) from main to a worktree
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path


# Items that must NOT be copied back from a worktree (they are main-workspace
# configuration that agents should never modify).
_NEVER_COLLECT = frozenset({
    "redlines.yaml",
    "manifest.yaml",
    "context.json",
})
_NEVER_COLLECT_DIRS = frozenset({
    "rules",
})


def _is_collectable(rel_path):
    """Return True if *rel_path* (relative to .devflow/) should be collected
    from a worktree."""
    parts = Path(rel_path).parts
    if not parts:
        return False
    if parts[0] in _NEVER_COLLECT_DIRS:
        return False
    if parts[0] in _NEVER_COLLECT:
        return False
    return True


def find_worktrees(main_root):
    """Return a list of Path objects for all agent worktrees."""
    wt_dir = main_root / ".claude" / "worktrees"
    if not wt_dir.is_dir():
        return []
    worktrees = []
    try:
        for entry in sorted(wt_dir.iterdir()):
            if entry.is_dir() and entry.name.startswith("agent-"):
                worktrees.append(entry)
    except Exception:
        pass
    return worktrees


def _is_formal_task_worktree(worktree):
    """Return True when *worktree* lives inside the formal task worktree tree
    (``.devflow-worktrees/``).  ``collect`` only recycles *agent* worktrees
    under ``.claude/worktrees/agent-*``; formal task artifacts must be published
    explicitly via ``artifact_publish.py publish`` and never flattened here.
    """
    try:
        return ".devflow-worktrees" in Path(worktree).resolve().parts
    except Exception:
        return False


def collect_artifacts(main_root, worktree=None, dry_run=False):
    """Collect artifacts from one worktree, or legacy agent worktrees.

    Formal task worktrees (``.devflow-worktrees/``) are explicitly skipped —
    they are published to ``docs/tasks/<task-id>/`` by ``artifact_publish.py``,
    not flattened into the main ``.devflow/`` (AC-8, AC-11).
    """
    main_devflow = main_root / ".devflow"
    result = {"synced": [], "errors": []}

    if worktree and _is_formal_task_worktree(worktree):
        result["errors"].append(
            f"{Path(worktree).name}: formal task worktree, use "
            "artifact_publish.py publish"
        )
        return result

    worktrees = [Path(worktree).resolve()] if worktree else find_worktrees(main_root)

    for wt in worktrees:
        wt_devflow = wt / ".devflow"
        if not wt_devflow.is_dir():
            continue

        synced_files = []
        try:
            for src_path in sorted(wt_devflow.rglob("*")):
                if src_path.is_symlink() or not src_path.is_file():
                    continue
                try:
                    src_path.resolve().relative_to(wt_devflow.resolve())
                except ValueError:
                    continue
                rel = src_path.relative_to(wt_devflow)
                rel_str = str(rel).replace(os.sep, "/")
                if not _is_collectable(rel_str):
                    continue

                dst_path = main_devflow / rel
                if not dry_run:
                    dst_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(src_path), str(dst_path))
                synced_files.append(rel_str)
        except Exception as exc:
            result["errors"].append(f"{wt.name}: {exc}")
            continue

        if synced_files:
            result["synced"].append({
                "worktree": wt.name,
                "files": synced_files,
            })

    return result


def prepare_worktree(main_root, worktree_path, dry_run=False):
    """Copy essential DevFlow config from main workspace to a worktree so
    that guard hooks can find .devflow/ and load the correct context when
    the agent works inside the worktree.

    This copies: manifest.yaml, redlines.yaml, rules/, contracts/ (read-only
    references).  It does NOT copy context.json (each worktree gets its own
    runtime context written by the hooks).
    """
    main_devflow = main_root / ".devflow"
    wt_devflow = Path(worktree_path) / ".devflow"
    copied = []

    if not main_devflow.is_dir():
        return {"copied": copied, "error": "main .devflow/ not found"}

    config_items = ["manifest.yaml", "redlines.yaml", "rules", "contracts"]

    for item in config_items:
        src = main_devflow / item
        if not src.exists():
            continue
        dst = wt_devflow / item
        try:
            if not dry_run:
                if src.is_dir():
                    if dst.exists():
                        shutil.rmtree(str(dst))
                    shutil.copytree(str(src), str(dst))
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(src), str(dst))
            copied.append(item)
        except Exception as exc:
            return {"copied": copied, "error": f"{item}: {exc}"}

    return {"copied": copied}


def main():
    parser = argparse.ArgumentParser(description="DevFlow worktree sync")
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="Collect artifacts from worktrees")
    p_collect.add_argument("--root", required=True, help="Main workspace root")
    p_collect.add_argument("--worktree", help="Only collect from this task worktree")
    p_collect.add_argument("--dry-run", action="store_true")

    p_prep = sub.add_parser("prepare", help="Prepare a worktree with config")
    p_prep.add_argument("--root", required=True, help="Main workspace root")
    p_prep.add_argument("--worktree", required=True, help="Worktree path")
    p_prep.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    main_root = Path(args.root).resolve()

    if not main_root.is_dir():
        print(json.dumps({"error": f"root not found: {main_root}"}))
        sys.exit(1)

    if args.command == "collect":
        result = collect_artifacts(main_root, worktree=args.worktree, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["errors"]:
            sys.exit(1)
    elif args.command == "prepare":
        result = prepare_worktree(main_root, args.worktree, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if "error" in result:
            sys.exit(1)


if __name__ == "__main__":
    main()
