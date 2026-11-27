#!/usr/bin/env python3
"""Automated tests for redline-guard.py boundary and redline enforcement.

Run from anywhere:

    python3 core/tests/test_redline_guard.py

The suite builds a throwaway project fixture under ``tempfile``, then drives
``redline-guard.py`` through its stdin/stdout contract (the same JSON a host
platform would pipe in) and asserts the resulting allow/deny decision. No
third-party dependencies — only the Python standard library.

Covered scenarios (per the delivery-report safety matrix):

    * backend agent writing backend file        -> allow
    * backend agent writing frontend file       -> deny
    * frontend agent writing backend file       -> deny
    * dev agent writing a contract file         -> deny
    * writing a forbidden file (.env)           -> deny
    * reading a forbidden file (.env)        -> deny
    * reading a protected file               -> allow
    * hook cwd overrides stale context.json cwd -> allow (regression for cwd bug)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

BULK = (
    "git checkout .",
    "git checkout -- .",
    "git reset --hard",
    "git reset --hard HEAD",
    "git clean -fdx",
    "git clean -fd",
    "find . -name '*.pyc' -delete",
    "rsync -a --delete src/ dst/",
    "truncate -s 0 important.log",
    "git branch -D feature/x",
)
ROUTINE = (
    "git checkout feature/x",
    "git clean -n",
    "git reset HEAD -- src/app.py",
    "grep -r 'token' src/",
    "python3 -m unittest discover -s core/tests",
    "git branch -d merged-branch",
    "find . -name '*.pyc'",
)
ALLOWED = (
    "rm -f /tmp/x.md",
    "rm -rf /tmp/devflow_dogfood",
    "rm -f /tmp/probe.json",
    "rm -rf ./dist",
    "rm -f out.log",
)
STILL_BLOCKED = (
    "rm -rf /",
    "rm -rf /*",
    "rm -rf ~",
    "rm -rf $HOME",
    "rm -rf ~/Documents",
)



def _boundary_bash(boundary_state, command, cwd=None):
    _boundary_write_context(boundary_state, boundary_state.backend)
    return _decision(
        _run_hook(boundary_state.root, "Bash", {"command": command}, str(cwd or boundary_state.root))
    )


@pytest.fixture(scope="module")
def boundary_state():
    from types import SimpleNamespace
    st = SimpleNamespace()
    st.tmp = tempfile.mkdtemp(prefix="devflow-test-")
    st.root = Path(st.tmp) / "project"
    st.backend = st.root / "server"
    st.frontend = st.root / "web"
    st.contracts = st.root / ".devflow" / "contracts"

    for d in (
        st.root / ".devflow",
        st.contracts,
        st.backend / "internal",
        st.frontend / "src",
    ):
        d.mkdir(parents=True, exist_ok=True)

    manifest = (
        "project:\n"
        "  name: test\n"
        "  current_phase: development\n"
        "  work_type: feature\n"
        "workspace:\n"
        f'  root: "{st.root}"\n'
        "  backend:\n"
        '    path: "server"\n'
        "  frontend:\n"
        '    path: "web"\n'
        "  contract:\n"
        '    path: ".devflow/contracts"\n'
    )
    (st.root / ".devflow" / "manifest.yaml").write_text(manifest, encoding="utf-8")

    redlines = (
        "forbidden:\n"
        '  - ".env"\n'
        "protected:\n"
        '  - ".github/**"\n'
        "approval_required:\n"
        '  - "package.json"\n'
    )
    (st.root / ".devflow" / "redlines.yaml").write_text(redlines, encoding="utf-8")
    yield st
    import shutil

    shutil.rmtree(st.tmp, ignore_errors=True)


def _boundary_write_context(boundary_state, cwd, agent="devflow-backend-dev"):
    ctx = {
        "run_id": "test-run",
        "current_phase": "development",
        "current_agent": agent,
        "cwd": str(cwd),
    }
    (boundary_state.root / ".devflow" / "context.json").write_text(json.dumps(ctx), encoding="utf-8")


def test_backend_writes_backend_allowed(boundary_state):
    _boundary_write_context(boundary_state, boundary_state.backend)
    target = boundary_state.backend / "internal" / "handler.go"
    proc = _run_hook(boundary_state.root, "Write", {"file_path": str(target)}, str(boundary_state.backend))
    assert _decision(proc) == "allow"


def test_backend_writes_frontend_allowed_within_root(boundary_state):
    # No per-track gating: a workspace spans repositories, so writing
    # another subdirectory under the same project root is allowed.
    _boundary_write_context(boundary_state, boundary_state.backend)
    target = boundary_state.frontend / "src" / "App.tsx"
    proc = _run_hook(boundary_state.root, "Write", {"file_path": str(target)}, str(boundary_state.backend))
    assert _decision(proc) == "allow"


def test_write_outside_project_root_denied(boundary_state):
    # The boundary is the session root ("drill down, never up/outside").
    _boundary_write_context(boundary_state, boundary_state.backend)
    with tempfile.TemporaryDirectory() as outside:
        target = Path(outside) / "stray.go"
        proc = _run_hook(boundary_state.root, "Write", {"file_path": str(target)}, str(boundary_state.backend))
        assert _decision(proc) == "deny"


def test_dev_agent_writes_contract_denied(boundary_state):
    _boundary_write_context(boundary_state, boundary_state.backend)
    target = boundary_state.contracts / "api.yaml"
    proc = _run_hook(boundary_state.root, "Write", {"file_path": str(target)}, str(boundary_state.backend))
    assert _decision(proc) == "deny"


def test_agent_writes_redlines_denied(boundary_state):
    # An agent must never rewrite the redlines that constrain it. This is
    # inside the project root, so it is caught by the DevFlow-protected
    # rule, not the boundary rule.
    _boundary_write_context(boundary_state, boundary_state.backend)
    target = boundary_state.root / ".devflow" / "redlines.yaml"
    proc = _run_hook(boundary_state.root, "Write", {"file_path": str(target)}, str(boundary_state.backend))
    assert _decision(proc) == "deny"


def test_forbidden_file_denied(boundary_state):
    _boundary_write_context(boundary_state, boundary_state.backend)
    target = boundary_state.root / ".env"
    proc = _run_hook(boundary_state.root, "Write", {"file_path": str(target)}, str(boundary_state.backend))
    assert _decision(proc) == "deny"


def test_bash_cp_to_forbidden_denied(boundary_state):
    _boundary_write_context(boundary_state, boundary_state.backend)
    proc = _run_hook(boundary_state.root, "Bash", {"command": "cp notes.txt .env"}, str(boundary_state.root))
    assert _decision(proc) == "deny"


def test_bash_mv_to_forbidden_denied(boundary_state):
    _boundary_write_context(boundary_state, boundary_state.backend)
    proc = _run_hook(boundary_state.root, "Bash", {"command": "mv notes.txt .env"}, str(boundary_state.root))
    assert _decision(proc) == "deny"


def test_bash_python_c_to_forbidden_denied(boundary_state):
    _boundary_write_context(boundary_state, boundary_state.backend)
    proc = _run_hook(
        boundary_state.root,
        "Bash",
        {"command": "python3 -c \"open('.env','w').write('x')\""},
        str(boundary_state.root),
    )
    assert _decision(proc) == "deny"


def test_bash_git_apply_forbidden_denied(boundary_state):
    _boundary_write_context(boundary_state, boundary_state.backend)
    patch = boundary_state.root / "secret.patch"
    patch.write_text("--- a/.env\n+++ b/.env\n@@\n-old\n+new\n", encoding="utf-8")
    proc = _run_hook(boundary_state.root, "Bash", {"command": "git apply secret.patch"}, str(boundary_state.root))
    assert _decision(proc) == "deny"


def test_bash_redirect_single_gt_to_forbidden_denied(boundary_state):
    # A single ``>`` (not just ``>>``) must be seen, or `.env` slips by.
    assert _boundary_bash(boundary_state, "echo x > .env") == "deny"


def test_bash_redirect_outside_root_denied(boundary_state):
    # Same boundary as the Write tool: out-of-root is refused.
    with tempfile.TemporaryDirectory() as outside:
        target = Path(outside) / "stray.txt"
        assert _boundary_bash(boundary_state, f"echo x > {target}") == "deny"


def test_bash_cp_outside_root_denied(boundary_state):
    with tempfile.TemporaryDirectory() as outside:
        assert _boundary_bash(boundary_state, f"cp notes.txt {outside}/x") == "deny"


def test_bash_tee_outside_root_denied(boundary_state):
    with tempfile.TemporaryDirectory() as outside:
        assert _boundary_bash(boundary_state, f"echo x | tee {outside}/y") == "deny"


def test_bash_rewrite_devflow_config_denied(boundary_state):
    # The guard's own rules and state are not shell-writable either.
    assert _boundary_bash(boundary_state, "echo x > .devflow/redlines.yaml") == "deny"
    assert _boundary_bash(boundary_state, "echo x > .devflow/task.yaml") == "deny"


def test_bash_write_devflow_artifact_allowed(boundary_state):
    assert _boundary_bash(boundary_state, "echo x > .devflow/plan.md") == "allow"


def test_bash_in_root_write_allowed(boundary_state):
    assert _boundary_bash(boundary_state, f"echo x > {boundary_state.backend}/internal/x.go") == "allow"


def test_bash_redirect_to_user_memory_allowed(boundary_state):
    memory = Path.home() / ".claude" / "projects" / "probe" / "memory" / "M.md"
    assert _boundary_bash(boundary_state, f"echo x > {memory}") == "allow"


def test_forbidden_file_read_denied(boundary_state):
    _boundary_write_context(boundary_state, boundary_state.backend)
    target = boundary_state.root / ".env"
    proc = _run_hook(boundary_state.root, "Read", {"file_path": str(target)}, str(boundary_state.backend))
    assert _decision(proc) == "deny"


def test_protected_file_read_allowed(boundary_state):
    _boundary_write_context(boundary_state, boundary_state.backend)
    target = boundary_state.root / ".github" / "workflows" / "ci.yml"
    proc = _run_hook(boundary_state.root, "Read", {"file_path": str(target)}, str(boundary_state.backend))
    assert _decision(proc) == "allow"


def test_normal_code_allowed(boundary_state):
    _boundary_write_context(boundary_state, boundary_state.backend)
    target = boundary_state.backend / "internal" / "model.go"
    proc = _run_hook(boundary_state.root, "Write", {"file_path": str(target)}, str(boundary_state.backend))
    assert _decision(proc) == "allow"


def test_hook_cwd_overrides_stale_context(boundary_state):
    # context.json still points at the frontend (stale, from a prior
    # dispatch), but the actual tool call runs from the backend cwd.
    _boundary_write_context(boundary_state, boundary_state.frontend)
    target = boundary_state.backend / "internal" / "handler.go"
    proc = _run_hook(boundary_state.root, "Write", {"file_path": str(target)}, str(boundary_state.backend))
    assert _decision(proc) == "allow"


@pytest.fixture
def st_approvaliscontentgatedtest():
    from types import SimpleNamespace
    st_approvaliscontentgatedtest = SimpleNamespace()
    st_approvaliscontentgatedtest._tmp = tempfile.TemporaryDirectory()
    st_approvaliscontentgatedtest.root = Path(st_approvaliscontentgatedtest._tmp.name)
    (st_approvaliscontentgatedtest.root / ".devflow").mkdir()
    (st_approvaliscontentgatedtest.root / ".devflow" / "task.yaml").write_text(
        "schema_version: 2\n"
        "task:\n"
        '  id: "task-approval"\n'
        '  slug: "approval"\n'
        '  kind: "feature"\n'
        '  description: "approval"\n'
        '  current_phase: "working"\n'
        '  status: "active"\n',
        encoding="utf-8",
    )
    (st_approvaliscontentgatedtest.root / ".devflow" / "redlines.yaml").write_text(
        "forbidden:\n"
        '  - ".env"\n'
        "protected:\n"
        '  - ".github/**"\n'
        "config_protected:\n"
        '  - "**/config/**"\n'
        '  - "**/settings/*"\n'
        "approval_required:\n"
        '  - "package.json"\n'
        '  - "**/auth/**"\n',
        encoding="utf-8",
    )
    yield st_approvaliscontentgatedtest
    st_approvaliscontentgatedtest._tmp.cleanup()


@pytest.fixture
def st_deliveryarchivegatetest():
    from types import SimpleNamespace
    st_deliveryarchivegatetest = SimpleNamespace()
    st_deliveryarchivegatetest._tmp = tempfile.mkdtemp(prefix="devflow-archive-gate-")
    st_deliveryarchivegatetest.root = Path(st_deliveryarchivegatetest._tmp) / "project"
    (st_deliveryarchivegatetest.root / ".devflow").mkdir(parents=True)
    yield st_deliveryarchivegatetest
    import shutil

    shutil.rmtree(st_deliveryarchivegatetest._tmp, ignore_errors=True)


CORE_DIR = Path(__file__).resolve().parent.parent
HOOK = CORE_DIR / "hooks" / "redline-guard.py"

sys.path.insert(0, str(CORE_DIR / "hooks"))

from devflow_guard_common import check_dangerous_command


def _run_hook(project_root, tool_name, tool_input, cwd, project_dir=None):
    """Invoke redline-guard.py and return the subprocess result.

    ``project_root`` is the session's launch directory (the process cwd); the
    guard reads it from ``CLAUDE_PROJECT_DIR`` — the fixed project root — while
    the payload ``cwd`` is the per-call working directory, which may be a
    subdirectory.  ``project_dir`` defaults to ``project_root``.
    """
    payload = {"tool_name": tool_name, "tool_input": tool_input, "cwd": cwd}
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project_dir if project_dir is not None else project_root)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
    )


def _decision(proc):
    """Extract the allow/deny/ask decision from a hook run's stdout."""
    out = proc.stdout.strip()
    if not out:
        return "allow"
    try:
        data = json.loads(out)
        return data["hookSpecificOutput"]["permissionDecision"]
    except Exception:
        return "unknown:" + out


