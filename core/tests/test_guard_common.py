#!/usr/bin/env python3
"""Unit tests for worktree mapping and shell write-target extraction."""

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS))

from devflow_guard_common import (
    _extract_shell_write_targets,
    _newest_plugin_dir,
    _parse_workspaces,
    detect_worktree,
    is_user_agent_state,
    is_within_boundary,
)


def test_task_worktree_main_root_is_git_repo_not_worktrees_parent() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir)
        repo = home / "myapp"
        repo.mkdir()
        wt = home / ".devflow-worktrees" / "myapp" / "task-abc"
        (wt / ".devflow").mkdir(parents=True)
        (wt / ".devflow" / "task.yaml").write_text("task:\n  id: task-abc\n", encoding="utf-8")
        src = wt / "server" / "main.go"
        src.parent.mkdir()
        src.write_text("package main\n", encoding="utf-8")

        wt_root, main_root = detect_worktree(str(src))
        assert Path(wt_root).resolve() == wt.resolve()
        assert Path(main_root).resolve() == repo.resolve()


def test_in_place_task_yaml_is_not_an_external_worktree() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        repo = Path(temp_dir) / "repo"
        (repo / ".devflow").mkdir(parents=True)
        (repo / ".devflow" / "task.yaml").write_text(
            "task:\n  id: in-place\n", encoding="utf-8"
        )
        wt_root, main_root = detect_worktree(str(repo / "src"))
        assert wt_root is None
        assert main_root is None


def test_cp_and_mv_destinations_are_extracted() -> None:
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
        assert ".env" in targets
        assert ".devflow/redlines.yaml" in targets


def test_python_c_quoted_paths_are_extracted() -> None:
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
        assert ".env" in targets


def test_git_apply_reads_plus_plus_plus_paths() -> None:
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
        assert ".env" in targets


def test_picks_highest_version() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        v1 = Path(temp_dir) / "1.0.0"
        v2 = Path(temp_dir) / "1.1.0"
        v1.mkdir()
        v2.mkdir()
        assert _newest_plugin_dir([str(v1), str(v2)]) == str(v2)


def _import():
    from devflow_guard_common import (
        _parse_task_id,
        is_git_commit,
        task_needs_archive,
    )

    return _parse_task_id, is_git_commit, task_needs_archive


def test_parse_task_id_nested() -> None:
    _parse_task_id, _, _ = _import()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / ".devflow").mkdir()
        (root / ".devflow" / "task.yaml").write_text(
            'task:\n  id: "task-abc"\n  kind: "feature"\n', encoding="utf-8"
        )
        assert _parse_task_id(root) == "task-abc"


def test_parse_task_id_missing() -> None:
    _parse_task_id, _, _ = _import()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / ".devflow").mkdir()
        assert _parse_task_id(root) == ""


def test_task_needs_archive_without_index() -> None:
    _, _, task_needs_archive = _import()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / ".devflow").mkdir()
        (root / ".devflow" / "task.yaml").write_text(
            'task:\n  id: "task-abc"\n', encoding="utf-8"
        )
        assert task_needs_archive(root)


def test_task_needs_archive_false_after_index() -> None:
    _, _, task_needs_archive = _import()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / ".devflow").mkdir()
        (root / ".devflow" / "task.yaml").write_text(
            'task:\n  id: "task-abc"\n', encoding="utf-8"
        )
        index = root / ".devflow" / "tasks" / "task-abc" / "README.md"
        index.parent.mkdir(parents=True)
        index.write_text("# x\n", encoding="utf-8")
        assert not (task_needs_archive(root))


def test_task_needs_archive_legacy_no_task_yaml() -> None:
    _, _, task_needs_archive = _import()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / ".devflow").mkdir()
        assert not (task_needs_archive(root))


def test_is_git_commit() -> None:
    _, is_git_commit, _ = _import()
    assert is_git_commit("git commit -m 'feat: x'")
    assert is_git_commit("git commit --amend")
    assert not (is_git_commit("git status"))
    assert not (is_git_commit("git push"))


def test_is_within_boundary_is_project_root_scoped() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor = Path(temp_dir) / "backend"
        frontend = Path(temp_dir) / "frontend"
        anchor.mkdir()
        frontend.mkdir()
        # Boundary is the project root: anything beneath it is allowed,
        # anything outside is refused. There is no per-track gating.
        assert is_within_boundary(str(anchor / "internal" / "x.go"), anchor)
        assert not (is_within_boundary(str(frontend / "src" / "App.tsx"), anchor))
        assert is_within_boundary(str(anchor / "internal" / "x.go"), Path(temp_dir))


def test_parse_workspaces_resolves_relative_git_root() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor = Path(temp_dir) / "backend"
        frontend = Path(temp_dir) / "frontend"
        anchor.mkdir()
        frontend.mkdir()
        (anchor / ".devflow").mkdir(parents=True)
        (anchor / ".devflow" / "project.yaml").write_text(
            "workspaces:\n"
            '  - track: "backend"\n'
            '    git_root: "."\n'
            '  - track: "frontend"\n'
            '    git_root: "../frontend"\n',
            encoding="utf-8",
        )
        endpoints = _parse_workspaces(anchor)
        assert len(endpoints) == 2
        assert endpoints[1]["track"] == "frontend"
        assert endpoints[1]["git_root"] == str(frontend.resolve())


