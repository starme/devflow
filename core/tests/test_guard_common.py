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
    _parse_workspaces,
    detect_worktree,
    infer_track,
    is_within_boundary,
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


class ArchiveSignalTest(unittest.TestCase):
    """archive gate helpers: task id parsing, archive index, git-commit matcher."""

    def _import(self):
        from devflow_guard_common import (
            _parse_task_id,
            is_git_commit,
            task_needs_archive,
        )
        return _parse_task_id, is_git_commit, task_needs_archive

    def test_parse_task_id_nested(self) -> None:
        _parse_task_id, _, _ = self._import()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".devflow").mkdir()
            (root / ".devflow" / "task.yaml").write_text(
                "task:\n  id: \"task-abc\"\n  kind: \"feature\"\n", encoding="utf-8"
            )
            self.assertEqual(_parse_task_id(root), "task-abc")

    def test_parse_task_id_missing(self) -> None:
        _parse_task_id, _, _ = self._import()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".devflow").mkdir()
            self.assertEqual(_parse_task_id(root), "")

    def test_task_needs_archive_without_index(self) -> None:
        _, _, task_needs_archive = self._import()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".devflow").mkdir()
            (root / ".devflow" / "task.yaml").write_text(
                "task:\n  id: \"task-abc\"\n", encoding="utf-8"
            )
            self.assertTrue(task_needs_archive(root))

    def test_task_needs_archive_false_after_index(self) -> None:
        _, _, task_needs_archive = self._import()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".devflow").mkdir()
            (root / ".devflow" / "task.yaml").write_text(
                "task:\n  id: \"task-abc\"\n", encoding="utf-8"
            )
            index = root / ".devflow" / "tasks" / "task-abc" / "README.md"
            index.parent.mkdir(parents=True)
            index.write_text("# x\n", encoding="utf-8")
            self.assertFalse(task_needs_archive(root))

    def test_task_needs_archive_legacy_no_task_yaml(self) -> None:
        _, _, task_needs_archive = self._import()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".devflow").mkdir()
            self.assertFalse(task_needs_archive(root))

    def test_is_git_commit(self) -> None:
        _, is_git_commit, _ = self._import()
        self.assertTrue(is_git_commit("git commit -m 'feat: x'"))
        self.assertTrue(is_git_commit("git commit --amend"))
        self.assertFalse(is_git_commit("git status"))
        self.assertFalse(is_git_commit("git push"))


class MultiRepoEndpointTest(unittest.TestCase):
    """Endpoint-based track boundary for separated backend/frontend repos."""

    def _workspace(self, temp_dir, anchor, frontend):
        anchor = Path(anchor)
        frontend = Path(frontend)
        (anchor / ".devflow").mkdir(parents=True, exist_ok=True)
        (anchor / ".devflow" / "project.yaml").write_text(
            "workspaces:\n"
            f"  - track: \"backend\"\n"
            f"    git_root: \"{anchor}\"\n"
            f"  - track: \"frontend\"\n"
            f"    git_root: \"{frontend}\"\n",
            encoding="utf-8",
        )
        return {
            "root": str(anchor),
            "backend": "",
            "frontend": "",
            "endpoints": [
                {"track": "backend", "git_root": str(anchor.resolve())},
                {"track": "frontend", "git_root": str(frontend.resolve())},
            ],
        }

    def test_infer_track_from_endpoint_git_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            anchor = Path(temp_dir) / "backend"
            frontend = Path(temp_dir) / "frontend"
            anchor.mkdir()
            frontend.mkdir()
            workspace = self._workspace(temp_dir, anchor, frontend)

            self.assertEqual(infer_track(str(frontend / "src" / "App.tsx"), workspace), "frontend")
            self.assertEqual(infer_track(str(anchor / "internal" / "main.go"), workspace), "backend")

    def test_is_within_boundary_uses_endpoint_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            anchor = Path(temp_dir) / "backend"
            frontend = Path(temp_dir) / "frontend"
            anchor.mkdir()
            frontend.mkdir()
            workspace = self._workspace(temp_dir, anchor, frontend)

            # backend agent may write within the backend repo root
            self.assertTrue(is_within_boundary(
                str(anchor / "internal" / "x.go"), workspace, "backend"))
            # backend agent may NOT write into the frontend repo
            self.assertFalse(is_within_boundary(
                str(frontend / "src" / "App.tsx"), workspace, "backend"))

    def test_parse_workspaces_resolves_relative_git_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            anchor = Path(temp_dir) / "backend"
            frontend = Path(temp_dir) / "frontend"
            anchor.mkdir()
            frontend.mkdir()
            (anchor / ".devflow").mkdir(parents=True)
            (anchor / ".devflow" / "project.yaml").write_text(
                "workspaces:\n"
                "  - track: \"backend\"\n"
                "    git_root: \".\"\n"
                "  - track: \"frontend\"\n"
                "    git_root: \"../frontend\"\n",
                encoding="utf-8",
            )
            endpoints = _parse_workspaces(anchor)
            self.assertEqual(len(endpoints), 2)
            self.assertEqual(endpoints[1]["track"], "frontend")
            self.assertEqual(endpoints[1]["git_root"], str(frontend.resolve()))


if __name__ == "__main__":
    unittest.main()