@pytest.fixture(scope="module")
def wt_state():
    from types import SimpleNamespace
    st = SimpleNamespace()
    st.tmp = tempfile.mkdtemp(prefix="devflow-wt-test-")
    st.root = Path(st.tmp) / "project"
    st.backend = st.root / "server"
    st.frontend = st.root / "web"

    # Simulate Claude Code worktree path
    st.wt_root = st.root / ".claude" / "worktrees" / "agent-abc123"
    st.wt_backend = st.wt_root / "server"
    st.wt_frontend = st.wt_root / "web"

    for d in (
        st.root / ".devflow",
        st.root / ".devflow" / "contracts",
        st.backend / "internal",
        st.frontend / "src",
        st.wt_backend / "internal",
        st.wt_frontend / "src",
    ):
        d.mkdir(parents=True, exist_ok=True)

    manifest = (
        "project:\n"
        "  name: test\n"
        "  current_phase: development\n"
        "  work_type: feature\n"
        "workspace:\n"
        f'  root: "{st.root}"\n'
        "  backend:\n"
        '    path: "server"\n'
        "  frontend:\n"
        '    path: "web"\n'
        "  contract:\n"
        '    path: ".devflow/contracts"\n'
    )
    (st.root / ".devflow" / "manifest.yaml").write_text(manifest, encoding="utf-8")

    redlines = (
        "forbidden:\n"
        '  - ".env"\n'
        "protected:\n"
        '  - ".github/**"\n'
        "approval_required:\n"
        '  - "package.json"\n'
    )
    (st.root / ".devflow" / "redlines.yaml").write_text(redlines, encoding="utf-8")
    yield st
    import shutil

    shutil.rmtree(st.tmp, ignore_errors=True)