def test_parse_workspaces_accepts_path_alias() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor = Path(temp_dir) / "backend"
        frontend = Path(temp_dir) / "frontend"
        anchor.mkdir()
        frontend.mkdir()
        (anchor / ".devflow").mkdir(parents=True)
        (anchor / ".devflow" / "project.yaml").write_text(
            "workspaces:\n"
            '  - track: "frontend"\n'
            '    path: "../frontend"\n',
            encoding="utf-8",
        )
        endpoints = _parse_workspaces(anchor)
        assert len(endpoints) == 1
        assert endpoints[0]["git_root"] == str(frontend.resolve())


def test_parse_workspaces_git_root_wins_over_path() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor = Path(temp_dir) / "backend"
        (anchor / ".devflow").mkdir(parents=True)
        (anchor / ".devflow" / "project.yaml").write_text(
            "workspaces:\n"
            '  - track: "frontend"\n'
            '    git_root: "./real"\n'
            '    path: "./alias"\n',
            encoding="utf-8",
        )
        endpoints = _parse_workspaces(anchor)
        assert endpoints[0]["git_root"] == str((anchor / "real").resolve())


def test_parse_workspaces_missing_root_skipped_not_raised() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor = Path(temp_dir) / "backend"
        (anchor / ".devflow").mkdir(parents=True)
        (anchor / ".devflow" / "project.yaml").write_text(
            "workspaces:\n"
            '  - track: "frontend"\n'
            '    remote: "origin"\n',
            encoding="utf-8",
        )
        assert _parse_workspaces(anchor) == []


def test_parse_workspaces_remote_first_residue_skipped() -> None:
    # Regression (verifier Round 1): a `- remote: origin` residue item must
    # not be misread as track='origin'; the valid endpoint still parses.
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor = Path(temp_dir) / "backend"
        frontend = Path(temp_dir) / "frontend"
        anchor.mkdir()
        frontend.mkdir()
        (anchor / ".devflow").mkdir(parents=True)
        (anchor / ".devflow" / "project.yaml").write_text(
            "workspaces:\n"
            '  - remote: "origin"\n'
            '  - track: "frontend"\n'
            '    git_root: "../frontend"\n',
            encoding="utf-8",
        )
        endpoints = _parse_workspaces(anchor)
        assert len(endpoints) == 1
        assert endpoints[0]["track"] == "frontend"


def test_parse_workspaces_indented_track_after_path() -> None:
    # H1 parity with orchestrator: legacy shape stays skipped, not parsed.
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor = Path(temp_dir) / "backend"
        frontend = Path(temp_dir) / "frontend"
        anchor.mkdir()
        frontend.mkdir()
        (anchor / ".devflow").mkdir(parents=True)
        (anchor / ".devflow" / "project.yaml").write_text(
            "workspaces:\n"
            '  - path: "../frontend"\n'
            '    track: "frontend"\n',
            encoding="utf-8",
        )
        assert _parse_workspaces(anchor) == []


def test_parse_workspaces_trailing_comment_in_path() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor = Path(temp_dir) / "backend"
        frontend = Path(temp_dir) / "frontend"
        anchor.mkdir()
        frontend.mkdir()
        (anchor / ".devflow").mkdir(parents=True)
        (anchor / ".devflow" / "project.yaml").write_text(
            "workspaces:\n"
            '  - track: "frontend"\n'
            '    path: "../frontend" # alias\n',
            encoding="utf-8",
        )
        endpoints = _parse_workspaces(anchor)
        assert len(endpoints) == 1
        assert endpoints[0]["git_root"] == str(frontend.resolve())


def test_parse_workspaces_comment_placeholder_root_skipped() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        anchor = Path(temp_dir) / "backend"
        (anchor / ".devflow").mkdir(parents=True)
        (anchor / ".devflow" / "project.yaml").write_text(
            "workspaces:\n"
            '  - track: "frontend"\n'
            '    git_root:   # to be filled in\n',
            encoding="utf-8",
        )
        assert _parse_workspaces(anchor) == []


def test_home_claude_memory_is_exempt() -> None:
    home = Path.home()
    assert is_user_agent_state(
            home / ".claude" / "projects" / "x" / "memory" / "MEMORY.md"
        )
    assert is_within_boundary(
            home / ".claude" / "projects" / "x" / "memory" / "MEMORY.md",
            Path("/some/project"),
        )


def test_memorant_root_from_env_is_exempt() -> None:
    with tempfile.TemporaryDirectory() as td:
        vault = Path(td) / "Memorant"
        with mock.patch.dict(os.environ, {"MEMORANT_ROOT": str(vault)}):
            assert is_user_agent_state(vault / "memories" / "x.md")


def test_memorant_default_root_when_env_unset() -> None:
    with mock.patch.dict(os.environ, {"MEMORANT_ROOT": ""}):
        assert is_user_agent_state(Path.home() / "Documents" / "Memorant" / "x.md")


def test_unrelated_outside_path_is_not_exempt() -> None:
    assert not (is_user_agent_state(Path("/tmp/scratch.txt")))
    assert not (is_user_agent_state(Path.home() / "Sites" / "other" / "x.go"))


def test_project_local_claude_is_inside_root_anyway() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "proj"
        (root / ".claude").mkdir(parents=True)
        assert is_within_boundary(root / ".claude" / "settings.local.json", root)

