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
from pathlib import Path

import pytest

ORCHESTRATOR = Path(__file__).resolve().parents[1] / "orchestrator"
sys.path.insert(0, str(ORCHESTRATOR))

import artifact_publish as ap
from task_state import TaskRecord, load_task, render_task_yaml


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


def _task_yaml(
    task_id: str,
    slug: str,
    kind: str = "feature",
    phase: str = "qa",
    worktree: str = "",
) -> str:
    # In-place is the only layout new tasks use, so the recorded path defaults
    # to an empty marker rather than a worktree path tests no longer create.
    record = TaskRecord(
        task_id=task_id,
        slug=slug,
        kind=kind,
        description=slug.replace("-", " ").title(),
        base_ref="main",
        base_commit="deadbeef" * 5,
        branch=f"{kind}/{task_id}",
        working_dir=worktree or f"/tmp/in-place/{task_id}",
    )
    return render_task_yaml(record, current_phase=phase)


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
        """Create an in-place task rooted at the repo (the default layout).

        New tasks are always in-place, so this is what every publishing test
        exercises. Use ``make_legacy_worktree`` when testing the read-only
        compatibility path for older isolated tasks.
        """
        devflow = self.repo / ".devflow"
        devflow.mkdir(parents=True, exist_ok=True)
        (devflow / "task.yaml").write_text(_task_yaml(task_id, slug, kind), encoding="utf-8")
        return self.repo

    def make_legacy_worktree(self, task_id: str, slug: str, kind: str = "feature") -> Path:
        """Create a task under ``.devflow-worktrees/``, the retired layout."""
        wt = self.worktree_dir(task_id)
        devflow = wt / ".devflow"
        devflow.mkdir(parents=True, exist_ok=True)
        (devflow / "task.yaml").write_text(
            _task_yaml(task_id, slug, kind, worktree=str(wt)), encoding="utf-8"
        )
        return wt

    def artifact(self, worktree: Path, name: str, content: str = "") -> Path:
        path = worktree / ".devflow" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path


def test_prd_renamed_to_semantic_slug():
    assert ap.target_name("prd.md", _meta(slug="weekly-report")) == "prd-weekly-report.md"


def test_other_artifacts_keep_fixed_name():
    for name in (
        "architecture.md",
        "scope.yaml",
        "diagnosis.md",
        "acceptance-report.md",
        "acceptance-scenarios.md",
        "test-report.md",
        "task-report.md",
    ):
        assert ap.target_name(name, _meta()) == name


def test_test_reports_dir_entries_keep_fixed_name():
    # Directory entries are walked into relative paths, not renamed.
    assert ap.target_name("test_reports/report.json", _meta()) == "test_reports/report.json"


def test_resolve_archive_root_form_a():
    # project_root == repo_root (ordinary user project).
    with tempfile.TemporaryDirectory() as temp_dir:
        project_root = Path(temp_dir) / "repo"
        assert ap.resolve_archive_root(project_root) == project_root / ".devflow" / "tasks"


def test_resolve_archive_root_form_b():
    # project_root == repo_root.parent (plugin self-hosting).
    with tempfile.TemporaryDirectory() as temp_dir:
        project_root = Path(temp_dir)
        assert ap.resolve_archive_root(project_root) == project_root / ".devflow" / "tasks"


def test_worktree_root_is_form_independent():
    # _worktree_root keys off repo_root only, never project_root, so both
    # forms resolve the worktree to the identical location.
    with tempfile.TemporaryDirectory() as temp_dir:
        parent = Path(temp_dir)
        repo_root = parent / "repo"
        for _ in ("form-a", "form-b"):
            assert ap._worktree_root(repo_root, "t-x") == parent / ".devflow-worktrees" / repo_root.name / "t-x"


def test_discover_legacy_worktree_by_task_id():
    # A task isolated by an older DevFlow is still locatable so its
    # unpublished artifacts can be archived.
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_legacy_worktree("t-1", "t-1")
    found = ap.discover_task(f.repo, task_id="t-1")
    assert found == wt.resolve()