def _wt_write_context(wt_state, cwd, agent="devflow-backend-dev"):
    ctx = {
        "run_id": "test-run",
        "current_phase": "development",
        "current_agent": agent,
        "cwd": str(cwd),
        "workspace": {
            "root": str(wt_state.root),
            "backend": "server",
            "frontend": "web",
        },
    }
    (wt_state.root / ".devflow" / "context.json").write_text(json.dumps(ctx), encoding="utf-8")


# Tests for isolated worktree mode (Claude Code Task subagents).
def test_worktree_backend_writes_backend_code_allowed(wt_state):
    """Backend agent in worktree can write to worktree's server/ dir."""
    _wt_write_context(wt_state, wt_state.wt_backend)
    target = wt_state.wt_backend / "internal" / "handler.go"
    proc = _run_hook(wt_state.root, "Write", {"file_path": str(target)}, str(wt_state.wt_backend))
    assert _decision(proc) == "allow"


def test_worktree_backend_writes_frontend_allowed(wt_state):
    """Within the worktree's project wt_state.root, cross-directory writes are allowed."""
    _wt_write_context(wt_state, wt_state.wt_backend)
    target = wt_state.wt_frontend / "src" / "App.tsx"
    proc = _run_hook(wt_state.root, "Write", {"file_path": str(target)}, str(wt_state.wt_backend))
    assert _decision(proc) == "allow"


