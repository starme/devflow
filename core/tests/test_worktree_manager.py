#!/usr/bin/env python3
"""Tests for isolated DevFlow task state and Git worktree creation."""
from __future__ import annotations

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
    def _repository(self, temp_dir):
        root = Path(temp_dir) / "repo"
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


if __name__ == "__main__":
    unittest.main()