def test_discover_by_task_id():
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_task("t-2", "t-2")
    found = ap.discover_task(f.repo, task_id="t-2")
    assert found == wt.resolve()


def test_discover_by_task_id_in_place():
    # In-place form: task.yaml lives directly under repo_root/.devflow/ with
    # no .devflow-worktrees/ tree.  --task must fall back to repo_root.
    f = _Fixture(tempfile.mkdtemp(), form_a=True)
    devflow = f.repo / ".devflow"
    devflow.mkdir(parents=True)
    (devflow / "task.yaml").write_text(_task_yaml("t-inplace", "t-inplace"), encoding="utf-8")
    found = ap.discover_task(f.repo, task_id="t-inplace")
    assert found == f.repo.resolve()


def test_discover_by_task_id_in_place_id_mismatch():
    # A stale in-place task.yaml naming a different task must not match.
    f = _Fixture(tempfile.mkdtemp(), form_a=True)
    devflow = f.repo / ".devflow"
    devflow.mkdir(parents=True)
    (devflow / "task.yaml").write_text(_task_yaml("t-actual", "t-actual"), encoding="utf-8")
    with pytest.raises(ValueError):
        ap.discover_task(f.repo, task_id="t-other")


def test_discover_by_task_id_self_hosted():
    # Self-hosted shape: .devflow/ lives at the project (archive) root while
    # the git repo is a nested subdirectory (project_root != repo_root).
    # Without the archive-root hint discovery fails; with it, the in-place
    # task at the archive root is found.
    f = _Fixture(tempfile.mkdtemp())
    devflow = f.project_root / ".devflow"
    devflow.mkdir(parents=True)
    (devflow / "task.yaml").write_text(_task_yaml("t-selfhost", "t-selfhost"), encoding="utf-8")
    with pytest.raises(ValueError):
        ap.discover_task(f.repo, task_id="t-selfhost")
    found = ap.discover_task(f.repo, task_id="t-selfhost", archive_root=f.project_root)
    assert found == f.project_root.resolve()


def test_discover_self_hosted_id_mismatch_rejected():
    # The archive-root fallback is id-guarded like the repo-root one.
    f = _Fixture(tempfile.mkdtemp())
    devflow = f.project_root / ".devflow"
    devflow.mkdir(parents=True)
    (devflow / "task.yaml").write_text(_task_yaml("t-actual", "t-actual"), encoding="utf-8")
    with pytest.raises(ValueError):
        ap.discover_task(f.repo, task_id="t-other", archive_root=f.project_root)


def test_discover_all_tasks():
    f = _Fixture(tempfile.mkdtemp())
    f.make_task("t-3", "t-3")
    found = ap.discover_task(f.repo, all_tasks=True)
    assert found == f.repo.resolve()


def test_missing_task_yaml_not_identified():
    # Directory name matches a task but has no task.yaml -> not recognized.
    f = _Fixture(tempfile.mkdtemp())
    candidate = f.worktree_dir("ghost")
    (candidate / ".devflow").mkdir(parents=True)
    # No task.yaml written.
    with pytest.raises(ValueError):
        ap.discover_task(f.repo, task_id="ghost")


def test_in_place_wins_over_legacy_worktree():
    # In-place is the live layout, so it must be located first even when a
    # stale .devflow-worktrees/ entry carries the same id.
    f = _Fixture(tempfile.mkdtemp())
    f.make_legacy_worktree("t-dup", "t-dup")
    live = f.make_task("t-dup", "t-dup")
    assert ap.discover_task(f.repo, task_id="t-dup") == live.resolve()


def test_no_selector_raises():
    f = _Fixture(tempfile.mkdtemp())
    with pytest.raises(ValueError) as ctx:
        ap.discover_task(f.repo)
    assert "one of --task or --all-tasks" in str(ctx.value)