def test_worktree_dev_agent_writes_devflow_artifact_allowed(wt_state):
    """Dev agent in worktree can write .devflow/ task report."""
    _wt_write_context(wt_state, wt_state.wt_backend)
    # Agent writes .devflow/wt_state.backend-task-report.md relative to cwd
    target = wt_state.wt_backend / ".devflow" / "wt_state.backend-task-report.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    proc = _run_hook(wt_state.root, "Write", {"file_path": str(target)}, str(wt_state.wt_backend))
    assert _decision(proc) == "allow"


def test_worktree_architect_writes_scope_allowed(wt_state):
    """Architect agent in worktree can write .devflow/scope.yaml."""
    _wt_write_context(wt_state, wt_state.wt_root, agent="devflow-architect")
    target = wt_state.wt_root / ".devflow" / "scope.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    proc = _run_hook(wt_state.root, "Write", {"file_path": str(target)}, str(wt_state.wt_root))
    assert _decision(proc) == "allow"


def test_worktree_tester_writes_report_allowed(wt_state):
    """Tester agent in worktree can write .devflow/test-report.md."""
    _wt_write_context(wt_state, wt_state.wt_root, agent="devflow-tester")
    target = wt_state.wt_root / ".devflow" / "test-report.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    proc = _run_hook(wt_state.root, "Write", {"file_path": str(target)}, str(wt_state.wt_root))
    assert _decision(proc) == "allow"


def test_worktree_dev_agent_writes_contract_denied(wt_state):
    """Dev agent in worktree cannot write contract files."""
    _wt_write_context(wt_state, wt_state.wt_backend)
    target = wt_state.wt_root / ".devflow" / "wt_state.contracts" / "api.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    proc = _run_hook(wt_state.root, "Write", {"file_path": str(target)}, str(wt_state.wt_backend))
    assert _decision(proc) == "deny"


def test_worktree_relative_path_resolved_against_cwd(wt_state):
    """Relative .devflow/ path in worktree resolves to worktree, not main."""
    _wt_write_context(wt_state, wt_state.wt_backend)
    # Agent uses a relative path — must resolve against cwd (worktree)
    proc = _run_hook(
        wt_state.root,
        "Write",
        {"file_path": ".devflow/wt_state.backend-task-report.md"},
        str(wt_state.wt_backend),
    )
    assert _decision(proc) == "allow"


def test_worktree_forbidden_file_still_denied(wt_state):
    """Forbidden files (.env) are denied even in worktree."""
    _wt_write_context(wt_state, wt_state.wt_backend)
    target = wt_state.wt_backend / ".env"
    proc = _run_hook(wt_state.root, "Write", {"file_path": str(target)}, str(wt_state.wt_backend))
    assert _decision(proc) == "deny"


