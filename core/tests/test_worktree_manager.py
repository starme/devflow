#!/usr/bin/env python3
"""Tests for isolated DevFlow task state and Git worktree creation."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

ORCHESTRATOR = Path(__file__).resolve().parents[1] / "orchestrator"
sys.path.insert(0, str(ORCHESTRATOR))

from task_state import TaskRecord, load_task, render_task_yaml  # noqa: E402
from worktree_manager import WorktreeError, create_task, discover_tasks  # noqa: E402


class TaskStateTest(unittest.TestCase):
    def test_render_and_load_round_trip(self):
        record = TaskRecord(
            task_id="fix-login-a1b2",
            slug="fix-login",
            kind="bugfix",
            description="Fix login timeout",
            base_ref="main",
            base_commit="abc123",
            branch="fix/fix-login-a1b2",
            worktree="/tmp/fix-login-a1b2",
            source_task_id="feature-login-old",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "task.yaml"
            path.write_text(render_task_yaml(record), encoding="utf-8")
            self.assertEqual(load_task(path), record)


class WorktreeManagerTest(unittest.TestCase):
    def _repository(self, temp_dir, name="repo"):
        root = Path(temp_dir) / name
        root.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        (root / "README.md").write_text("initial\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
        subprocess.run(
            ["git", "-c", "user.name=DevFlow", "-c", "user.email=devflow@example.invalid", "commit", "-qm", "initial"],
            cwd=root,
            check=True,
        )
        return root

    def test_first_task_is_in_place_second_gets_worktree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._repository(temp_dir)
            feature = create_task(root, "Add weekly report", "feature")
            bugfix = create_task(root, "Fix completed report bug", "bugfix", source_task_id=feature.task_id)

            self.assertEqual(Path(feature.worktree).resolve(), root.resolve())
            self.assertIn(".devflow-worktrees", bugfix.worktree)
            self.assertNotEqual(feature.branch, bugfix.branch)
            self.assertEqual(feature.base_commit, bugfix.base_commit)
            self.assertEqual(load_task(root / ".devflow" / "task.yaml").kind, "feature")
            self.assertEqual(load_task(Path(bugfix.worktree) / ".devflow" / "task.yaml").source_task_id, feature.task_id)
            self.assertEqual({record.task_id for record in discover_tasks(root)}, {feature.task_id, bugfix.task_id})

    def test_context_json_includes_workspace_from_project_yaml(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._repository(temp_dir)
            (root / ".devflow").mkdir(exist_ok=True)
            (root / ".devflow" / "project.yaml").write_text(
                "workspace:\n"
                "  root: \".\"\n"
                "  backend:\n"
                "    path: \"server\"\n"
                "  frontend:\n"
                "    path: \"web\"\n",
                encoding="utf-8",
            )
            record = create_task(root, "Add workspace context", "feature")
            ctx = json.loads((root / ".devflow" / "context.json").read_text(encoding="utf-8"))
            self.assertEqual(ctx["workspace"]["backend"], "server")
            self.assertEqual(ctx["workspace"]["frontend"], "web")
            self.assertEqual(ctx["task_id"], record.task_id)

    def test_dirty_in_place_task_does_not_block_latercomer_worktree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._repository(temp_dir)
            feature = create_task(root, "Add weekly report", "feature")
            (root / "README.md").write_text("wip\n", encoding="utf-8")
            bugfix = create_task(root, "Prod hotfix", "bugfix", source_task_id=feature.task_id)
            self.assertIn(".devflow-worktrees", bugfix.worktree)
            self.assertTrue((Path(bugfix.worktree) / ".devflow" / "task.yaml").is_file())

    def test_untracked_files_do_not_block_task_creation(self):
        # AC-15: an untracked file (e.g. a prior task's unpublished artifacts)
        # must not block creating a new task worktree.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._repository(temp_dir)
            (root / "uncommitted.txt").write_text("do not copy\n", encoding="utf-8")
            record = create_task(root, "Safe task", "feature")
            self.assertEqual(record.kind, "feature")

    def test_tracked_modifications_block_task_creation(self):
        # A change to an already-tracked file (M) is a real uncommitted change
        # and must still block worktree creation.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._repository(temp_dir)
            (root / "README.md").write_text("modified\n", encoding="utf-8")
            with self.assertRaises(WorktreeError):
                create_task(root, "Unsafe task", "feature")

    def test_tracked_additions_block_task_creation(self):
        # A newly staged/added tracked file (A) is a committed-change conflict.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._repository(temp_dir)
            (root / "extra.txt").write_text("staged\n", encoding="utf-8")
            subprocess.run(["git", "add", "extra.txt"], cwd=root, check=True)
            with self.assertRaises(WorktreeError):
                create_task(root, "Unsafe task", "feature")

    def test_ignored_files_do_not_block_task_creation(self):
        # Ignored files (!!) are invisible to the dirty check and must not block.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._repository(temp_dir)
            (root / ".gitignore").write_text("*.log\n", encoding="utf-8")
            subprocess.run(["git", "add", ".gitignore"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=DevFlow",
                 "-c", "user.email=devflow@example.invalid",
                 "commit", "-qm", "gitignore"],
                cwd=root, check=True,
            )
            (root / "debug.log").write_text("ignored\n", encoding="utf-8")
            record = create_task(root, "Ignored task", "feature")
            self.assertEqual(record.kind, "feature")

    def _multi_repo_fixture(self, temp_dir):
        """Create an anchor backend repo plus a separated frontend repo, and a
        ``project.yaml`` declaring the ``workspaces:`` endpoint list."""
        anchor = self._repository(temp_dir, name="backend")
        frontend = self._repository(temp_dir, name="frontend")
        (anchor / ".devflow").mkdir(exist_ok=True)
        (anchor / ".devflow" / "project.yaml").write_text(
            "workspaces:\n"
            f"  - track: \"backend\"\n"
            f"    git_root: \"{anchor}\"\n"
            f"  - track: \"frontend\"\n"
            f"    git_root: \"{frontend}\"\n",
            encoding="utf-8",
        )
        return anchor, frontend

    def test_multi_repo_creates_same_branch_in_each_endpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            anchor, frontend = self._multi_repo_fixture(temp_dir)
            record = create_task(anchor, "Cross repo feature", "feature")

            # Anchor (where .devflow lives) is not re-listed as an endpoint.
            self.assertEqual(len(record.endpoints), 1)
            ep = record.endpoints[0]
            self.assertEqual(ep.track, "frontend")
            self.assertEqual(ep.git_root, str(frontend.resolve()))
            self.assertEqual(ep.branch, record.branch)

            # Both repositories carry the same branch name.
            be_branches = subprocess.run(
                ["git", "branch", "--list", record.branch], cwd=anchor,
                text=True, capture_output=True, check=True,
            ).stdout.strip()
            fe_branches = subprocess.run(
                ["git", "branch", "--list", record.branch], cwd=frontend,
                text=True, capture_output=True, check=True,
            ).stdout.strip()
            self.assertIn(record.branch, be_branches)
            self.assertIn(record.branch, fe_branches)

            # Each endpoint froze its own base commit.
            self.assertTrue(ep.base_commit)

            # context.json carries the endpoint list.
            ctx = json.loads((anchor / ".devflow" / "context.json").read_text(encoding="utf-8"))
            self.assertEqual(len(ctx["endpoints"]), 1)
            self.assertEqual(ctx["endpoints"][0]["track"], "frontend")

    def test_multi_repo_rolls_back_endpoint_branch_on_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            anchor, frontend = self._multi_repo_fixture(temp_dir)
            # Break the frontend repo's git so the endpoint branch checkout fails.
            shutil.rmtree(frontend / ".git")
            with self.assertRaises(WorktreeError):
                create_task(anchor, "Broken cross repo", "feature")
            # The anchor's own branch must have been rolled back too.
            current = subprocess.run(
                ["git", "branch", "--show-current"], cwd=anchor,
                text=True, capture_output=True, check=True,
            ).stdout.strip()
            self.assertEqual(current, "main")


if __name__ == "__main__":
    unittest.main()