def test_read_task_meta():
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_task("t-5", "t-five", kind="bugfix")
    meta = ap.read_task_meta(wt)
    assert meta["task_id"] == "t-5"
    assert meta["slug"] == "t-five"
    assert meta["kind"] == "bugfix"
    assert meta["base_ref"] == "main"
    assert meta["base_commit"] == "deadbeef" * 5


def _archive(root: Path, task_id: str, phase: str = "done") -> Path:
    directory = root / task_id
    directory.mkdir(parents=True, exist_ok=True)
    state = _task_yaml(task_id, task_id, phase=phase)
    (directory / "task.yaml").write_text(state, encoding="utf-8")
    return directory


def _in_place(root: Path, task_id: str, phase: str = "working") -> Path:
    directory = root / ".devflow"
    directory.mkdir(parents=True, exist_ok=True)
    state = directory / "task.yaml"
    state.write_text(_task_yaml(task_id, task_id, phase=phase), encoding="utf-8")
    return state


def test_locates_legacy_worktree():
    # Read-only compatibility: a task isolated by an older DevFlow is still
    # located and publishable so its artifacts can be archived.
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_legacy_worktree("t-wt", "t-wt")
    location = ap.locate_task(f.repo, f.project_root, "t-wt")
    assert location.kind == "worktree"
    assert location.root == wt.resolve()
    assert ap.is_publishable(location)


def test_locates_in_place_at_repo_root():
    f = _Fixture(tempfile.mkdtemp())
    _in_place(f.repo, "t-repo")
    location = ap.locate_task(f.repo, f.project_root, "t-repo")
    assert location.kind == "in-place"
    assert location.root == f.repo.resolve()
    assert ap.is_publishable(location)


def test_locates_in_place_at_project_root():
    # Self-hosted shape: the state sits with the archive, not the git repo.
    f = _Fixture(tempfile.mkdtemp())
    _in_place(f.project_root, "t-proj")
    location = ap.locate_task(f.repo, f.project_root, "t-proj")
    assert location.kind == "in-place"
    assert location.root == f.project_root.resolve()
    assert ap.is_publishable(location)


def test_locates_archive_under_repo_root():
    f = _Fixture(tempfile.mkdtemp())
    archived = _archive(f.archive_dir(), "t-done")
    location = ap.locate_task(f.repo, f.project_root, "t-done")
    assert location.kind == "archived"
    assert location.root == archived.resolve()
    assert location.phase == "done"
    assert not (ap.is_publishable(location))


def test_locates_archive_under_project_root():
    f = _Fixture(tempfile.mkdtemp())
    project_archive = f.project_root / ".devflow" / "tasks"
    archived = _archive(project_archive, "t-proj-done")
    location = ap.locate_task(f.repo, f.project_root, "t-proj-done")
    assert location.kind == "archived"
    assert location.root == archived.resolve()


def test_repo_archive_wins_over_project_archive():
    f = _Fixture(tempfile.mkdtemp())
    _archive(f.archive_dir(), "t-both")
    project_archive = f.project_root / ".devflow" / "tasks"
    _archive(project_archive, "t-both")
    location = ap.locate_task(f.repo, f.project_root, "t-both")
    assert location.root == (f.archive_dir() / "t-both").resolve()


def test_archive_without_task_yaml_is_still_archived():
    # Older archives kept only their artifacts; they must not look missing.
    f = _Fixture(tempfile.mkdtemp())
    directory = f.archive_dir() / "t-legacy"
    directory.mkdir(parents=True)
    (directory / "card.md").write_text("card\n", encoding="utf-8")
    location = ap.locate_task(f.repo, f.project_root, "t-legacy")
    assert location.kind == "archived"
    assert not (location.has_state)
    assert location.phase is None
    assert not (ap.is_publishable(location))


def test_missing_task():
    f = _Fixture(tempfile.mkdtemp())
    location = ap.locate_task(f.repo, f.project_root, "t-ghost")
    assert location.kind == "missing"
    assert location.root is None
    assert not (ap.is_publishable(location))