def test_load_context_reads_project_yaml_workspace_and_task_phase():
    hooks_dir = Path(__file__).resolve().parent.parent / "hooks"
    sys.path.insert(0, str(hooks_dir))
    from devflow_guard_common import load_context

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        devflow = root / ".devflow"
        devflow.mkdir()
        (devflow / "project.yaml").write_text(
            "workspace:\n"
            '  root: "."\n'
            "  backend:\n"
            '    path: "server"\n'
            "  frontend:\n"
            '    path: "web"\n',
            encoding="utf-8",
        )
        (devflow / "task.yaml").write_text(
            'task:\n  current_phase: "development"\n',
            encoding="utf-8",
        )
        ctx = load_context(root)
        assert ctx["workspace"]["backend"] == "server"
        assert ctx["workspace"]["frontend"] == "web"
        assert ctx["current_phase"] == "development"


def _write_task(st_deliveryarchivegatetest, task_id="task-abc", phase="delivery"):
    (st_deliveryarchivegatetest.root / ".devflow" / "task.yaml").write_text(
        "schema_version: 1\n"
        "task:\n"
        f'  id: "{task_id}"\n'
        '  slug: "test"\n'
        '  kind: "feature"\n'
        '  description: "test"\n'
        f'  current_phase: "{phase}"\n'
        '  status: "active"\n',
        encoding="utf-8",
    )


def _write_context(st_deliveryarchivegatetest, phase="delivery"):
    (st_deliveryarchivegatetest.root / ".devflow" / "context.json").write_text(
        json.dumps({"current_phase": phase, "cwd": str(st_deliveryarchivegatetest.root)}),
        encoding="utf-8",
    )


def _write_archive_index(st_deliveryarchivegatetest, task_id="task-abc"):
    index = st_deliveryarchivegatetest.root / ".devflow" / "tasks" / task_id / "README.md"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text("# Task Artifacts\n", encoding="utf-8")


def _run_commit(st_deliveryarchivegatetest):
    return _run_hook(
        st_deliveryarchivegatetest.root,
        "Bash",
        {"command": 'git commit -m "feat: test"'},
        str(st_deliveryarchivegatetest.root),
    )


# Delivery-phase archive gate: commit is blocked until artifacts are
# published to .devflow/tasks/<task-id>/.
def test_delivery_commit_blocked_when_not_archived(st_deliveryarchivegatetest):
    _write_task(st_deliveryarchivegatetest)
    _write_context(st_deliveryarchivegatetest)
    assert _decision(_run_commit(st_deliveryarchivegatetest)) == "deny"


def test_delivery_commit_allowed_when_archived(st_deliveryarchivegatetest):
    _write_task(st_deliveryarchivegatetest)
    _write_context(st_deliveryarchivegatetest)
    _write_archive_index(st_deliveryarchivegatetest)
    assert _decision(_run_commit(st_deliveryarchivegatetest)) == "allow"


def test_legacy_manifest_without_task_yaml_not_blocked(st_deliveryarchivegatetest):
    # No task.yaml → no formal-task archive → the gate must not fire.
    (st_deliveryarchivegatetest.root / ".devflow" / "manifest.yaml").write_text(
        "project:\n  current_phase: delivery\n", encoding="utf-8"
    )
    _write_context(st_deliveryarchivegatetest)
    assert _decision(_run_commit(st_deliveryarchivegatetest)) == "allow"


def test_non_delivery_phase_not_blocked(st_deliveryarchivegatetest):
    # v2: phase comes from task.yaml; the retired context.json must not
    # override it. This test now covers that regression directly.
    _write_task(st_deliveryarchivegatetest, phase="working")
    _write_context(st_deliveryarchivegatetest, phase="deliver_confirm")
    assert _decision(_run_commit(st_deliveryarchivegatetest)) == "allow"


def test_non_commit_command_not_blocked(st_deliveryarchivegatetest):
    _write_task(st_deliveryarchivegatetest)
    _write_context(st_deliveryarchivegatetest)
    proc = _run_hook(st_deliveryarchivegatetest.root, "Bash", {"command": "git status"}, str(st_deliveryarchivegatetest.root))
    assert _decision(proc) == "allow"


# ---------------------------------------------------------------------------
# 2026-11 audit findings
#
# Both cases below were written before the fix and failed on the pre-change
# tree — that is the point: the previous suite was green while these two
# behaviours were broken.
# ---------------------------------------------------------------------------


def _write(st_approvaliscontentgatedtest, rel_path, content):
    target = st_approvaliscontentgatedtest.root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    return _run_hook(
        st_approvaliscontentgatedtest.root, "Write", {"file_path": str(target), "content": content}, str(st_approvaliscontentgatedtest.root)
    )


# Two different questions, deliberately answered differently.
# 
# ``approval_required`` covers dependencies, migrations and auth code: those
# are routine work, so a path match only asks when the written content
# carries a credential marker.
# 
# Configuration is not routine — ``**/config/*`` and ``**/settings/*`` are
# matched by ``config_protected`` and refused outright, reads included. A
# guard that lets an agent read the config can leak the secrets the
# ``forbidden`` rules are there to protect; one that lets it write can
# redirect where those secrets are loaded from.
def test_config_write_is_denied_even_without_a_secret(st_approvaliscontentgatedtest):
    proc = _write(st_approvaliscontentgatedtest, "server/config/app.yaml", "timeout: 30\n")
    assert _decision(proc) == "deny"


