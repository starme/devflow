#!/usr/bin/env python3
"""Tests for the delivery orchestrator module (read-only probes + state)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ORCHESTRATOR = Path(__file__).resolve().parents[1] / "orchestrator"
sys.path.insert(0, str(ORCHESTRATOR))

import delivery  # noqa: E402
from delivery import DeliveryState  # noqa: E402


def _load_guard_whitelist() -> frozenset:
    """Load the guard hook's artifact whitelist for consistency checks."""
    hooks_dir = Path(__file__).resolve().parents[1] / "hooks"
    sys.path.insert(0, str(hooks_dir))
    import devflow_guard_common  # noqa: E402
    return frozenset(devflow_guard_common._DEVFLOW_ARTIFACT_FILES)


class GhAvailableTest(unittest.TestCase):
    def test_gh_available_true_when_authenticated_with_output(self):
        with mock.patch.object(delivery, "_run", return_value="Logged in to github.com"):
            self.assertTrue(delivery.gh_available())

    def test_gh_available_false_when_gh_missing(self):
        # "gh" not on PATH -> _run returns None (fail-safe)
        with mock.patch.object(delivery, "_run", return_value=None):
            self.assertFalse(delivery.gh_available())

    def test_gh_available_false_when_unauthenticated(self):
        # gh present but `gh auth status` exits non-zero -> _run returns None
        with mock.patch.object(delivery, "_run", return_value=None):
            self.assertFalse(delivery.gh_available())

    def test_gh_available_false_when_output_empty(self):
        # Regression: exit-0 but empty stdout must NOT count as authenticated.
        with mock.patch.object(delivery, "_run", return_value=""):
            self.assertFalse(delivery.gh_available())

    def test_gh_available_false_when_output_only_whitespace(self):
        with mock.patch.object(delivery, "_run", return_value="   \n\t"):
            self.assertFalse(delivery.gh_available())


class BranchPushedTest(unittest.TestCase):
    def test_branch_pushed_true_when_upstream_present(self):
        with mock.patch.object(delivery, "_run", return_value="origin/feature"):
            self.assertTrue(delivery.branch_pushed())

    def test_branch_pushed_false_when_no_upstream(self):
        with mock.patch.object(delivery, "_run", return_value=None):
            self.assertFalse(delivery.branch_pushed())

    def test_remote_name_returns_remote_part(self):
        with mock.patch.object(delivery, "_run", return_value="origin/feature/x"):
            self.assertEqual(delivery.remote_name(), "origin")

    def test_remote_name_none_when_no_upstream(self):
        with mock.patch.object(delivery, "_run", return_value=None):
            self.assertIsNone(delivery.remote_name())


class DirtyFilesTest(unittest.TestCase):
    def test_dirty_files_parses_porcelain_output(self):
        output = "M a.py\nA b.py\n?? c.py\n"
        with mock.patch.object(delivery, "_run", return_value=output):
            self.assertEqual(delivery.dirty_files(), ["M a.py", "A b.py", "?? c.py"])

    def test_dirty_files_empty_when_clean(self):
        with mock.patch.object(delivery, "_run", return_value=""):
            self.assertEqual(delivery.dirty_files(), [])

    def test_dirty_files_empty_when_git_missing(self):
        with mock.patch.object(delivery, "_run", return_value=None):
            self.assertEqual(delivery.dirty_files(), [])


class WhitelistConsistencyTest(unittest.TestCase):
    def test_delivery_artifacts_subset_of_guard_whitelist(self):
        guard = _load_guard_whitelist()
        self.assertTrue(delivery.DELIVERY_ARTIFACT_FILES.issubset(guard))

    def test_no_temporary_files_in_delivery_whitelist(self):
        for path in delivery.DELIVERY_ARTIFACT_FILES:
            self.assertFalse(path.endswith(".tmp"), path)
            self.assertFalse(path.endswith(".log"), path)
        self.assertNotIn(".devflow/context.json", delivery.DELIVERY_ARTIFACT_FILES)
        self.assertNotIn(".devflow/runs/", delivery.DELIVERY_ARTIFACT_FILES)


class DeliveryStateTest(unittest.TestCase):
    def test_render_and_load_round_trip(self):
        state = DeliveryState(
            commit="abc123",
            pushed=True,
            remote="origin",
            pr_url="https://github.com/x/y/pull/1",
            pr_title="feat: add delivery",
            worktree_removed=True,
            branch_deleted=True,
            returned_to_main=True,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "delivery.yaml"
            path.write_text(delivery.render_delivery_yaml(state), encoding="utf-8")
            self.assertEqual(delivery.load_delivery_state(path), state)

    def test_load_returns_defaults_when_absent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "missing.yaml"
            self.assertEqual(delivery.load_delivery_state(path), DeliveryState())

    def test_save_creates_delivery_yaml(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = delivery.save_delivery_state(root, DeliveryState(pr_url="https://x"))
            self.assertEqual(path, root / ".devflow" / "delivery.yaml")
            self.assertTrue(path.exists())
            self.assertEqual(delivery.load_delivery_state(path).pr_url, "https://x")


if __name__ == "__main__":
    unittest.main()