@pytest.mark.parametrize("unsafe", ("../escape", "..", "a/b"))
def test_rejects_ids_that_escape_the_archive_roots(unsafe):
    f = _Fixture(tempfile.mkdtemp())
    assert ap.locate_task(f.repo, f.project_root, unsafe).kind == "missing"


def test_finished_in_place_task_is_not_publishable():
    # The live task.yaml still carries the id right after completion, so an
    # id-only check would wrongly advertise it as publishable.
    f = _Fixture(tempfile.mkdtemp())
    _in_place(f.repo, "t-finished", phase="done")
    location = ap.locate_task(f.repo, f.project_root, "t-finished")
    assert location.kind == "in-place"
    assert location.phase == "done"
    assert not (ap.is_publishable(location))


# The rule in one place: live kind + state + not finished.
PUBLISHABLE_CASES = [
    ("worktree", True, "working", True),
    ("worktree", True, "done", False),
    ("worktree", True, None, True),
    ("in-place", True, "qa", True),
    ("in-place", True, "done", False),
    ("in-place", False, None, False),
    ("archived", True, "done", False),
    ("archived", False, None, False),
    ("missing", False, None, False),
]


@pytest.mark.parametrize("kind,has_state,phase,expected", PUBLISHABLE_CASES)
def test_publishable_table(kind, has_state, phase, expected):
    location = ap.TaskLocation(
        task_id="t",
        kind=kind,
        root=Path("/tmp/t"),
        state_file=Path("/tmp/t/task.yaml") if has_state else None,
        phase=phase,
        has_state=has_state,
    )
    assert ap.is_publishable(location) is expected


def test_discover_refuses_archived_task():
    f = _Fixture(tempfile.mkdtemp())
    directory = f.archive_dir() / "t-done"
    directory.mkdir(parents=True)
    (directory / "task.yaml").write_text(_task_yaml("t-done", "t-done"), encoding="utf-8")
    with pytest.raises(ValueError) as ctx:
        ap.discover_task(f.repo, task_id="t-done", archive_root=f.project_root)
    assert "archived" in str(ctx.value)


def test_discover_refuses_finished_in_place_task():
    f = _Fixture(tempfile.mkdtemp(), form_a=True)
    devflow = f.repo / ".devflow"
    devflow.mkdir(parents=True)
    state = _task_yaml("t-done", "t-done", phase="done")
    (devflow / "task.yaml").write_text(state, encoding="utf-8")
    with pytest.raises(ValueError) as ctx:
        ap.discover_task(f.repo, task_id="t-done")
    assert "done" in str(ctx.value)


def test_all_tasks_skips_archives():
    f = _Fixture(tempfile.mkdtemp())
    directory = f.archive_dir() / "t-done"
    directory.mkdir(parents=True)
    (directory / "task.yaml").write_text(_task_yaml("t-done", "t-done"), encoding="utf-8")
    live = f.make_task("t-live", "t-live")

    found = ap.discover_task(f.repo, all_tasks=True, archive_root=f.project_root)

    assert found == live.resolve()


def test_describe_task_matches_locate():
    f = _Fixture(tempfile.mkdtemp())
    directory = f.archive_dir() / "t-done"
    directory.mkdir(parents=True)
    (directory / "task.yaml").write_text(
        _task_yaml("t-done", "t-done", phase="done"), encoding="utf-8"
    )
    info = ap.describe_task(f.repo, f.project_root, "t-done")
    assert info["location"] == "archived"
    assert Path(info["path"]) == directory.resolve()
    assert info["phase"] == "done"
    assert not (info["publishable"])


def test_symlink_refused():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        real = root / "real.md"
        real.write_text("x", encoding="utf-8")
        link = root / "link.md"
        try:
            os.symlink(real, link)
        except (OSError, NotImplementedError):
            pytest.skip("symlink not supported on this platform")
        assert not (ap.is_safe_source(link, root))