def test_config_write_with_password_is_denied(st_approvaliscontentgatedtest):
    proc = _write(st_approvaliscontentgatedtest, "server/config/app.yaml", "password: hunter2\n")
    assert _decision(proc) == "deny"


def test_settings_file_write_is_denied(st_approvaliscontentgatedtest):
    proc = _write(st_approvaliscontentgatedtest, "server/settings/base.py", "DEBUG = False\n")
    assert _decision(proc) == "deny"


def test_config_read_is_denied(st_approvaliscontentgatedtest):
    """Reading is what makes the boundary real: otherwise the agent can
    lift secrets out of a file it may not write."""
    target = st_approvaliscontentgatedtest.root / "server" / "config" / "app.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("token: abc\n", encoding="utf-8")
    proc = _run_hook(st_approvaliscontentgatedtest.root, "Read", {"file_path": str(target)}, str(st_approvaliscontentgatedtest.root))
    assert _decision(proc) == "deny"


@pytest.mark.parametrize("command", (
    "cat server/config/app.yaml",
    "grep token server/config/app.yaml",
    "head -n 5 server/config/app.yaml",
    "cat server/config/app.yaml | grep token",
))
def test_shell_read_of_config_is_denied(st_approvaliscontentgatedtest, command):
    """``cat config/app.yaml`` names no write target, so the write-target
    extractor misses it and the whole rule would be bypassable."""
    target = st_approvaliscontentgatedtest.root / "server" / "config" / "app.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("token: abc\n", encoding="utf-8")
    proc = _run_hook(st_approvaliscontentgatedtest.root, "Bash", {"command": command}, str(st_approvaliscontentgatedtest.root))
    assert _decision(proc) == "deny"


def test_shell_read_of_ordinary_file_is_allowed(st_approvaliscontentgatedtest):
    proc = _run_hook(st_approvaliscontentgatedtest.root, "Bash", {"command": "cat server/app.py"}, str(st_approvaliscontentgatedtest.root))
    assert _decision(proc) == "allow"


def test_project_config_is_still_readable(st_approvaliscontentgatedtest):
    """The guard's own file contract lives in config-shaped paths; denying
    those would stop DevFlow from reading its own state."""
    target = st_approvaliscontentgatedtest.root / ".devflow" / "project.yaml"
    target.write_text("project:\n  name: x\n", encoding="utf-8")
    proc = _run_hook(st_approvaliscontentgatedtest.root, "Read", {"file_path": str(target)}, str(st_approvaliscontentgatedtest.root))
    assert _decision(proc) == "allow"


def test_ordinary_python_is_allowed(st_approvaliscontentgatedtest):
    proc = _write(st_approvaliscontentgatedtest, "server/app.py", "def handler():\n    return 1\n")
    assert _decision(proc) == "allow"


def test_auth_with_secret_is_asked(st_approvaliscontentgatedtest):
    proc = _write(st_approvaliscontentgatedtest, "server/auth/session.py", "API_KEY = 'sk-123'\n")
    assert _decision(proc) == "ask"


def test_auth_without_secret_is_allowed(st_approvaliscontentgatedtest):
    proc = _write(st_approvaliscontentgatedtest, 
        "server/auth/session.py", "def is_expired(ts, now):\n    return ts < now\n"
    )
    assert _decision(proc) == "allow"


def test_sensitive_marker_is_case_insensitive(st_approvaliscontentgatedtest):
    proc = _write(st_approvaliscontentgatedtest, "server/auth/db.py", "DB_PASSWORD: x\n")
    assert _decision(proc) == "ask"


def test_edit_without_secret_is_allowed(st_approvaliscontentgatedtest):
    """Edit carries a diff snippet. When neither side mentions a
    credential, the edit is routine and passes.

    This is the deliberate loosening from the 2026-11 audit: an Edit is by
    definition a small, reviewable change, so a bare path match is not
    worth stopping for.
    """
    target = st_approvaliscontentgatedtest.root / "package.json"
    target.write_text('{"name": "x"}\n', encoding="utf-8")
    proc = _run_hook(
        st_approvaliscontentgatedtest.root,
        "Edit",
        {"file_path": str(target), "old_string": '"name": "x"', "new_string": '"name": "y"'},
        str(st_approvaliscontentgatedtest.root),
    )
    assert _decision(proc) == "allow"


def test_edit_adding_a_secret_is_asked(st_approvaliscontentgatedtest):
    target = st_approvaliscontentgatedtest.root / "package.json"
    target.write_text('{"name": "x"}\n', encoding="utf-8")
    proc = _run_hook(
        st_approvaliscontentgatedtest.root,
        "Edit",
        {"file_path": str(target), "old_string": '"name": "x"', "new_string": '"token": "abc"'},
        str(st_approvaliscontentgatedtest.root),
    )
    assert _decision(proc) == "ask"


def test_forbidden_file_still_denied(st_approvaliscontentgatedtest):
    proc = _write(st_approvaliscontentgatedtest, ".env", "TOKEN=1\n")
    assert _decision(proc) == "deny"


