#!/usr/bin/env python3
"""Tests for formal task artifact publishing (core/orchestrator/artifact_publish.py).

These cover discovery (three precedence levels), whitelist enforcement, safe
sources (symlink / dir-symlink / path escape / sensitive files), semantic PRD
naming, per-task namespacing, idempotent publishing, conflict refusal, README
index, task.yaml dual-path reference updates, collect guard, and the CLI.

All fixtures are built under ``tempfile.TemporaryDirectory`` so tests never
touch a real repository or ``.devflow-worktrees/`` tree.
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

ORCHESTRATOR = Path(__file__).resolve().parents[1] / "orchestrator"
sys.path.insert(0, str(ORCHESTRATOR))

from task_state import TaskRecord, load_task, render_task_yaml  # noqa: E402
import artifact_publish as ap  # noqa: E402


def _meta(**overrides) -> dict:
    meta = {
        "task_id": "feature-add-report-abc123",
        "slug": "feature-add-report",
        "branch": "feature/feature-add-report-abc123",
        "base_ref": "main",
        "base_commit": "deadbeef" * 5,
        "kind": "feature",
    }
    meta.update(overrides)
    return meta


def _task_yaml(task_id: str, slug: str, kind: str = "feature") -> str:
    record = TaskRecord(
        task_id=task_id,
        slug=slug,
        kind=kind,
        description=slug.replace("-", " ").title(),
        base_ref="main",
        base_commit="deadbeef" * 5,
        branch=f"{kind}/{task_id}",
        worktree=f"/tmp/.devflow-worktrees/repo/{task_id}",
    )
    return render_task_yaml(record)


class _Fixture:
    """Build a minimal ``<project_root>/<repo_root>`` layout with task worktrees.

    The default models form B (project_root == repo_root.parent): ``<parent>``
    is the project root holding ``.devflow/``, and ``<parent>/repo`` is the git
    repo root.  ``form_a=True`` collapses the two so project_root == repo_root
    (the ordinary user-project layout).
    """

    def __init__(self, temp: str, form_a: bool = False):
        self.parent = Path(temp)
        self.repo = self.parent if form_a else self.parent / "repo"
        self.repo.mkdir(exist_ok=True)

    @property
    def project_root(self) -> Path:
        """Return the archive authority (the dir holding ``.devflow/``)."""
        return self.parent

    def archive_dir(self) -> Path:
        """Return the archive root ``project_root/.devflow/tasks``."""
        return self.project_root / ".devflow" / "tasks"

    def worktree_dir(self, task_id: str) -> Path:
        return self.repo.parent / ".devflow-worktrees" / self.repo.name / task_id

    def make_task(self, task_id: str, slug: str, kind: str = "feature") -> Path:
        wt = self.worktree_dir(task_id)
        devflow = wt / ".devflow"
        devflow.mkdir(parents=True, exist_ok=True)
        (devflow / "task.yaml").write_text(_task_yaml(task_id, slug, kind), encoding="utf-8")
        return wt

    def artifact(self, worktree: Path, name: str, content: str = "") -> Path:
        path = worktree / ".devflow" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path


class TargetNameTest(unittest.TestCase):
    def test_prd_renamed_to_semantic_slug(self):
        self.assertEqual(ap.target_name("prd.md", _meta(slug="weekly-report")),
                         "prd-weekly-report.md")

    def test_other_artifacts_keep_fixed_name(self):
        for name in ("architecture.md", "scope.yaml", "diagnosis.md",
                     "acceptance-report.md", "acceptance-scenarios.md",
                     "test-report.md", "task-report.md"):
            self.assertEqual(ap.target_name(name, _meta()), name)

    def test_test_reports_dir_entries_keep_fixed_name(self):
        # Directory entries are walked into relative paths, not renamed.
        self.assertEqual(ap.target_name("test_reports/report.json", _meta()),
                         "test_reports/report.json")


class ArchiveRootTest(unittest.TestCase):
    def test_resolve_archive_root_form_a(self):
        # project_root == repo_root (ordinary user project).
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "repo"
            self.assertEqual(
                ap.resolve_archive_root(project_root),
                project_root / ".devflow" / "tasks",
            )

    def test_resolve_archive_root_form_b(self):
        # project_root == repo_root.parent (plugin self-hosting).
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            self.assertEqual(
                ap.resolve_archive_root(project_root),
                project_root / ".devflow" / "tasks",
            )

    def test_worktree_root_is_form_independent(self):
        # _worktree_root keys off repo_root only, never project_root, so both
        # forms resolve the worktree to the identical location.
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            repo_root = parent / "repo"
            for _ in ("form-a", "form-b"):
                self.assertEqual(
                    ap._worktree_root(repo_root, "t-x"),
                    parent / ".devflow-worktrees" / repo_root.name / "t-x",
                )


class DiscoveryTest(unittest.TestCase):
    def test_discover_by_explicit_worktree(self):
        f = _Fixture(tempfile.mkdtemp())
        wt = f.make_task("t-1", "t-1")
        found = ap.discover_task(f.repo, worktree=str(wt))
        self.assertEqual(found, wt.resolve())

    def test_discover_by_task_id(self):
        f = _Fixture(tempfile.mkdtemp())
        wt = f.make_task("t-2", "t-2")
        found = ap.discover_task(f.repo, task_id="t-2")
        self.assertEqual(found, wt.resolve())

    def test_discover_all_tasks(self):
        f = _Fixture(tempfile.mkdtemp())
        f.make_task("t-3", "t-3")
        found = ap.discover_task(f.repo, all_tasks=True)
        self.assertEqual(found.name, "t-3")

    def test_missing_task_yaml_not_identified(self):
        # Directory name matches a task but has no task.yaml -> not recognized.
        f = _Fixture(tempfile.mkdtemp())
        candidate = f.worktree_dir("ghost")
        (candidate / ".devflow").mkdir(parents=True)
        # No task.yaml written.
        with self.assertRaises(ValueError):
            ap.discover_task(f.repo, task_id="ghost")

    def test_explicit_worktree_outside_tree_rejected(self):
        f = _Fixture(tempfile.mkdtemp())
        outside = f.parent / "elsewhere"
        outside.mkdir(parents=True)
        (outside / ".devflow").mkdir()
        (outside / ".devflow" / "task.yaml").write_text(
            _task_yaml("x", "x"), encoding="utf-8")
        with self.assertRaises(ValueError):
            ap.discover_task(f.repo, worktree=str(outside))

    def test_explicit_worktree_without_task_yaml_rejected(self):
        f = _Fixture(tempfile.mkdtemp())
        wt = f.worktree_dir("t-4")
        (wt / ".devflow").mkdir(parents=True)
        with self.assertRaises(ValueError):
            ap.discover_task(f.repo, worktree=str(wt))

    def test_no_selector_raises(self):
        f = _Fixture(tempfile.mkdtemp())
        with self.assertRaises(ValueError):
            ap.discover_task(f.repo)

    def test_read_task_meta(self):
        f = _Fixture(tempfile.mkdtemp())
        wt = f.make_task("t-5", "t-five", kind="bugfix")
        meta = ap.read_task_meta(wt)
        self.assertEqual(meta["task_id"], "t-5")
        self.assertEqual(meta["slug"], "t-five")
        self.assertEqual(meta["kind"], "bugfix")
        self.assertEqual(meta["base_ref"], "main")
        self.assertEqual(meta["base_commit"], "deadbeef" * 5)


class SafetyTest(unittest.TestCase):
    def test_symlink_refused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            real = root / "real.md"
            real.write_text("x", encoding="utf-8")
            link = root / "link.md"
            try:
                os.symlink(real, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlink not supported on this platform")
            self.assertFalse(ap.is_safe_source(link, root))

    def test_directory_symlink_refused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            real_dir = root / "real_dir"
            real_dir.mkdir()
            (real_dir / "f.md").write_text("x", encoding="utf-8")
            link_dir = root / "link_dir"
            try:
                os.symlink(real_dir, link_dir)
            except (OSError, NotImplementedError):
                self.skipTest("symlink not supported on this platform")
            self.assertFalse(ap.is_safe_source(link_dir, root))

    def test_path_escape_refused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "devflow"
            root.mkdir()
            outside = Path(temp_dir) / "outside.md"
            outside.write_text("x", encoding="utf-8")
            # A path that resolves outside root must be refused.
            self.assertFalse(ap.is_safe_source(outside, root))

    def test_sensitive_names_refused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in (".env", ".env.prod", "server.pem", "secrets.json",
                         "config.key", "id_rsa.key"):
                (root / name).write_text("secret", encoding="utf-8")
                self.assertFalse(ap.is_safe_source(root / name, root), name)

    def test_ordinary_artifact_allowed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            f = root / "prd.md"
            f.write_text("content", encoding="utf-8")
            self.assertTrue(ap.is_safe_source(f, root))


class WhitelistTest(unittest.TestCase):
    def test_only_publishable_artifacts_listed(self):
        f = _Fixture(tempfile.mkdtemp())
        wt = f.make_task("t-6", "t-6")
        # Publishable files.
        f.artifact(wt, "prd.md", "prd")
        f.artifact(wt, "architecture.md", "arch")
        f.artifact(wt, "scope.yaml", "scope")
        f.artifact(wt, "task-report.md", "impl report")
        # Non-publishable files (config / state / read-only refs).
        f.artifact(wt, "project.yaml", "proj")
        f.artifact(wt, "context.json", "ctx")
        f.artifact(wt, "manifest.yaml", "manifest")
        (wt / ".devflow" / "rules").mkdir(exist_ok=True)
        f.artifact(wt, "rules/redlines.yaml", "rl")

        rels = ap.iter_publishable_files(wt)
        self.assertEqual(rels, ["architecture.md", "prd.md", "scope.yaml",
                                "task-report.md"])

    def test_test_reports_dir_walked_recursively(self):
        f = _Fixture(tempfile.mkdtemp())
        wt = f.make_task("t-7", "t-7")
        (wt / ".devflow" / "test_reports").mkdir(parents=True)
        f.artifact(wt, "test_reports/a.json", "{}")
        f.artifact(wt, "test_reports/nested/b.txt", "b")

        rels = ap.iter_publishable_files(wt)
        self.assertEqual(rels, ["test_reports/a.json", "test_reports/nested/b.txt"])

    def test_sensitive_file_inside_test_reports_skipped(self):
        f = _Fixture(tempfile.mkdtemp())
        wt = f.make_task("t-8", "t-8")
        (wt / ".devflow" / "test_reports").mkdir(parents=True)
        f.artifact(wt, "test_reports/a.json", "{}")
        f.artifact(wt, "test_reports/.env", "secret")

        rels = ap.iter_publishable_files(wt)
        self.assertEqual(rels, ["test_reports/a.json"])


class ContentHashTest(unittest.TestCase):
    def test_directory_hash_order_independent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = (Path(temp_dir) / "tr").resolve()
            root.mkdir(parents=True)
            (root / "a.txt").write_text("a", encoding="utf-8")
            (root / "b.txt").write_text("b", encoding="utf-8")
            h1 = ap.content_hash(root, root.parent)

        with tempfile.TemporaryDirectory() as temp_dir:
            root2 = (Path(temp_dir) / "tr").resolve()
            root2.mkdir(parents=True)
            # Same contents, different creation order.
            (root2 / "b.txt").write_text("b", encoding="utf-8")
            (root2 / "a.txt").write_text("a", encoding="utf-8")
            h2 = ap.content_hash(root2, root2.parent)
        self.assertEqual(h1, h2)


class PlanPublishTest(unittest.TestCase):
    def test_create_skip_conflict_actions(self):
        f = _Fixture(tempfile.mkdtemp())
        wt = f.make_task("t-9", "t-nine")
        f.artifact(wt, "prd.md", "prd content")

        target = f.archive_dir() / "t-9"
        # First plan: create.
        actions, mapping = ap.plan_publish(wt, target)
        self.assertEqual(actions[0]["action"], ap.ACTION_CREATE)
        self.assertEqual(actions[0]["target"], "prd-t-nine.md")
        self.assertEqual(mapping["prd.md"], ".devflow/tasks/t-9/prd-t-nine.md")

        # Simulate an already-published identical target.
        target.mkdir(parents=True)
        (target / "prd-t-nine.md").write_text("prd content", encoding="utf-8")
        actions, _ = ap.plan_publish(wt, target)
        self.assertEqual(actions[0]["action"], ap.ACTION_SKIP)

        # Differing content -> conflict.
        (target / "prd-t-nine.md").write_text("different", encoding="utf-8")
        actions, _ = ap.plan_publish(wt, target)
        self.assertEqual(actions[0]["action"], ap.ACTION_CONFLICT)


class PublishTest(unittest.TestCase):
    def test_publish_prd_under_semantic_name_and_others_fixed(self):
        f = _Fixture(tempfile.mkdtemp())
        wt = f.make_task("t-10", "t-ten")
        f.artifact(wt, "prd.md", "prd body")
        f.artifact(wt, "architecture.md", "arch body")

        result = ap.publish(f.project_root, wt)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["conflicts"], [])
        target = f.archive_dir() / "t-10"
        self.assertTrue((target / "prd-t-ten.md").is_file())
        self.assertTrue((target / "architecture.md").is_file())
        self.assertFalse((target / "prd.md").exists())
        self.assertEqual((target / "prd-t-ten.md").read_text(encoding="utf-8"),
                         "prd body")

    def test_publish_is_idempotent(self):
        f = _Fixture(tempfile.mkdtemp())
        wt = f.make_task("t-11", "t-11")
        f.artifact(wt, "prd.md", "same prd")

        first = ap.publish(f.project_root, wt)
        self.assertEqual(len(first["published"]), 1)
        second = ap.publish(f.project_root, wt)
        self.assertEqual(len(second["skipped"]), 1)
        self.assertEqual(len(second["published"]), 0)
        # No duplicate file.
        target = f.archive_dir() / "t-11"
        prds = [p for p in target.iterdir() if p.name.startswith("prd-")]
        self.assertEqual(len(prds), 1)

    def test_content_conflict_refuses_overwrite(self):
        f = _Fixture(tempfile.mkdtemp())
        wt = f.make_task("t-12", "t-12")
        f.artifact(wt, "prd.md", "new content")

        target = f.archive_dir() / "t-12"
        target.mkdir(parents=True)
        (target / "prd-t-12.md").write_text("old content", encoding="utf-8")

        result = ap.publish(f.project_root, wt)
        self.assertTrue(result["conflicts"])
        # Target not overwritten, source intact.
        self.assertEqual((target / "prd-t-12.md").read_text(encoding="utf-8"),
                         "old content")
        self.assertEqual(
            (wt / ".devflow" / "prd.md").read_text(encoding="utf-8"),
            "new content")

    def test_two_tasks_same_prd_name_do_not_overwrite(self):
        f = _Fixture(tempfile.mkdtemp())
        wt1 = f.make_task("task-one", "task-one")
        wt2 = f.make_task("task-two", "task-two")
        f.artifact(wt1, "prd.md", "prd for one")
        f.artifact(wt2, "prd.md", "prd for two")

        ap.publish(f.project_root, wt1)
        ap.publish(f.project_root, wt2)

        one = f.archive_dir() / "task-one" / "prd-task-one.md"
        two = f.archive_dir() / "task-two" / "prd-task-two.md"
        self.assertEqual(one.read_text(encoding="utf-8"), "prd for one")
        self.assertEqual(two.read_text(encoding="utf-8"), "prd for two")


class ReadmeIndexTest(unittest.TestCase):
    def test_readme_contains_metadata_and_semantic_prd(self):
        f = _Fixture(tempfile.mkdtemp())
        wt = f.make_task("t-13", "t-thirteen")
        f.artifact(wt, "prd.md", "prd")
        f.artifact(wt, "architecture.md", "arch")

        ap.publish(f.project_root, wt)
        readme = (f.archive_dir() / "t-13" / "README.md").read_text(
            encoding="utf-8")
        self.assertIn('task_id: "t-13"', readme)
        self.assertIn('slug: "t-thirteen"', readme)
        self.assertIn('base_commit: "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"', readme)
        self.assertIn('kind: "feature"', readme)
        self.assertIn('prd: "prd-t-thirteen.md"', readme)
        self.assertIn('architecture: "architecture.md"', readme)
        # No absolute worktree path leaks into the index.
        self.assertNotIn("/.devflow-worktrees/", readme)

    def test_acceptance_report_and_scenarios_get_distinct_keys(self):
        # Regression: both files used to map to one ``acceptance_report`` key,
        # emitting duplicate YAML keys that silently dropped the report ref.
        f = _Fixture(tempfile.mkdtemp())
        wt = f.make_task("t-18", "t-eighteen")
        f.artifact(wt, "acceptance-report.md", "report")
        f.artifact(wt, "acceptance-scenarios.md", "scenarios")

        ap.publish(f.project_root, wt)
        readme = (f.archive_dir() / "t-18" / "README.md").read_text(
            encoding="utf-8")
        self.assertIn('acceptance_report: "acceptance-report.md"', readme)
        self.assertIn('acceptance_scenarios: "acceptance-scenarios.md"', readme)

        content = (wt / ".devflow" / "task.yaml").read_text(encoding="utf-8")
        self.assertIn('published: ".devflow/tasks/t-18/acceptance-report.md"', content)
        self.assertIn('published: ".devflow/tasks/t-18/acceptance-scenarios.md"', content)


class TaskYamlRefUpdateTest(unittest.TestCase):
    def test_update_writes_dual_path_refs(self):
        f = _Fixture(tempfile.mkdtemp())
        wt = f.make_task("t-14", "t-fourteen")
        f.artifact(wt, "prd.md", "prd")
        f.artifact(wt, "architecture.md", "arch")
        f.artifact(wt, "scope.yaml", "scope")

        actions, mapping = ap.plan_publish(wt, f.archive_dir() / "t-14")
        ap.update_task_artifact_refs(wt, "t-14", "t-fourteen", mapping)

        content = (wt / ".devflow" / "task.yaml").read_text(encoding="utf-8")
        self.assertIn('worktree: ".devflow/prd.md"', content)
        self.assertIn('published: ".devflow/tasks/t-14/prd-t-fourteen.md"', content)
        self.assertIn('worktree: ".devflow/architecture.md"', content)

        # task.yaml still parseable (id/slug intact).
        record = load_task(wt / ".devflow" / "task.yaml")
        self.assertEqual(record.task_id, "t-14")

    def test_update_preserves_delivery_field_and_does_not_touch_root(self):
        f = _Fixture(tempfile.mkdtemp())
        wt = f.make_task("t-15", "t-fifteen")
        f.artifact(wt, "prd.md", "prd")

        actions, mapping = ap.plan_publish(wt, f.archive_dir() / "t-15")
        ap.update_task_artifact_refs(wt, "t-15", "t-fifteen", mapping)

        content = (wt / ".devflow" / "task.yaml").read_text(encoding="utf-8")
        # delivery is a legacy scalar, preserved.
        self.assertIn('delivery: ".devflow/delivery.yaml"', content)
        # Root .devflow/task.yaml must never be created.
        self.assertFalse((f.repo / ".devflow" / "task.yaml").exists())


class CollectGuardTest(unittest.TestCase):
    def test_collect_skips_formal_task_worktree(self):
        import worktree_sync  # noqa: E402  (imported lazily; same sys.path)
        f = _Fixture(tempfile.mkdtemp())
        wt = f.make_task("t-16", "t-sixteen")
        f.artifact(wt, "prd.md", "prd")

        result = worktree_sync.collect_artifacts(f.repo, worktree=str(wt))
        self.assertEqual(result["synced"], [])
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("formal task worktree", result["errors"][0])


class CliTest(unittest.TestCase):
    def test_cli_dry_run_outputs_plan_json(self):
        f = _Fixture(tempfile.mkdtemp())
        wt = f.make_task("t-17", "t-seventeen")
        f.artifact(wt, "prd.md", "prd")

        with contextlib.redirect_stdout(io.StringIO()):
            out = ap.main(["publish", "--root", str(f.project_root),
                           "--repo-root", str(f.repo), "--task", "t-17",
                           "--dry-run"])
        # dry-run returns 0 when no errors/conflicts.
        self.assertEqual(out, 0)

    def test_cli_conflict_exits_nonzero(self):
        f = _Fixture(tempfile.mkdtemp())
        wt = f.make_task("t-18", "t-eighteen")
        f.artifact(wt, "prd.md", "new")

        target = f.archive_dir() / "t-18"
        target.mkdir(parents=True)
        (target / "prd-t-eighteen.md").write_text("old", encoding="utf-8")

        with contextlib.redirect_stdout(io.StringIO()):
            out = ap.main(["publish", "--root", str(f.project_root),
                           "--repo-root", str(f.repo), "--task", "t-18"])
        self.assertEqual(out, 1)

    def test_cli_missing_root_exits_nonzero(self):
        f = _Fixture(tempfile.mkdtemp())
        with contextlib.redirect_stdout(io.StringIO()):
            out = ap.main(["publish", "--root", str(f.parent / "nope"),
                           "--repo-root", str(f.repo), "--all-tasks"])
        self.assertEqual(out, 1)

    def test_cli_missing_discovery_exits_nonzero(self):
        f = _Fixture(tempfile.mkdtemp())
        with contextlib.redirect_stdout(io.StringIO()):
            out = ap.main(["publish", "--root", str(f.project_root),
                           "--repo-root", str(f.repo), "--task", "missing"])
        self.assertEqual(out, 1)

    def test_cli_archives_to_devflow_tasks_not_docs(self):
        # AC-12: archive lands in .devflow/tasks/, docs/tasks/ is never created.
        f = _Fixture(tempfile.mkdtemp())
        wt = f.make_task("t-ac12", "t-ac12")
        f.artifact(wt, "prd.md", "prd")

        with contextlib.redirect_stdout(io.StringIO()):
            out = ap.main(["publish", "--root", str(f.project_root),
                           "--repo-root", str(f.repo), "--task", "t-ac12"])
        self.assertEqual(out, 0)
        self.assertTrue((f.archive_dir() / "t-ac12" / "prd-t-ac12.md").is_file())
        self.assertFalse((f.repo / "docs" / "tasks").exists())

    def test_cli_form_a_archives_inside_repo(self):
        # Form A: project_root == repo_root; the archive lives under the repo's
        # own .devflow/tasks/ and the worktree still lives under repo.parent.
        f = _Fixture(tempfile.mkdtemp(), form_a=True)
        wt = f.make_task("t-forma", "t-form-a")
        f.artifact(wt, "prd.md", "prd")

        with contextlib.redirect_stdout(io.StringIO()):
            out = ap.main(["publish", "--root", str(f.project_root),
                           "--repo-root", str(f.repo), "--task", "t-forma"])
        self.assertEqual(out, 0)
        # project_root == repo_root, so archive is under the repo itself.
        self.assertTrue((f.repo / ".devflow" / "tasks" / "t-forma" / "prd-t-form-a.md").is_file())
        self.assertFalse((f.repo / "docs" / "tasks").exists())


if __name__ == "__main__":
    unittest.main()