def test_directory_symlink_refused():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        real_dir = root / "real_dir"
        real_dir.mkdir()
        (real_dir / "f.md").write_text("x", encoding="utf-8")
        link_dir = root / "link_dir"
        try:
            os.symlink(real_dir, link_dir)
        except (OSError, NotImplementedError):
            pytest.skip("symlink not supported on this platform")
        assert not (ap.is_safe_source(link_dir, root))


def test_path_escape_refused():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "devflow"
        root.mkdir()
        outside = Path(temp_dir) / "outside.md"
        outside.write_text("x", encoding="utf-8")
        # A path that resolves outside root must be refused.
        assert not (ap.is_safe_source(outside, root))


def test_sensitive_names_refused():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        for name in (
            ".env",
            ".env.prod",
            "server.pem",
            "secrets.json",
            "config.key",
            "id_rsa.key",
        ):
            (root / name).write_text("secret", encoding="utf-8")
            assert not (ap.is_safe_source(root / name, root))


def test_ordinary_artifact_allowed():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        f = root / "prd.md"
        f.write_text("content", encoding="utf-8")
        assert ap.is_safe_source(f, root)


def test_only_publishable_artifacts_listed():
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
    assert rels == ["architecture.md", "prd.md", "scope.yaml", "task-report.md"]


def test_test_reports_dir_walked_recursively():
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_task("t-7", "t-7")
    (wt / ".devflow" / "test_reports").mkdir(parents=True)
    f.artifact(wt, "test_reports/a.json", "{}")
    f.artifact(wt, "test_reports/nested/b.txt", "b")

    rels = ap.iter_publishable_files(wt)
    assert rels == ["test_reports/a.json", "test_reports/nested/b.txt"]


def test_sensitive_file_inside_test_reports_skipped():
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_task("t-8", "t-8")
    (wt / ".devflow" / "test_reports").mkdir(parents=True)
    f.artifact(wt, "test_reports/a.json", "{}")
    f.artifact(wt, "test_reports/.env", "secret")

    rels = ap.iter_publishable_files(wt)
    assert rels == ["test_reports/a.json"]


def test_frontend_components_and_impact_analysis_publishable():
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_task("t-20", "t-20")
    f.artifact(wt, "frontend-components.md", "components")
    f.artifact(wt, "impact-analysis.md", "impact")
    f.artifact(wt, "architecture.md", "arch")

    rels = ap.iter_publishable_files(wt)
    assert "frontend-components.md" in rels
    assert "impact-analysis.md" in rels


def test_contracts_dir_walked_recursively():
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_task("t-21", "t-21")
    f.artifact(wt, "contracts/actions.md", "# actions")
    f.artifact(wt, "architecture.md", "arch")

    rels = ap.iter_publishable_files(wt)
    assert "contracts/actions.md" in rels


def test_missing_archived_artifacts_returns_unpublished():
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_task("t-22", "t-22")
    f.artifact(wt, "architecture.md", "arch")
    f.artifact(wt, "scope.yaml", "scope")

    missing = ap.missing_archived_artifacts(wt, f.project_root)
    assert missing == ["architecture.md", "scope.yaml"]


def test_missing_archived_artifacts_empty_after_publish():
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_task("t-23", "t-23")
    f.artifact(wt, "architecture.md", "arch")
    result = ap.publish(f.project_root, wt)
    assert result["errors"] == []

    missing = ap.missing_archived_artifacts(wt, f.project_root)
    assert missing == []


def test_missing_archived_artifacts_no_artifacts_is_empty():
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_task("t-24", "t-24")

    missing = ap.missing_archived_artifacts(wt, f.project_root)
    assert missing == []


def test_directory_hash_order_independent():
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
    assert h1 == h2


