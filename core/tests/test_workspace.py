#!/usr/bin/env python3
"""Tests for the shared project-root resolver (core/workspace.py).

Root model (see the module docstring):

* Root = the ONE directory the session starts in, when it owns ``.devflow/``.
* No upward/downward substitution: if the launch dir has no ``.devflow``, the
  session is uninitialised — no child, parent, or process cwd may stand in.
* ``CLAUDE_PROJECT_DIR`` (fixed) wins over the drifting stdin ``cwd``.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CORE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CORE))

from workspace import (
    resolve_project_root,
    resolve_session_project_root,
    session_launch_dir,
)


def _make_root(path: Path) -> Path:
    (path / ".devflow").mkdir(parents=True, exist_ok=True)
    return path


class ResolveProjectRootTest(unittest.TestCase):
    def test_directory_owning_devflow_is_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = _make_root(Path(td) / "ws")
            self.assertEqual(resolve_project_root(root), root.resolve())

    def test_directory_without_devflow_is_none(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plain = Path(td) / "plain"
            plain.mkdir()
            self.assertIsNone(resolve_project_root(plain))

    def test_child_without_devflow_does_not_adopt_ancestor(self) -> None:
        # The central rule: "drill down, never up". An ancestor workspace's
        # .devflow must not capture a child repository that has none.
        with tempfile.TemporaryDirectory() as td:
            ws = _make_root(Path(td) / "ws")
            child = ws / "repo-a"
            child.mkdir()
            self.assertIsNone(resolve_project_root(child))
            self.assertEqual(resolve_project_root(ws), ws.resolve())

    def test_child_with_own_devflow_is_its_own_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = _make_root(Path(td) / "ws")
            child = _make_root(ws / "repo-a")
            self.assertEqual(resolve_project_root(child), child.resolve())


class SessionLaunchDirTest(unittest.TestCase):
    def test_env_wins_and_empty_payload_is_not_substituted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "ws"
            ws.mkdir()
            with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(ws)}):
                self.assertEqual(session_launch_dir("/tmp/payload"), ws.resolve())
                self.assertEqual(session_launch_dir(None), ws.resolve())

    def test_env_unset_payload_wins_over_process_cwd(self) -> None:
        # Regression: process cwd used to become the FIRST candidate when env
        # was unset, silently outranking the payload cwd.
        with tempfile.TemporaryDirectory() as td:
            payload = Path(td) / "payload"
            payload.mkdir()
            elsewhere = Path(td) / "elsewhere"
            elsewhere.mkdir()
            with (
                mock.patch.dict(os.environ, {}, clear=False),
                mock.patch("pathlib.Path.cwd", return_value=elsewhere),
            ):
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
                self.assertEqual(session_launch_dir(payload), payload.resolve())

    def test_process_cwd_only_when_both_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td) / "cwd"
            cwd.mkdir()
            with (
                mock.patch.dict(os.environ, {}, clear=False),
                mock.patch("pathlib.Path.cwd", return_value=cwd),
            ):
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
                self.assertEqual(session_launch_dir(None), cwd.resolve())


class SessionRootTest(unittest.TestCase):
    def test_claude_project_dir_wins_over_drifting_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = _make_root(Path(td) / "ws")
            drifted = ws / "repo-a" / "src"
            drifted.mkdir(parents=True)
            with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(ws)}):
                self.assertEqual(resolve_session_project_root(drifted), ws.resolve())

    def test_falls_back_to_payload_cwd_when_no_env(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = _make_root(Path(td) / "solo")
            with (
                mock.patch.dict(os.environ, {}, clear=False),
                mock.patch("pathlib.Path.cwd", return_value=Path(td)),
            ):
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
                self.assertEqual(resolve_session_project_root(root), root.resolve())

    def test_launch_dir_without_devflow_is_uninitialised_even_if_process_has_one(self) -> None:
        # P0 regression: a hook process started in a directory that has
        # .devflow must NOT make an uninitialised session look initialised.
        with tempfile.TemporaryDirectory() as td:
            plain = Path(td) / "plain"
            plain.mkdir()
            process_cwd = _make_root(Path(td) / "plugin-with-devflow")
            with (
                mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(plain)}),
                mock.patch("pathlib.Path.cwd", return_value=process_cwd),
            ):
                self.assertIsNone(resolve_session_project_root(plain))

    def test_launch_dir_without_devflow_does_not_adopt_child_with_one(self) -> None:
        # P1 regression: env points at an uninitialised launch dir; a drifted
        # payload cwd sits inside a child that HAS .devflow. The session must
        # stay uninitialised, not silently adopt the child.
        with tempfile.TemporaryDirectory() as td:
            launch = Path(td) / "launch"
            launch.mkdir()
            child = _make_root(launch / "child")
            with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(launch)}):
                self.assertIsNone(resolve_session_project_root(child))

    def test_returns_none_when_nothing_owns_devflow(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plain = Path(td) / "plain"
            plain.mkdir()
            with (
                mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(plain)}),
                mock.patch("pathlib.Path.cwd", return_value=plain),
            ):
                self.assertIsNone(resolve_session_project_root(plain))


if __name__ == "__main__":
    unittest.main()