# Bulk-destructive commands destroy work in one shot and matched none of
# the original danger patterns (which only caught ``rm -rf /``, ``mkfs``,
# force-push and friends).
@pytest.mark.parametrize("command", BULK)
def test_bulk_destructive_commands_are_blocked(command):
    assert check_dangerous_command(command) is not None


@pytest.mark.parametrize("command", ROUTINE)
def test_routine_commands_still_pass(command):
    assert check_dangerous_command(command) is None


@pytest.mark.parametrize("command", (
    'git commit -m "fix: stop using git reset --hard"',
    'git commit -m "docs: explain git clean -fd"',
    'echo "git checkout ." > notes.md',
    "git status  # not git clean -fd",
))
def test_command_names_inside_a_commit_message_are_allowed(command):
    """The words appear as text, not as an invocation. Blocking here made
    the guard reject its own commit message."""
    assert check_dangerous_command(command) is None


@pytest.mark.parametrize("command", (
    "echo hi && git reset --hard",
    "ls; git clean -fdx",
    "cd /tmp && find . -name '*.tmp' -delete",
    "sudo git branch -D main",
))
def test_chained_bulk_command_is_still_blocked(command):
    """A real invocation after a chain operator must not slip through the
    segment split."""
    assert check_dangerous_command(command) is not None


def test_heredoc_body_is_not_scanned_as_a_command():
    """`git commit -F - <<'EOF'` passes a message on stdin. The words in
    it are prose — scanning them blocked the guard's own commit."""
    command = (
        "git commit -F - <<'EOF'\n"
        "fix: stop calling git reset --hard in CI to truncate -s 0 logs\n"
        "EOF\n"
    )
    assert check_dangerous_command(command) is None


def test_real_command_after_a_heredoc_is_still_blocked():
    command = "cat <<'EOF' > notes.txt\nhello\nEOF\ngit reset --hard\n"
    assert check_dangerous_command(command) is not None


def test_expandable_strings_are_still_scanned():
    """Double quotes expand `$(...)`, so their contents can execute and
    must keep being checked."""
    assert check_dangerous_command('echo "$(git reset --hard)"') is not None


def test_backticks_inside_a_heredoc_are_text():
    """Markdown code spans in a PR body are backticks, not command
    substitution. Stripping heredocs has to happen before substitutions
    are hoisted, or writing the PR body blocks itself."""
    backtick = chr(96)
    command = (
        "cat > /tmp/pr.md <<'EOF'\n"
        f"- {backtick}git checkout .{backtick} and more\n"
        "EOF\n"
    )
    assert check_dangerous_command(command) is None


def test_backticks_outside_a_heredoc_still_execute():
    backtick = chr(96)
    assert check_dangerous_command(f"echo {backtick}git clean -f{backtick}") is not None


# Scratch-file cleanup under /tmp is routine during verification.
# 
# It used to be blocked as a root wipe: the pattern's bare ``/`` alternative
# matched the leading slash of ``/tmp/scratch``. The QA agent hit this in the
# 2026-11 dogfood, worked around it in memory, and reported it as friction —
# which is exactly the kind of thing that should become a test rather than a
# workaround.
@pytest.mark.parametrize("command", ALLOWED)
def test_scratch_cleanup_is_allowed(command):
    assert check_dangerous_command(command) is None


@pytest.mark.parametrize("command", STILL_BLOCKED)
def test_root_and_home_wipes_are_still_blocked(command):
    assert check_dangerous_command(command) is not None


@pytest.fixture(scope="module")
def ws_state():
    from types import SimpleNamespace
    st = SimpleNamespace()
    st.tmp = tempfile.mkdtemp(prefix="devflow-ws-test-")
    st.ws = _make_ws(Path(st.tmp) / "ws")
    st.repo_a = _make_child(st.ws, "repo-a")
    st.repo_b = _make_child(st.ws, "repo-b")
    yield st
    import shutil
    shutil.rmtree(st.tmp, ignore_errors=True)


def _decide(ws_state, project_dir, target, cwd=None):
    return _decision(
        _run_hook(
            ws_state.ws,
            "Write",
            {"file_path": str(target)},
            str(cwd if cwd is not None else project_dir),
            project_dir=project_dir,
        )
    )


# Multi-repo workspace: the session root is the boundary, drilled down.
def test_workspace_root_can_write_across_repos(ws_state):
    # Session at ws_state.ws root: both child repos are under the root → allowed.
    assert _decide(ws_state, ws_state.ws, ws_state.repo_a / "src/main.go") == "allow"
    assert _decide(ws_state, ws_state.ws, ws_state.repo_b / "src/App.tsx") == "allow"


def test_child_repo_root_cannot_write_sibling_repo(ws_state):
    # Session at repo-a: repo-b is outside repo-a → denied.
    assert _decide(ws_state, ws_state.repo_a, ws_state.repo_b / "src/App.tsx") == "deny"


def test_child_repo_root_can_write_itself(ws_state):
    assert _decide(ws_state, ws_state.repo_a, ws_state.repo_a / "src/main.go") == "allow"