def test_create_skip_conflict_actions():
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_task("t-9", "t-nine")
    f.artifact(wt, "prd.md", "prd content")

    target = f.archive_dir() / "t-9"
    # First plan: create.
    actions, mapping = ap.plan_publish(wt, target)
    assert actions[0]["action"] == ap.ACTION_CREATE
    assert actions[0]["target"] == "prd-t-nine.md"
    assert mapping["prd.md"] == ".devflow/tasks/t-9/prd-t-nine.md"

    # Simulate an already-published identical target.
    target.mkdir(parents=True)
    (target / "prd-t-nine.md").write_text("prd content", encoding="utf-8")
    actions, _ = ap.plan_publish(wt, target)
    assert actions[0]["action"] == ap.ACTION_SKIP

    # Differing content -> conflict.
    (target / "prd-t-nine.md").write_text("different", encoding="utf-8")
    actions, _ = ap.plan_publish(wt, target)
    assert actions[0]["action"] == ap.ACTION_CONFLICT


def test_publish_prd_under_semantic_name_and_others_fixed():
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_task("t-10", "t-ten")
    f.artifact(wt, "prd.md", "prd body")
    f.artifact(wt, "architecture.md", "arch body")

    result = ap.publish(f.project_root, wt)
    assert result["errors"] == []
    assert result["conflicts"] == []
    target = f.archive_dir() / "t-10"
    assert (target / "prd-t-ten.md").is_file()
    assert (target / "architecture.md").is_file()
    assert not ((target / "prd.md").exists())
    assert (target / "prd-t-ten.md").read_text(encoding="utf-8") == "prd body"


def test_publish_self_hosted_in_place():
    # End-to-end publish for the self-hosted shape: the in-place task's
    # artifacts sit at project_root/.devflow/, the git repo is nested
    # inside the project (project_root != repo_root).
    f = _Fixture(tempfile.mkdtemp())
    devflow = f.project_root / ".devflow"
    devflow.mkdir(parents=True)
    (devflow / "task.yaml").write_text(_task_yaml("t-selfpub", "t-selfpub"), encoding="utf-8")
    (devflow / "prd.md").write_text("selfhost prd", encoding="utf-8")
    (devflow / "card.md").write_text("card body", encoding="utf-8")

    found = ap.discover_task(f.repo, task_id="t-selfpub", archive_root=f.project_root)
    result = ap.publish(f.project_root, found)

    assert result["errors"] == []
    assert result["conflicts"] == []
    target = f.archive_dir() / "t-selfpub"
    assert (target / "prd-t-selfpub.md").is_file()
    assert (target / "card.md").is_file()
    # The archive tree itself must not be re-published into the task dir.
    assert not ((target / "tasks").exists())


def test_publish_is_idempotent():
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_task("t-11", "t-11")
    f.artifact(wt, "prd.md", "same prd")

    first = ap.publish(f.project_root, wt)
    assert len(first["published"]) == 1
    second = ap.publish(f.project_root, wt)
    assert len(second["skipped"]) == 1
    assert len(second["published"]) == 0
    # No duplicate file.
    target = f.archive_dir() / "t-11"
    prds = [p for p in target.iterdir() if p.name.startswith("prd-")]
    assert len(prds) == 1


def test_content_conflict_refuses_overwrite():
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_task("t-12", "t-12")
    f.artifact(wt, "prd.md", "new content")

    target = f.archive_dir() / "t-12"
    target.mkdir(parents=True)
    (target / "prd-t-12.md").write_text("old content", encoding="utf-8")

    result = ap.publish(f.project_root, wt)
    assert result["conflicts"]
    # Target not overwritten, source intact.
    assert (target / "prd-t-12.md").read_text(encoding="utf-8") == "old content"
    assert (wt / ".devflow" / "prd.md").read_text(encoding="utf-8") == "new content"


