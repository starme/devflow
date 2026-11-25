#!/usr/bin/env python3
"""Tests for the delivery orchestrator module (read-only probes + state)."""

from __future__ import annotations

import subprocess
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
    import devflow_guard_common

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


class EndpointHasChangesTest(unittest.TestCase):
    """Zero-diff activated endpoints must be detectable so delivery skips them."""

    def test_true_when_working_tree_dirty(self):
        # status non-empty, rev-list clean -> still has changes (uncommitted).
        with mock.patch.object(delivery, "_git", side_effect=["M a.py", "0"]):
            self.assertTrue(delivery.endpoint_has_changes(Path("/repo"), "abc123"))

    def test_true_when_commits_ahead_of_base(self):
        # status clean but rev-list > 0 -> committed, undelivered changes.
        with mock.patch.object(delivery, "_git", side_effect=["", "2"]):
            self.assertTrue(delivery.endpoint_has_changes(Path("/repo"), "abc123"))

    def test_false_when_clean_and_no_commits_ahead(self):
        with mock.patch.object(delivery, "_git", side_effect=["", "0"]):
            self.assertFalse(delivery.endpoint_has_changes(Path("/repo"), "abc123"))

    def test_fail_safe_true_when_git_unavailable(self):
        # Probes returning None (git missing / repo broken) must NOT silently
        # skip a real delivery: unknown state counts as "has changes".
        with mock.patch.object(delivery, "_git", return_value=None):
            self.assertTrue(delivery.endpoint_has_changes(Path("/repo"), "abc123"))

    def test_fail_safe_true_when_base_commit_invalid(self):
        # rev-list fails (bad base ref) while status is clean -> True.
        with mock.patch.object(delivery, "_git", side_effect=["", None]):
            self.assertTrue(delivery.endpoint_has_changes(Path("/repo"), "bad-ref"))

    def test_fail_safe_true_when_base_commit_empty(self):
        with mock.patch.object(delivery, "_git", side_effect=["", "0"]):
            self.assertTrue(delivery.endpoint_has_changes(Path("/repo"), ""))


class EndpointHasChangesRealGitTest(unittest.TestCase):
    """Real-git fixture: the probe must distinguish the delivery states."""

    def _repository(self, temp_dir: str) -> Path:
        root = Path(temp_dir) / "repo"
        root.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        (root / "README.md").write_text("initial\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
        subprocess.run(
            ["git", "-c", "user.name=DevFlow", "-c", "user.email=d@example.invalid",
             "commit", "-qm", "initial"],
            cwd=root, check=True,
        )
        return root

    def _base_commit(self, root: Path) -> str:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
        ).stdout.strip()

    def test_false_when_activated_but_zero_diff(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._repository(temp_dir)
            base = self._base_commit(root)
            subprocess.run(["git", "checkout", "-q", "-b", "feature/x"], cwd=root, check=True)
            self.assertFalse(delivery.endpoint_has_changes(root, base))

    def test_true_after_a_commit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._repository(temp_dir)
            base = self._base_commit(root)
            subprocess.run(["git", "checkout", "-q", "-b", "feature/x"], cwd=root, check=True)
            (root / "new.py").write_text("x = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "new.py"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=DevFlow", "-c", "user.email=d@example.invalid",
                 "commit", "-qm", "change"],
                cwd=root, check=True,
            )
            self.assertTrue(delivery.endpoint_has_changes(root, base))

    def test_true_with_uncommitted_edit_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._repository(temp_dir)
            base = self._base_commit(root)
            (root / "README.md").write_text("edited\n", encoding="utf-8")
            self.assertTrue(delivery.endpoint_has_changes(root, base))

    def test_false_with_untracked_residue_only(self):
        # ?? residue is not deliverable content (same rule as _ensure_clean):
        # an activated endpoint holding only untracked leftovers is zero-diff.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._repository(temp_dir)
            base = self._base_commit(root)
            subprocess.run(["git", "checkout", "-q", "-b", "feature/x"], cwd=root, check=True)
            (root / "leftover.log").write_text("residue\n", encoding="utf-8")
            self.assertFalse(delivery.endpoint_has_changes(root, base))

    def test_false_when_base_reachable_but_unrelated(self):
        # A base that exists but is not an ancestor of HEAD (e.g. after rebase
        # onto a divergent line): rev-list --count returns 0 with rc=0, so the
        # probe reads False — documented behavior, not the fail-safe path.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._repository(temp_dir)
            subprocess.run(["git", "checkout", "-q", "-b", "side"], cwd=root, check=True)
            (root / "side.py").write_text("s = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "side.py"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=DevFlow", "-c", "user.email=d@example.invalid",
                 "commit", "-qm", "side"],
                cwd=root, check=True,
            )
            unrelated = self._base_commit(root)
            subprocess.run(["git", "checkout", "-q", "main"], cwd=root, check=True)
            subprocess.run(["git", "checkout", "-q", "-b", "feature/x"], cwd=root, check=True)
            self.assertFalse(delivery.endpoint_has_changes(root, unrelated))


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

    def test_render_and_load_multi_repo_round_trip(self):
        state = DeliveryState(
            commit="be-commit",
            pushed=True,
            pr_url="https://github.com/x/be/pull/1",
            repos=(
                delivery.RepoDelivery(
                    "backend", "/abs/be", "be-commit", True, "https://github.com/x/be/pull/1"
                ),
                delivery.RepoDelivery("frontend", "/abs/fe", "fe-commit", False, None),
            ),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "delivery.yaml"
            path.write_text(delivery.render_delivery_yaml(state), encoding="utf-8")
            loaded = delivery.load_delivery_state(path)
            self.assertEqual(loaded.repos, state.repos)
            self.assertEqual(loaded.repos[0].pr_url, "https://github.com/x/be/pull/1")
            self.assertIsNone(loaded.repos[1].pr_url)

    def test_load_multi_repo_absent_repos_defaults_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "delivery.yaml"
            path.write_text(
                delivery.render_delivery_yaml(DeliveryState(commit="c")), encoding="utf-8"
            )
            self.assertEqual(delivery.load_delivery_state(path).repos, ())


if __name__ == "__main__":
    unittest.main()
