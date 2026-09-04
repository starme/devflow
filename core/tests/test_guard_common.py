#!/usr/bin/env python3
"""Unit tests for worktree mapping and shell write-target extraction."""
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS))

from devflow_guard_common import (  # noqa: E402
    _extract_shell_write_targets,
    _newest_plugin_dir,
    detect_worktree,
)


class DetectWorktreeTest(unittest.TestCase):
    def test_task_worktree_main_root_is_git_repo_not_worktrees_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            repo = home / "myapp"
            repo.mkdir()
            wt = home / ".devflow-worktrees" / "myapp" / "task-abc"
            (wt / ".devflow").mkdir(parents=True)
            (wt / ".devflow" / "task.yaml").write_text(
                "task:\n  id: task-abc\n", encoding="utf-8"
            )
            src = wt / "server" / "main.go"
            src.parent.mkdir()
            src.write_text("package main\n", encoding="utf-8")

            wt_root, main_root = detect_worktree(str(src))
            self.assertEqual(Path(wt_root).resolve(), wt.resolve())
            self.assertEqual(Path(main_root).resolve(), repo.resolve())

    def test_in_place_task_yaml_is_not_an_external_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "repo"
            (repo / ".devflow").mkdir(parents=True)
            (repo / ".devflow" / "task.yaml").write_text(
                "task:\n  id: in-place\n", encoding="utf-8"
            )
            wt_root, main_root = detect_worktree(str(repo / "src"))
            self.assertIsNone(wt_root)
            self.assertIsNone(main_root)


class ShellWriteTargetsTest(unittest.TestCase):
    def test_cp_and_mv_destinations_are_extracted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            targets = {
                rel
                for rel, _ in _extract_shell_write_targets(
                    "cp notes.txt .env && mv bak .devflow/redlines.yaml",
                    root,
                    cwd=str(root),
                )
            }
            self.assertIn(".env", targets)
            self.assertIn(".devflow/redlines.yaml", targets)

    def test_python_c_quoted_paths_are_extracted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            targets = {
                rel
                for rel, _ in _extract_shell_write_targets(
                    "python3 -c \"open('.env','w').write('x')\"",
                    root,
                    cwd=str(root),
                )
            }
            self.assertIn(".env", targets)

    def test_git_apply_reads_plus_plus_plus_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            patch = root / "secret.patch"
            patch.write_text(
                "--- a/.env\n+++ b/.env\n@@\n-old\n+new\n",
                encoding="utf-8",
            )
            targets = {
                rel
                for rel, _ in _extract_shell_write_targets(
                    "git apply secret.patch",
                    root,
                    cwd=str(root),
                )
            }
            self.assertIn(".env", targets)


class NewestPluginDirTest(unittest.TestCase):
    def test_picks_highest_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            v1 = Path(temp_dir) / "1.0.0"
            v2 = Path(temp_dir) / "1.1.0"
            v1.mkdir()
            v2.mkdir()
            self.assertEqual(_newest_plugin_dir([str(v1), str(v2)]), str(v2))


if __name__ == "__main__":
    unittest.main()