def test_two_tasks_same_prd_name_do_not_overwrite():
    # Tasks run serially in one checkout, so the second task's plan replaces
    # the first's at the same path; each must still land in its own archive
    # namespace instead of overwriting the other.
    f = _Fixture(tempfile.mkdtemp())
    wt1 = f.make_task("task-one", "task-one")
    f.artifact(wt1, "prd.md", "prd for one")
    ap.publish(f.project_root, wt1)

    wt2 = f.make_task("task-two", "task-two")
    f.artifact(wt2, "prd.md", "prd for two")
    ap.publish(f.project_root, wt2)

    one = f.archive_dir() / "task-one" / "prd-task-one.md"
    two = f.archive_dir() / "task-two" / "prd-task-two.md"
    assert one.read_text(encoding="utf-8") == "prd for one"
    assert two.read_text(encoding="utf-8") == "prd for two"


def test_readme_contains_metadata_and_semantic_prd():
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_task("t-13", "t-thirteen")
    f.artifact(wt, "prd.md", "prd")
    f.artifact(wt, "architecture.md", "arch")

    ap.publish(f.project_root, wt)
    readme = (f.archive_dir() / "t-13" / "README.md").read_text(encoding="utf-8")
    assert 'task_id: "t-13"' in readme
    assert 'slug: "t-thirteen"' in readme
    assert 'base_commit: "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"' in readme
    assert 'kind: "feature"' in readme
    assert 'prd: "prd-t-thirteen.md"' in readme
    assert 'architecture: "architecture.md"' in readme
    # No absolute worktree path leaks into the index.
    assert "/.devflow-worktrees/" not in readme


def test_task_report_gets_own_key():
    # task-report.md is a publishable artifact (PUBLISHABLE_ARTIFACTS); the
    # README index must record it under a task_report key once published.
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_task("t-taskrep", "t-taskrep")
    f.artifact(wt, "task-report.md", "impl report")

    ap.publish(f.project_root, wt)
    readme = (f.archive_dir() / "t-taskrep" / "README.md").read_text(encoding="utf-8")
    assert 'task_report: "task-report.md"' in readme


def test_acceptance_report_and_scenarios_get_distinct_keys():
    # Regression: both files used to map to one ``acceptance_report`` key,
    # emitting duplicate YAML keys that silently dropped the report ref.
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_task("t-18", "t-eighteen")
    f.artifact(wt, "acceptance-report.md", "report")
    f.artifact(wt, "acceptance-scenarios.md", "scenarios")

    ap.publish(f.project_root, wt)
    readme = (f.archive_dir() / "t-18" / "README.md").read_text(encoding="utf-8")
    assert 'acceptance_report: "acceptance-report.md"' in readme
    assert 'acceptance_scenarios: "acceptance-scenarios.md"' in readme

    content = (wt / ".devflow" / "task.yaml").read_text(encoding="utf-8")
    assert 'published: ".devflow/tasks/t-18/acceptance-report.md"' in content
    assert 'published: ".devflow/tasks/t-18/acceptance-scenarios.md"' in content


def test_update_writes_dual_path_refs():
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_task("t-14", "t-fourteen")
    f.artifact(wt, "prd.md", "prd")
    f.artifact(wt, "architecture.md", "arch")
    f.artifact(wt, "scope.yaml", "scope")

    _actions, mapping = ap.plan_publish(wt, f.archive_dir() / "t-14")
    ap.update_task_artifact_refs(wt, "t-14", "t-fourteen", mapping)

    content = (wt / ".devflow" / "task.yaml").read_text(encoding="utf-8")
    assert 'worktree: ".devflow/prd.md"' in content
    assert 'published: ".devflow/tasks/t-14/prd-t-fourteen.md"' in content
    assert 'worktree: ".devflow/architecture.md"' in content

    # task.yaml still parseable (id/slug intact).
    record = load_task(wt / ".devflow" / "task.yaml")
    assert record.task_id == "t-14"