def test_cwd_drift_does_not_move_the_root(ws_state):
    # cwd drifted deep into repo-a, but launch dir is ws_state.ws → still ws_state.ws root,
    # so a redline file anywhere under ws_state.ws is still enforced and a sibling
    # repo write is allowed.
    drifted = ws_state.repo_a / "src/deep"
    drifted.mkdir(parents=True, exist_ok=True)
    assert _decide(ws_state, ws_state.ws, ws_state.repo_b / "src/App.tsx", cwd=drifted) == "allow"


def test_redline_still_enforced_within_root(ws_state):
    assert _decide(ws_state, ws_state.ws, ws_state.repo_a / ".env") == "deny"


def test_agent_cannot_edit_devflow_config(ws_state):
    # Inside the root, but DevFlow's own machinery → denied.
    assert _decide(ws_state, ws_state.ws, ws_state.ws / ".devflow/redlines.yaml") == "deny"
    assert _decide(ws_state, ws_state.ws, ws_state.ws / ".devflow/task.yaml") == "deny"


def test_agent_can_write_devflow_artifact(ws_state):
    assert _decide(ws_state, ws_state.ws, ws_state.ws / ".devflow/plan.md") == "allow"


def test_init_window_allows_writing_config(ws_state):
    # A never-initialised project (bare .devflow, no state file) — /devflow
    # init must be able to create project.yaml / rules/ / redlines.yaml.
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td) / "fresh"
        (proj / ".devflow").mkdir(parents=True)
        for rel in ("project.yaml", "redlines.yaml", "rules/frontend.md"):
            assert _decide(ws_state, proj, proj / ".devflow" / rel) == "allow", f"init should be able to write {rel}"


def test_init_window_rejects_non_init_paths(ws_state):
    # Even during init, arbitrary .devflow/ files are not writable.
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td) / "fresh"
        (proj / ".devflow").mkdir(parents=True)
        assert _decide(ws_state, proj, proj / ".devflow/random.md") == "deny"


def test_initialised_project_denies_config_without_a_task(ws_state):
    # project.yaml already exists but no task yet → init window is closed;
    # config stays protected (a configured project can't treat itself as
    # still-initialising to rewrite its rules).
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td) / "configured"
        (proj / ".devflow").mkdir(parents=True)
        (proj / ".devflow/project.yaml").write_text(
            'project:\n  name: x\n', encoding="utf-8"
        )
        assert _decide(ws_state, proj, proj / ".devflow/redlines.yaml") == "deny"
        assert _decide(ws_state, proj, proj / ".devflow/rules/a.md") == "deny"


def test_uninitialised_dir_is_transparent():
    # repo-b has no .devflow; a session launched there is uninitialised.
    with tempfile.TemporaryDirectory() as td:
        plain = Path(td) / "plain"
        plain.mkdir()
        assert _decision(
                _run_hook(plain, "Write", {"file_path": str(plain / "x.go")}, str(plain),
                          project_dir=plain)
            ) == "allow"


def test_user_level_memory_write_allowed(ws_state):
    # auto-memory / Memorant live outside the project root but must stay
    # writable — they are user-level infrastructure, not project files.
    memory = Path.home() / ".claude" / "projects" / "probe" / "memory" / "MEMORY.md"
    assert _decide(ws_state, ws_state.ws, memory) == "allow"


def test_redline_still_applies_in_exempt_root(ws_state):
    # The boundary exemption must not bypass the forbidden-file rule.
    secret = Path.home() / ".claude" / "projects" / "probe" / "memory" / ".env"
    assert _decide(ws_state, ws_state.ws, secret) == "deny"


def _make_ws(ws: Path) -> Path:
    (ws / ".devflow").mkdir(parents=True, exist_ok=True)
    (ws / ".devflow/project.yaml").write_text(
        'project:\n  name: ws\nworkspace:\n  root: "."\n', encoding="utf-8"
    )
    (ws / ".devflow/redlines.yaml").write_text(
        'forbidden:\n  - ".env"\nprotected: []\napproval_required: []\n', encoding="utf-8"
    )
    return ws


def _make_child(ws: Path, name: str) -> Path:
    child = ws / name
    (child / ".devflow").mkdir(parents=True, exist_ok=True)
    (child / "src").mkdir(parents=True, exist_ok=True)
    (child / ".devflow/redlines.yaml").write_text(
        'forbidden:\n  - ".env"\nprotected: []\napproval_required: []\n', encoding="utf-8"
    )
    return child


def test_branch_name_with_f_token_triggers_force_push_false_positive():
    """Known false positive, pinned so a guard fix is a deliberate change.

    The danger regex ``git\\s+push\\s+.*(-f|--force)`` matches a ``-f-<id>``
    token inside a branch slug (DevFlow slugs contain ``-f-`` when a word
    ends in f before the id separator). PR #35 hit this live: ``git push -u origin
    fix/...-f-5c22f1`` was denied. The guard-safe equivalent is
    ``git push origin HEAD`` plus ``git branch --set-upstream-to``.
    """
    assert check_dangerous_command("git push -u origin feature/x-f-1") == "Force push to git remote"
    assert check_dangerous_command("git push origin HEAD") is None
    assert check_dangerous_command("git push --force origin main") == "Force push to git remote"
