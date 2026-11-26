#!/usr/bin/env python3
"""Tests for isolated DevFlow task state and Git worktree creation."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

ORCHESTRATOR = Path(__file__).resolve().parents[1] / "orchestrator"
sys.path.insert(0, str(ORCHESTRATOR))

from task_state import RepoEndpoint, TaskRecord, load_task, render_task_yaml
from worktree_manager import (
    WorktreeError,
    activate_endpoint,
    create_task,
    describe_git_skips,
    discover_tasks,
    resolve_project_root,
)


def test_render_and_load_round_trip():
    record = TaskRecord(
        task_id="fix-login-a1b2",
        slug="fix-login",
        kind="bugfix",
        description="Fix login timeout",
        base_ref="main",
        base_commit="abc123",
        branch="fix/fix-login-a1b2",
        working_dir="/tmp/fix-login-a1b2",
        source_task_id="feature-login-old",
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "task.yaml"
        path.write_text(render_task_yaml(record), encoding="utf-8")
        assert load_task(path) == record


def test_endpoint_activated_round_trips() -> None:
    record = TaskRecord(
        task_id="feat-x-a1b2",
        slug="feat-x",
        kind="feature",
        description="Cross repo",
        base_ref="main",
        base_commit="abc123",
        branch="feature/feat-x-a1b2",
        working_dir="/tmp/anchor",
        endpoints=(
            RepoEndpoint("frontend", "/tmp/fe", "main", "def456",
                         "feature/feat-x-a1b2", activated=False),
            RepoEndpoint("backend", "/tmp/be", "main", "ghi789",
                         "feature/feat-x-a1b2", activated=True),
        ),
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "task.yaml"
        path.write_text(render_task_yaml(record), encoding="utf-8")
        assert load_task(path) == record


def test_endpoint_without_activated_defaults_false() -> None:
    # Legacy task.yaml predates the activated field; absence reads as False.
    content = (
        'schema_version: 2\n\ntask:\n  id: "t1"\n  slug: "t"\n'
        '  kind: "feature"\n  description: "d"\n  current_phase: "done"\n'
        '  status: "done"\n\ngit:\n  base_ref: "main"\n  base_commit: "c"\n'
        '  branch: "feature/t1"\n  working_dir: "/tmp/a"\n'
        '  endpoints:\n    - track: "frontend"\n      git_root: "/tmp/fe"\n'
        '      base_ref: "main"\n      base_commit: "c"\n'
        '      branch: "feature/t1"\n'
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "task.yaml"
        path.write_text(content, encoding="utf-8")
        ep = load_task(path).endpoints[0]
        assert not (ep.activated)


def _repository(temp_dir, name="repo"):
    root = Path(temp_dir) / name
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    (root / "README.md").write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=DevFlow",
            "-c",
            "user.email=devflow@example.invalid",
            "commit",
            "-qm",
            "initial",
        ],
        cwd=root,
        check=True,
    )
    return root


def test_first_task_is_in_place_second_is_rejected():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = _repository(temp_dir)
        feature = create_task(root, "Add weekly report", "feature")

        assert Path(feature.working_dir).resolve() == root.resolve()
        assert load_task(root / ".devflow" / "task.yaml").kind == "feature"

        with pytest.raises(WorktreeError) as ctx:
            create_task(
                root, "Fix completed report bug", "bugfix", source_task_id=feature.task_id
            )
        assert "/devflow next" in str(ctx.value)

        # Nothing was created for the refused task: no worktree tree, and
        # the only branches are the base plus the first task's feature.
        assert not ((root.parent / ".devflow-worktrees").exists())
        branches = subprocess.run(
            ["git", "branch", "--format=%(refname:short)"],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.split()
        assert sorted(branches) == sorted(["main", feature.branch])
        assert {record.task_id for record in discover_tasks(root)} == {feature.task_id}


def test_new_in_place_task_snapshots_the_finished_one():
    # Two in-place tasks share repo_root/.devflow/task.yaml. Without a
    # snapshot the first task's id/branch/parent chain is lost when the
    # second one starts.
    with tempfile.TemporaryDirectory() as temp_dir:
        root = _repository(temp_dir)
        first = create_task(root, "First chore", "chore")
        (root / ".devflow" / "task.yaml").write_text(
            render_task_yaml(first, current_phase="done").replace(
                'status: "active"', 'status: "done"'
            ),
            encoding="utf-8",
        )
        subprocess.run(["git", "checkout", "-q", "main"], cwd=root, check=True)

        second = create_task(root, "Second chore", "chore")

        assert Path(second.working_dir).resolve() == root.resolve()
        assert load_task(root / ".devflow" / "task.yaml").task_id == second.task_id
        snapshot = root / ".devflow" / "tasks" / first.task_id / "task.yaml"
        assert snapshot.is_file(), "previous task state was not snapshotted"
        assert load_task(snapshot).task_id == first.task_id


def test_create_task_always_writes_in_place_worktree_path():
    # The record always names the repo itself; the retired isolation layout
    # must never appear in state written today.
    with tempfile.TemporaryDirectory() as temp_dir:
        root = _repository(temp_dir)
        record = create_task(root, "In-place only", "feature")
        assert Path(record.working_dir).resolve() == root.resolve()
        assert ".devflow-worktrees" not in record.working_dir
        content = (root / ".devflow" / "task.yaml").read_text(encoding="utf-8")
        assert ".devflow-worktrees" not in content


def test_state_written_to_launch_dir_when_started_at_project_root():
    # The root is the launch directory. Starting a task at the project
    # (which owns .devflow/) writes state there, even when git repositories
    # live in subdirectories. The project itself is not a git repository,
    # so git operations are skipped and reported, not fatal.
    with tempfile.TemporaryDirectory() as temp_dir:
        project = Path(temp_dir) / "project"
        project.mkdir()
        (project / ".devflow").mkdir()
        (project / ".devflow" / "project.yaml").write_text(
            "workspace:\n  root: .\n", encoding="utf-8"
        )
        repo = project / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        (repo / "README.md").write_text("initial\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
        subprocess.run(
            ["git", "-c", "user.name=DevFlow", "-c", "user.email=d@example.invalid",
             "commit", "-qm", "initial"],
            cwd=repo,
            check=True,
        )

        with mock.patch("builtins.print"):
            record = create_task(project, "Project-root task", "chore")

        state = project / ".devflow" / "task.yaml"
        assert state.is_file(), "state was not written to the launch dir"
        assert load_task(state).task_id == record.task_id
        assert Path(record.working_dir).resolve() == project.resolve()
        assert not ((repo / ".devflow" / "task.yaml").exists())


def test_resolve_project_root_falls_back_to_repo_root():
    # No ancestor declares a workspace root, so an ordinary project keeps its
    # previous behaviour and writes state beside the repository.
    with tempfile.TemporaryDirectory() as temp_dir:
        root = _repository(temp_dir)
        assert resolve_project_root(root) == root.resolve()


def test_resolve_project_root_does_not_search_upward():
    # Root = the directory itself when it owns .devflow. An ancestor's
    # .devflow must never capture a nested directory: "drill down, never up".
    with tempfile.TemporaryDirectory() as temp_dir:
        project = Path(temp_dir) / "project"
        (project / ".devflow").mkdir(parents=True)
        (project / ".devflow" / "project.yaml").write_text(
            "workspace:\n  root: .\n", encoding="utf-8"
        )
        repo = project / "repo"
        repo.mkdir()
        # repo has no .devflow of its own → falls back to itself, not project.
        assert resolve_project_root(repo) == repo.resolve()
        # project owns .devflow → it is its own root.
        assert resolve_project_root(project) == project.resolve()


def test_unfinished_task_under_project_root_blocks_in_place():
    # A task left running at the project root must block the next one;
    # otherwise both would claim the same working tree.
    with tempfile.TemporaryDirectory() as temp_dir:
        project = Path(temp_dir) / "project"
        (project / ".devflow").mkdir(parents=True)
        (project / ".devflow" / "project.yaml").write_text(
            "workspace:\n  root: .\n", encoding="utf-8"
        )
        repo = project / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        (repo / "README.md").write_text("initial\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
        subprocess.run(
            ["git", "-c", "user.name=DevFlow", "-c", "user.email=d@example.invalid",
             "commit", "-qm", "initial"],
            cwd=repo,
            check=True,
        )
        first = create_task(repo, "First task", "chore")
        with pytest.raises(WorktreeError):
            create_task(repo, "Second task", "chore")
        ids = {r.task_id for r in discover_tasks(repo)}
        assert ids == {first.task_id}


def test_create_task_writes_v2_state_without_context_json():
    # ADR-0005: task.yaml is self-sufficient; the runtime context.json is
    # retired. The state file carries the v2 initial phase "qa".
    with tempfile.TemporaryDirectory() as temp_dir:
        root = _repository(temp_dir)
        (root / ".devflow").mkdir(exist_ok=True)
        (root / ".devflow" / "project.yaml").write_text(
            'workspace:\n  root: "."\n',
            encoding="utf-8",
        )
        create_task(root, "Add v2 state", "feature")
        assert not ((root / ".devflow" / "context.json").exists())
        content = (root / ".devflow" / "task.yaml").read_text(encoding="utf-8")
        assert 'current_phase: "qa"' in content
        # ADR-0006 D1 replaced the prd/card pair with a single plan slot.
        assert 'plan: ".devflow/plan.md"' in content
        assert "verification: null" in content


def test_dirty_workspace_with_active_task_is_still_rejected():
    # Uncommitted work in a busy workspace makes sharing it even worse, so
    # the refusal must hold regardless of dirtiness — it is the active task
    # that blocks the request, not the cleanliness check.
    with tempfile.TemporaryDirectory() as temp_dir:
        root = _repository(temp_dir)
        feature = create_task(root, "Add weekly report", "feature")
        (root / "README.md").write_text("wip\n", encoding="utf-8")
        with pytest.raises(WorktreeError) as ctx:
            create_task(root, "Prod hotfix", "bugfix", source_task_id=feature.task_id)
        assert "unfinished task" in str(ctx.value)
        # The in-place task's state is untouched.
        assert load_task(root / ".devflow" / "task.yaml").task_id == feature.task_id


def test_untracked_files_do_not_block_task_creation():
    # AC-15: an untracked file (e.g. a prior task's unpublished artifacts)
    # must not block creating a new task worktree.
    with tempfile.TemporaryDirectory() as temp_dir:
        root = _repository(temp_dir)
        (root / "uncommitted.txt").write_text("do not copy\n", encoding="utf-8")
        record = create_task(root, "Safe task", "feature")
        assert record.kind == "feature"


def test_tracked_modifications_block_task_creation():
    # A change to an already-tracked file (M) is a real uncommitted change
    # and must still block worktree creation.
    with tempfile.TemporaryDirectory() as temp_dir:
        root = _repository(temp_dir)
        (root / "README.md").write_text("modified\n", encoding="utf-8")
        with pytest.raises(WorktreeError):
            create_task(root, "Unsafe task", "feature")


def test_tracked_additions_block_task_creation():
    # A newly staged/added tracked file (A) is a committed-change conflict.
    with tempfile.TemporaryDirectory() as temp_dir:
        root = _repository(temp_dir)
        (root / "extra.txt").write_text("staged\n", encoding="utf-8")
        subprocess.run(["git", "add", "extra.txt"], cwd=root, check=True)
        with pytest.raises(WorktreeError):
            create_task(root, "Unsafe task", "feature")


def test_ignored_files_do_not_block_task_creation():
    # Ignored files (!!) are invisible to the dirty check and must not block.
    with tempfile.TemporaryDirectory() as temp_dir:
        root = _repository(temp_dir)
        (root / ".gitignore").write_text("*.log\n", encoding="utf-8")
        subprocess.run(["git", "add", ".gitignore"], cwd=root, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=DevFlow",
                "-c",
                "user.email=devflow@example.invalid",
                "commit",
                "-qm",
                "gitignore",
            ],
            cwd=root,
            check=True,
        )
        (root / "debug.log").write_text("ignored\n", encoding="utf-8")
        record = create_task(root, "Ignored task", "feature")
        assert record.kind == "feature"


def _multi_repo_fixture(temp_dir):
    """Create an anchor backend repo plus a separated frontend repo, and a
    ``project.yaml`` declaring the ``workspaces:`` endpoint list."""
    anchor = _repository(temp_dir, name="backend")
    frontend = _repository(temp_dir, name="frontend")
    (anchor / ".devflow").mkdir(exist_ok=True)
    (anchor / ".devflow" / "project.yaml").write_text(
        "workspaces:\n"
        f'  - track: "backend"\n'
        f'    git_root: "{anchor}"\n'
        f'  - track: "frontend"\n'
        f'    git_root: "{frontend}"\n',
        encoding="utf-8",
    )
    return anchor, frontend


def test_multi_repo_accepts_path_alias() -> None:
    # path: is an alias of git_root: (same key name as workspace.*.path);
    # the endpoint must not be silently dropped.
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor, frontend = _multi_repo_fixture(temp_dir)
        (anchor / ".devflow" / "project.yaml").write_text(
            "workspaces:\n"
            f'  - track: "frontend"\n'
            f'    path: "{frontend}"\n',
            encoding="utf-8",
        )
        record = create_task(anchor, "Path alias task", "feature")
        assert len(record.endpoints) == 1
        assert record.endpoints[0].track == "frontend"
        assert record.endpoints[0].git_root == str(frontend.resolve())


def test_multi_repo_git_root_wins_over_path() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor, frontend = _multi_repo_fixture(temp_dir)
        (anchor / ".devflow" / "project.yaml").write_text(
            "workspaces:\n"
            f'  - track: "frontend"\n'
            f'    git_root: "{frontend}"\n'
            f'    path: "/nonexistent/alias"\n',
            encoding="utf-8",
        )
        record = create_task(anchor, "Both keys task", "feature")
        assert record.endpoints[0].git_root == str(frontend.resolve())


def test_multi_repo_named_endpoint_missing_root_raises() -> None:
    # A named endpoint declaring neither git_root: nor path: is a config
    # error — raise with track + file context, never silently drop it.
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor, _frontend = _multi_repo_fixture(temp_dir)
        (anchor / ".devflow" / "project.yaml").write_text(
            "workspaces:\n"
            '  - track: "frontend"\n'
            '    remote: "origin"\n',
            encoding="utf-8",
        )
        with pytest.raises(WorktreeError) as ctx:
            create_task(anchor, "Broken config task", "feature")
        message = str(ctx.value)
        assert "frontend" in message
        assert "project.yaml" in message
        assert "git_root" in message


def test_multi_repo_trackless_entry_skipped() -> None:
    # An entry without a track has nothing to name or fix — skip, not raise.
    # Regression (verifier Round 1): the natural `- remote: origin` residue
    # used to be misread as track='origin' and triggered the new loud error.
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor, frontend = _multi_repo_fixture(temp_dir)
        (anchor / ".devflow" / "project.yaml").write_text(
            "workspaces:\n"
            '  - remote: "origin"\n'
            f'  - track: "frontend"\n'
            f'    git_root: "{frontend}"\n',
            encoding="utf-8",
        )
        record = create_task(anchor, "Trackless residue task", "feature")
        assert len(record.endpoints) == 1
        assert record.endpoints[0].track == "frontend"


def test_multi_repo_first_key_path_with_indented_track_skipped() -> None:
    # H1 (review high): main never parsed an indented `track:` after a
    # non-track first key. It must stay skipped, NOT become a hard error.
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor, frontend = _multi_repo_fixture(temp_dir)
        (anchor / ".devflow" / "project.yaml").write_text(
            "workspaces:\n"
            f'  - path: "{frontend}"\n'
            '    track: "frontend"\n',
            encoding="utf-8",
        )
        record = create_task(anchor, "Legacy indented track task", "feature")
        assert len(record.endpoints) == 0


def test_multi_repo_comment_placeholder_root_skipped() -> None:
    # `git_root:   # to be filled in` is a placeholder, not a broken path.
    # main silently dropped it; it must not become a hard error.
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor, _frontend = _multi_repo_fixture(temp_dir)
        (anchor / ".devflow" / "project.yaml").write_text(
            "workspaces:\n"
            '  - track: "frontend"\n'
            '    git_root:   # to be filled in\n',
            encoding="utf-8",
        )
        with pytest.raises(WorktreeError) as ctx:
            create_task(anchor, "Placeholder task", "feature")
        # First-key named endpoint still raises (that IS a config error),
        # but with actionable guidance, not a bogus path.
        assert "add `git_root:`" in str(ctx.value)


def test_multi_repo_trailing_comment_in_path() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor, frontend = _multi_repo_fixture(temp_dir)
        (anchor / ".devflow" / "project.yaml").write_text(
            "workspaces:\n"
            f'  - track: "frontend"\n'
            f'    path: "{frontend}" # alias\n',
            encoding="utf-8",
        )
        record = create_task(anchor, "Trailing comment task", "feature")
        assert record.endpoints[0].git_root == str(frontend.resolve())


def test_multi_repo_config_error_precedes_active_task_guard() -> None:
    # M1: a broken workspaces: config must be reported as itself even when
    # an unfinished task exists (guard used to shadow it).
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor, _frontend = _multi_repo_fixture(temp_dir)
        create_task(anchor, "First task", "feature")
        (anchor / ".devflow" / "project.yaml").write_text(
            "workspaces:\n"
            '  - track: "frontend"\n'
            '    remote: "origin"\n',
            encoding="utf-8",
        )
        with pytest.raises(WorktreeError) as ctx:
            create_task(anchor, "Second task", "feature")
        assert "declares neither" in str(ctx.value)


def test_multi_repo_defers_endpoint_branch_until_activation():
    # Lazy endpoint branches (plan A): create_task branches only the anchor.
    # Endpoints are recorded as candidates (activated=False) with their base
    # commit frozen, but no branch is created and HEAD stays on main.
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor, frontend = _multi_repo_fixture(temp_dir)
        record = create_task(anchor, "Cross repo feature", "feature")

        # Anchor (where .devflow lives) is not re-listed as an endpoint.
        assert len(record.endpoints) == 1
        ep = record.endpoints[0]
        assert ep.track == "frontend"
        assert ep.git_root == str(frontend.resolve())
        assert ep.branch == record.branch
        assert not (ep.activated)

        # Anchor carries the branch; the endpoint does NOT yet.
        be_branches = subprocess.run(
            ["git", "branch", "--list", record.branch],
            cwd=anchor, text=True, capture_output=True, check=True,
        ).stdout.strip()
        fe_branches = subprocess.run(
            ["git", "branch", "--list", record.branch],
            cwd=frontend, text=True, capture_output=True, check=True,
        ).stdout.strip()
        assert record.branch in be_branches
        assert record.branch not in fe_branches
        fe_head = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=frontend, text=True, capture_output=True, check=True,
        ).stdout.strip()
        assert fe_head == "main"

        # Base commit is frozen at creation even though the branch is deferred.
        assert ep.base_commit

        # task.yaml carries the candidate endpoint, marked not activated.
        anchor_task = load_task(anchor / ".devflow" / "task.yaml")
        assert len(anchor_task.endpoints) == 1
        assert anchor_task.endpoints[0].track == "frontend"
        assert not (anchor_task.endpoints[0].activated)


def test_activate_endpoint_creates_branch_and_marks_activated():
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor, frontend = _multi_repo_fixture(temp_dir)
        record = create_task(anchor, "Cross repo feature", "feature")
        state_file = anchor / ".devflow" / "task.yaml"
        # Advance phase + add an artifact ref so writeback must preserve them.
        text = state_file.read_text(encoding="utf-8")
        text = text.replace('current_phase: "qa"', 'current_phase: "working"')
        state_file.write_text(text, encoding="utf-8")

        ep = activate_endpoint(anchor, "frontend")
        assert ep.activated
        assert ep.branch == record.branch

        fe_branches = subprocess.run(
            ["git", "branch", "--list", record.branch],
            cwd=frontend, text=True, capture_output=True, check=True,
        ).stdout.strip()
        assert record.branch in fe_branches
        fe_head = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=frontend, text=True, capture_output=True, check=True,
        ).stdout.strip()
        assert fe_head == record.branch

        # Writeback preserved phase and flipped only this endpoint's flag.
        reloaded = load_task(state_file)
        assert reloaded.endpoints[0].activated
        assert 'current_phase: "working"' in state_file.read_text(encoding="utf-8")


def test_activate_endpoint_is_idempotent():
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor, _frontend = _multi_repo_fixture(temp_dir)
        record = create_task(anchor, "Cross repo feature", "feature")
        first = activate_endpoint(anchor, "frontend")
        # Second call must not raise (branch already exists) and stays activated.
        second = activate_endpoint(anchor, "frontend")
        assert first.activated
        assert second.activated
        assert second.branch == record.branch


def test_activate_endpoint_unknown_track_raises():
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor, _frontend = _multi_repo_fixture(temp_dir)
        create_task(anchor, "Cross repo feature", "feature")
        with pytest.raises(WorktreeError):
            activate_endpoint(anchor, "nonexistent")


def test_activate_endpoint_git_failure_writes_no_state():
    # plan promise: "On git failure nothing is written." A checkout failure
    # must leave task.yaml byte-identical (activated still false).
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor, _frontend = _multi_repo_fixture(temp_dir)
        create_task(anchor, "Cross repo feature", "feature")
        state_file = anchor / ".devflow" / "task.yaml"
        before = state_file.read_text(encoding="utf-8")
        with mock.patch(
            "worktree_manager._git", side_effect=WorktreeError("checkout failed")
        ), pytest.raises(WorktreeError):
            activate_endpoint(anchor, "frontend")
        assert state_file.read_text(encoding="utf-8") == before
        assert not (load_task(state_file).endpoints[0].activated)


def test_mark_endpoint_activated_missing_field_raises():
    # Legacy/hand-edited endpoint without an activated: line must raise and
    # leave the file untouched (no truncation).
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor, _frontend = _multi_repo_fixture(temp_dir)
        create_task(anchor, "Cross repo feature", "feature")
        state_file = anchor / ".devflow" / "task.yaml"
        text = state_file.read_text(encoding="utf-8")
        stripped = "\n".join(
            l for l in text.splitlines() if not l.strip().startswith("activated:")
        ) + "\n"
        state_file.write_text(stripped, encoding="utf-8")
        from worktree_manager import _mark_endpoint_activated
        with pytest.raises(WorktreeError):
            _mark_endpoint_activated(state_file, "frontend")
        assert state_file.read_text(encoding="utf-8") == stripped


def test_activate_endpoint_cli_entry():
    # The contract prose names an executable command; verify it runs.
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor, frontend = _multi_repo_fixture(temp_dir)
        record = create_task(anchor, "Cross repo feature", "feature")
        from worktree_manager import main
        rc = main(["activate-endpoint", "--root", str(anchor), "--track", "frontend"])
        assert rc == 0
        assert load_task(anchor / ".devflow" / "task.yaml").endpoints[0].activated
        fe_head = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=frontend, text=True, capture_output=True, check=True,
        ).stdout.strip()
        assert fe_head == record.branch
        # Unknown track via CLI returns non-zero, not a traceback.
        rc = main(["activate-endpoint", "--root", str(anchor), "--track", "nope"])
        assert rc == 1


def test_multi_repo_rolls_back_anchor_branch_on_failure():
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor, frontend = _multi_repo_fixture(temp_dir)
        # A declared endpoint that is not a git repo is a config error raised
        # during candidate resolution, before any checkout. Break it so
        # _build_endpoints raises; the anchor must stay on main.
        shutil.rmtree(frontend / ".git")
        with pytest.raises(WorktreeError):
            create_task(anchor, "Broken cross repo", "feature")
        current = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=anchor, text=True, capture_output=True, check=True,
        ).stdout.strip()
        assert current == "main"


def test_multi_repo_failure_leaves_no_task_state():
    # Regression: state used to be seeded before the endpoint checkouts, so
    # a failed endpoint left a task.yaml naming branches the rollback then
    # deleted. The rollback must leave the workspace as it found it.
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor, frontend = _multi_repo_fixture(temp_dir)
        shutil.rmtree(frontend / ".git")
        with pytest.raises(WorktreeError):
            create_task(anchor, "Broken cross repo", "feature")
        assert not ((anchor / ".devflow" / "task.yaml").exists())
        assert not ((anchor / ".devflow" / "tasks").exists())


def test_multi_repo_failure_preserves_the_previous_task_state():
    # A failed multi-repo start must not disturb the record of the task that
    # already finished (its state is the one live when the next one starts).
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor, frontend = _multi_repo_fixture(temp_dir)
        first = create_task(anchor, "First task", "chore")
        state_file = anchor / ".devflow" / "task.yaml"
        state_file.write_text(
            render_task_yaml(first, current_phase="done").replace(
                'status: "active"', 'status: "done"'
            ),
            encoding="utf-8",
        )
        subprocess.run(["git", "checkout", "-q", "main"], cwd=anchor, check=True)
        broken = anchor / ".devflow" / "task.yaml"
        before = broken.read_text(encoding="utf-8")

        shutil.rmtree(frontend / ".git")
        with pytest.raises(WorktreeError):
            create_task(anchor, "Second task", "chore")

        assert broken.read_text(encoding="utf-8") == before
        assert load_task(broken).task_id == first.task_id


def test_non_git_root_creates_task_without_branch():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "plain"
        (root / ".devflow").mkdir(parents=True)
        with mock.patch("builtins.print"):
            record = create_task(root, "Plain task", "chore")
        assert Path(record.working_dir).resolve() == root.resolve()
        assert record.base_commit == ""
        # State is readable even though git fields are empty.
        assert load_task(root / ".devflow" / "task.yaml").task_id == record.task_id
        assert describe_git_skips(root) == [f"not a git repository: {root.resolve()} (no branch, no base_commit)"]


def test_clean_git_root_reports_no_skips():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = _repository(temp_dir)
        assert describe_git_skips(root) == []


def test_declared_non_git_endpoint_raises():
    with tempfile.TemporaryDirectory() as temp_dir:
        ws = Path(temp_dir) / "ws"
        _repository(temp_dir, name="ws")  # ws is a git repo
        (ws / ".devflow").mkdir(exist_ok=True)
        (ws / ".devflow/project.yaml").write_text(
            'workspace:\n  root: "."\nworkspaces:\n'
            '  - track: "frontend"\n    git_root: "./repo-x"\n',
            encoding="utf-8",
        )
        (ws / "repo-x").mkdir()  # exists but not a git repo root
        with pytest.raises(WorktreeError) as ctx:
            create_task(ws, "Broken cross repo", "feature")
        assert "not a git repository root" in str(ctx.value)


def test_auto_skip_suppresses_the_report():
    # Explicit opt-in to silence; git_policy: ask (or absent) still reports.
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "plain"
        (root / ".devflow").mkdir(parents=True)
        (root / ".devflow/project.yaml").write_text(
            'workspace:\n  root: "."\n  git_policy: auto_skip\n', encoding="utf-8"
        )
        assert describe_git_skips(root) == []
        with mock.patch("builtins.print") as printed:
            create_task(root, "Quiet task", "chore")
        printed.assert_not_called()


def test_non_git_root_announces_the_skip():
    # "Show a hint unless auto-agreed": create_task must actually print.
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "plain"
        (root / ".devflow").mkdir(parents=True)
        with mock.patch("builtins.print") as printed:
            create_task(root, "Announced task", "chore")
        messages = [str(call.args[0]) for call in printed.call_args_list if call.args]
        assert any("not a git repository" in m for m in messages)


def test_git_root_prints_nothing():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = _repository(temp_dir)
        with mock.patch("builtins.print") as printed:
            create_task(root, "Git task", "feature")
        printed.assert_not_called()


def test_subdirectory_of_repo_is_not_a_git_root():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = _repository(temp_dir)
        sub = root / "sub"
        sub.mkdir()
        # sub is inside a repository but is not its own top level.
        assert describe_git_skips(sub)