def test_update_preserves_delivery_field_and_writes_single_state_file():
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_legacy_worktree("t-15", "t-fifteen")
    f.artifact(wt, "prd.md", "prd")

    _actions, mapping = ap.plan_publish(wt, f.archive_dir() / "t-15")
    ap.update_task_artifact_refs(wt, "t-15", "t-fifteen", mapping)

    content = (wt / ".devflow" / "task.yaml").read_text(encoding="utf-8")
    # delivery is a legacy scalar, preserved.
    assert 'delivery: ".devflow/delivery.yaml"' in content
    # Publishing an isolated task updates only its own state: the archive
    # root (f.project_root) must gain no second task.yaml.
    assert not ((f.project_root / ".devflow" / "task.yaml").exists())
    # ...and the copy really did rewrite refs at the source.
    assert "published:" in content


def test_cli_dry_run_outputs_plan_json():
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_task("t-17", "t-seventeen")
    f.artifact(wt, "prd.md", "prd")

    with contextlib.redirect_stdout(io.StringIO()):
        out = ap.main(
            [
                "publish",
                "--root",
                str(f.project_root),
                "--repo-root",
                str(f.repo),
                "--task",
                "t-17",
                "--dry-run",
            ]
        )
    # dry-run returns 0 when no errors/conflicts.
    assert out == 0


def test_cli_conflict_exits_nonzero():
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_task("t-18", "t-eighteen")
    f.artifact(wt, "prd.md", "new")

    target = f.archive_dir() / "t-18"
    target.mkdir(parents=True)
    (target / "prd-t-eighteen.md").write_text("old", encoding="utf-8")

    with contextlib.redirect_stdout(io.StringIO()):
        out = ap.main(
            [
                "publish",
                "--root",
                str(f.project_root),
                "--repo-root",
                str(f.repo),
                "--task",
                "t-18",
            ]
        )
    assert out == 1


def test_cli_missing_root_exits_nonzero():
    f = _Fixture(tempfile.mkdtemp())
    with contextlib.redirect_stdout(io.StringIO()):
        out = ap.main(
            [
                "publish",
                "--root",
                str(f.parent / "nope"),
                "--repo-root",
                str(f.repo),
                "--all-tasks",
            ]
        )
    assert out == 1


def test_cli_missing_discovery_exits_nonzero():
    f = _Fixture(tempfile.mkdtemp())
    with contextlib.redirect_stdout(io.StringIO()):
        out = ap.main(
            [
                "publish",
                "--root",
                str(f.project_root),
                "--repo-root",
                str(f.repo),
                "--task",
                "missing",
            ]
        )
    assert out == 1


def test_cli_archives_to_devflow_tasks_not_docs():
    # AC-12: archive lands in .devflow/tasks/, docs/tasks/ is never created.
    f = _Fixture(tempfile.mkdtemp())
    wt = f.make_task("t-ac12", "t-ac12")
    f.artifact(wt, "prd.md", "prd")

    with contextlib.redirect_stdout(io.StringIO()):
        out = ap.main(
            [
                "publish",
                "--root",
                str(f.project_root),
                "--repo-root",
                str(f.repo),
                "--task",
                "t-ac12",
            ]
        )
    assert out == 0
    assert (f.archive_dir() / "t-ac12" / "prd-t-ac12.md").is_file()
    assert not ((f.repo / "docs" / "tasks").exists())


def test_cli_form_a_archives_inside_repo():
    # Form A: project_root == repo_root; the archive lives under the repo's
    # own .devflow/tasks/ and the worktree still lives under repo.parent.
    f = _Fixture(tempfile.mkdtemp(), form_a=True)
    wt = f.make_task("t-forma", "t-form-a")
    f.artifact(wt, "prd.md", "prd")

    with contextlib.redirect_stdout(io.StringIO()):
        out = ap.main(
            [
                "publish",
                "--root",
                str(f.project_root),
                "--repo-root",
                str(f.repo),
                "--task",
                "t-forma",
            ]
        )
    assert out == 0
    # project_root == repo_root, so archive is under the repo itself.
    assert (f.repo / ".devflow" / "tasks" / "t-forma" / "prd-t-form-a.md").is_file()
    assert not ((f.repo / "docs" / "tasks").exists())

