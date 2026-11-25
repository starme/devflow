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
import unittest
from pathlib import Path

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


class RedlineGuardBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="devflow-test-")
        cls.root = Path(cls.tmp) / "project"
        cls.backend = cls.root / "server"
        cls.frontend = cls.root / "web"
        cls.contracts = cls.root / ".devflow" / "contracts"

        for d in (
            cls.root / ".devflow",
            cls.contracts,
            cls.backend / "internal",
            cls.frontend / "src",
        ):
            d.mkdir(parents=True, exist_ok=True)

        manifest = (
            "project:\n"
            "  name: test\n"
            "  current_phase: development\n"
            "  work_type: feature\n"
            "workspace:\n"
            f'  root: "{cls.root}"\n'
            "  backend:\n"
            '    path: "server"\n'
            "  frontend:\n"
            '    path: "web"\n'
            "  contract:\n"
            '    path: ".devflow/contracts"\n'
        )
        (cls.root / ".devflow" / "manifest.yaml").write_text(manifest, encoding="utf-8")

        redlines = (
            "forbidden:\n"
            '  - ".env"\n'
            "protected:\n"
            '  - ".github/**"\n'
            "approval_required:\n"
            '  - "package.json"\n'
        )
        (cls.root / ".devflow" / "redlines.yaml").write_text(redlines, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        import shutil

        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _write_context(self, cwd, agent="devflow-backend-dev"):
        ctx = {
            "run_id": "test-run",
            "current_phase": "development",
            "current_agent": agent,
            "cwd": str(cwd),
        }
        (self.root / ".devflow" / "context.json").write_text(json.dumps(ctx), encoding="utf-8")

    # --- boundary matrix -------------------------------------------------

    def test_backend_writes_backend_allowed(self):
        self._write_context(self.backend)
        target = self.backend / "internal" / "handler.go"
        proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.backend))
        self.assertEqual(_decision(proc), "allow")

    def test_backend_writes_frontend_allowed_within_root(self):
        # No per-track gating: a workspace spans repositories, so writing
        # another subdirectory under the same project root is allowed.
        self._write_context(self.backend)
        target = self.frontend / "src" / "App.tsx"
        proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.backend))
        self.assertEqual(_decision(proc), "allow")

    def test_write_outside_project_root_denied(self):
        # The boundary is the session root ("drill down, never up/outside").
        self._write_context(self.backend)
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "stray.go"
            proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.backend))
            self.assertEqual(_decision(proc), "deny")

    def test_dev_agent_writes_contract_denied(self):
        self._write_context(self.backend)
        target = self.contracts / "api.yaml"
        proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.backend))
        self.assertEqual(_decision(proc), "deny")

    def test_agent_writes_redlines_denied(self):
        # An agent must never rewrite the redlines that constrain it. This is
        # inside the project root, so it is caught by the DevFlow-protected
        # rule, not the boundary rule.
        self._write_context(self.backend)
        target = self.root / ".devflow" / "redlines.yaml"
        proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.backend))
        self.assertEqual(_decision(proc), "deny")

    # --- redline regression ---------------------------------------------

    def test_forbidden_file_denied(self):
        self._write_context(self.backend)
        target = self.root / ".env"
        proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.backend))
        self.assertEqual(_decision(proc), "deny")

    def test_bash_cp_to_forbidden_denied(self):
        self._write_context(self.backend)
        proc = _run_hook(self.root, "Bash", {"command": "cp notes.txt .env"}, str(self.root))
        self.assertEqual(_decision(proc), "deny")

    def test_bash_mv_to_forbidden_denied(self):
        self._write_context(self.backend)
        proc = _run_hook(self.root, "Bash", {"command": "mv notes.txt .env"}, str(self.root))
        self.assertEqual(_decision(proc), "deny")

    def test_bash_python_c_to_forbidden_denied(self):
        self._write_context(self.backend)
        proc = _run_hook(
            self.root,
            "Bash",
            {"command": "python3 -c \"open('.env','w').write('x')\""},
            str(self.root),
        )
        self.assertEqual(_decision(proc), "deny")

    def test_bash_git_apply_forbidden_denied(self):
        self._write_context(self.backend)
        patch = self.root / "secret.patch"
        patch.write_text("--- a/.env\n+++ b/.env\n@@\n-old\n+new\n", encoding="utf-8")
        proc = _run_hook(self.root, "Bash", {"command": "git apply secret.patch"}, str(self.root))
        self.assertEqual(_decision(proc), "deny")

    # --- Bash channel must match the file-tool boundary ------------------

    def _bash(self, command, cwd=None):
        self._write_context(self.backend)
        return _decision(
            _run_hook(self.root, "Bash", {"command": command}, str(cwd or self.root))
        )

    def test_bash_redirect_single_gt_to_forbidden_denied(self):
        # A single ``>`` (not just ``>>``) must be seen, or `.env` slips by.
        self.assertEqual(self._bash("echo x > .env"), "deny")

    def test_bash_redirect_outside_root_denied(self):
        # Same boundary as the Write tool: out-of-root is refused.
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "stray.txt"
            self.assertEqual(self._bash(f"echo x > {target}"), "deny")

    def test_bash_cp_outside_root_denied(self):
        with tempfile.TemporaryDirectory() as outside:
            self.assertEqual(self._bash(f"cp notes.txt {outside}/x"), "deny")

    def test_bash_tee_outside_root_denied(self):
        with tempfile.TemporaryDirectory() as outside:
            self.assertEqual(self._bash(f"echo x | tee {outside}/y"), "deny")

    def test_bash_rewrite_devflow_config_denied(self):
        # The guard's own rules and state are not shell-writable either.
        self.assertEqual(self._bash("echo x > .devflow/redlines.yaml"), "deny")
        self.assertEqual(self._bash("echo x > .devflow/task.yaml"), "deny")

    def test_bash_write_devflow_artifact_allowed(self):
        self.assertEqual(self._bash("echo x > .devflow/plan.md"), "allow")

    def test_bash_in_root_write_allowed(self):
        self.assertEqual(self._bash(f"echo x > {self.backend}/internal/x.go"), "allow")

    def test_bash_redirect_to_user_memory_allowed(self):
        memory = Path.home() / ".claude" / "projects" / "probe" / "memory" / "M.md"
        self.assertEqual(self._bash(f"echo x > {memory}"), "allow")

    def test_forbidden_file_read_denied(self):
        self._write_context(self.backend)
        target = self.root / ".env"
        proc = _run_hook(self.root, "Read", {"file_path": str(target)}, str(self.backend))
        self.assertEqual(_decision(proc), "deny")

    def test_protected_file_read_allowed(self):
        self._write_context(self.backend)
        target = self.root / ".github" / "workflows" / "ci.yml"
        proc = _run_hook(self.root, "Read", {"file_path": str(target)}, str(self.backend))
        self.assertEqual(_decision(proc), "allow")

    def test_normal_code_allowed(self):
        self._write_context(self.backend)
        target = self.backend / "internal" / "model.go"
        proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.backend))
        self.assertEqual(_decision(proc), "allow")

    # --- cwd priority regression ----------------------------------------

    def test_hook_cwd_overrides_stale_context(self):
        # context.json still points at the frontend (stale, from a prior
        # dispatch), but the actual tool call runs from the backend cwd.
        self._write_context(self.frontend)
        target = self.backend / "internal" / "handler.go"
        proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.backend))
        self.assertEqual(_decision(proc), "allow")


class WorktreeGuardTest(unittest.TestCase):
    """Tests for isolated worktree mode (Claude Code Task subagents)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="devflow-wt-test-")
        cls.root = Path(cls.tmp) / "project"
        cls.backend = cls.root / "server"
        cls.frontend = cls.root / "web"

        # Simulate Claude Code worktree path
        cls.wt_root = cls.root / ".claude" / "worktrees" / "agent-abc123"
        cls.wt_backend = cls.wt_root / "server"
        cls.wt_frontend = cls.wt_root / "web"

        for d in (
            cls.root / ".devflow",
            cls.root / ".devflow" / "contracts",
            cls.backend / "internal",
            cls.frontend / "src",
            cls.wt_backend / "internal",
            cls.wt_frontend / "src",
        ):
            d.mkdir(parents=True, exist_ok=True)

        manifest = (
            "project:\n"
            "  name: test\n"
            "  current_phase: development\n"
            "  work_type: feature\n"
            "workspace:\n"
            f'  root: "{cls.root}"\n'
            "  backend:\n"
            '    path: "server"\n'
            "  frontend:\n"
            '    path: "web"\n'
            "  contract:\n"
            '    path: ".devflow/contracts"\n'
        )
        (cls.root / ".devflow" / "manifest.yaml").write_text(manifest, encoding="utf-8")

        redlines = (
            "forbidden:\n"
            '  - ".env"\n'
            "protected:\n"
            '  - ".github/**"\n'
            "approval_required:\n"
            '  - "package.json"\n'
        )
        (cls.root / ".devflow" / "redlines.yaml").write_text(redlines, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        import shutil

        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _write_context(self, cwd, agent="devflow-backend-dev"):
        ctx = {
            "run_id": "test-run",
            "current_phase": "development",
            "current_agent": agent,
            "cwd": str(cwd),
            "workspace": {
                "root": str(self.root),
                "backend": "server",
                "frontend": "web",
            },
        }
        (self.root / ".devflow" / "context.json").write_text(json.dumps(ctx), encoding="utf-8")

    def test_worktree_backend_writes_backend_code_allowed(self):
        """Backend agent in worktree can write to worktree's server/ dir."""
        self._write_context(self.wt_backend)
        target = self.wt_backend / "internal" / "handler.go"
        proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.wt_backend))
        self.assertEqual(_decision(proc), "allow")

    def test_worktree_backend_writes_frontend_allowed(self):
        """Within the worktree's project root, cross-directory writes are allowed."""
        self._write_context(self.wt_backend)
        target = self.wt_frontend / "src" / "App.tsx"
        proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.wt_backend))
        self.assertEqual(_decision(proc), "allow")

    def test_worktree_dev_agent_writes_devflow_artifact_allowed(self):
        """Dev agent in worktree can write .devflow/ task report."""
        self._write_context(self.wt_backend)
        # Agent writes .devflow/backend-task-report.md relative to cwd
        target = self.wt_backend / ".devflow" / "backend-task-report.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.wt_backend))
        self.assertEqual(_decision(proc), "allow")

    def test_worktree_architect_writes_scope_allowed(self):
        """Architect agent in worktree can write .devflow/scope.yaml."""
        self._write_context(self.wt_root, agent="devflow-architect")
        target = self.wt_root / ".devflow" / "scope.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.wt_root))
        self.assertEqual(_decision(proc), "allow")

    def test_worktree_tester_writes_report_allowed(self):
        """Tester agent in worktree can write .devflow/test-report.md."""
        self._write_context(self.wt_root, agent="devflow-tester")
        target = self.wt_root / ".devflow" / "test-report.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.wt_root))
        self.assertEqual(_decision(proc), "allow")

    def test_worktree_dev_agent_writes_contract_denied(self):
        """Dev agent in worktree cannot write contract files."""
        self._write_context(self.wt_backend)
        target = self.wt_root / ".devflow" / "contracts" / "api.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.wt_backend))
        self.assertEqual(_decision(proc), "deny")

    def test_worktree_relative_path_resolved_against_cwd(self):
        """Relative .devflow/ path in worktree resolves to worktree, not main."""
        self._write_context(self.wt_backend)
        # Agent uses a relative path — must resolve against cwd (worktree)
        proc = _run_hook(
            self.root,
            "Write",
            {"file_path": ".devflow/backend-task-report.md"},
            str(self.wt_backend),
        )
        self.assertEqual(_decision(proc), "allow")

    def test_worktree_forbidden_file_still_denied(self):
        """Forbidden files (.env) are denied even in worktree."""
        self._write_context(self.wt_backend)
        target = self.wt_backend / ".env"
        proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.wt_backend))
        self.assertEqual(_decision(proc), "deny")


class ProjectYamlContextTest(unittest.TestCase):
    def test_load_context_reads_project_yaml_workspace_and_task_phase(self):
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
            self.assertEqual(ctx["workspace"]["backend"], "server")
            self.assertEqual(ctx["workspace"]["frontend"], "web")
            self.assertEqual(ctx["current_phase"], "development")


class DeliveryArchiveGateTest(unittest.TestCase):
    """Delivery-phase archive gate: commit is blocked until artifacts are
    published to .devflow/tasks/<task-id>/."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="devflow-archive-gate-")
        self.root = Path(self._tmp) / "project"
        (self.root / ".devflow").mkdir(parents=True)

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_task(self, task_id="task-abc", phase="delivery"):
        (self.root / ".devflow" / "task.yaml").write_text(
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

    def _write_context(self, phase="delivery"):
        (self.root / ".devflow" / "context.json").write_text(
            json.dumps({"current_phase": phase, "cwd": str(self.root)}),
            encoding="utf-8",
        )

    def _write_archive_index(self, task_id="task-abc"):
        index = self.root / ".devflow" / "tasks" / task_id / "README.md"
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text("# Task Artifacts\n", encoding="utf-8")

    def _run_commit(self):
        return _run_hook(
            self.root,
            "Bash",
            {"command": 'git commit -m "feat: test"'},
            str(self.root),
        )

    def test_delivery_commit_blocked_when_not_archived(self):
        self._write_task()
        self._write_context()
        self.assertEqual(_decision(self._run_commit()), "deny")

    def test_delivery_commit_allowed_when_archived(self):
        self._write_task()
        self._write_context()
        self._write_archive_index()
        self.assertEqual(_decision(self._run_commit()), "allow")

    def test_legacy_manifest_without_task_yaml_not_blocked(self):
        # No task.yaml → no formal-task archive → the gate must not fire.
        (self.root / ".devflow" / "manifest.yaml").write_text(
            "project:\n  current_phase: delivery\n", encoding="utf-8"
        )
        self._write_context()
        self.assertEqual(_decision(self._run_commit()), "allow")

    def test_non_delivery_phase_not_blocked(self):
        # v2: phase comes from task.yaml; the retired context.json must not
        # override it. This test now covers that regression directly.
        self._write_task(phase="working")
        self._write_context(phase="deliver_confirm")
        self.assertEqual(_decision(self._run_commit()), "allow")

    def test_non_commit_command_not_blocked(self):
        self._write_task()
        self._write_context()
        proc = _run_hook(self.root, "Bash", {"command": "git status"}, str(self.root))
        self.assertEqual(_decision(proc), "allow")


# ---------------------------------------------------------------------------
# 2026-11 audit findings
#
# Both cases below were written before the fix and failed on the pre-change
# tree — that is the point: the previous suite was green while these two
# behaviours were broken.
# ---------------------------------------------------------------------------


class _ApprovalFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / ".devflow").mkdir()
        (self.root / ".devflow" / "task.yaml").write_text(
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
        (self.root / ".devflow" / "redlines.yaml").write_text(
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

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, rel_path, content):
        target = self.root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        return _run_hook(
            self.root, "Write", {"file_path": str(target), "content": content}, str(self.root)
        )


class ApprovalIsContentGatedTest(_ApprovalFixture):
    """Two different questions, deliberately answered differently.

    ``approval_required`` covers dependencies, migrations and auth code: those
    are routine work, so a path match only asks when the written content
    carries a credential marker.

    Configuration is not routine — ``**/config/*`` and ``**/settings/*`` are
    matched by ``config_protected`` and refused outright, reads included. A
    guard that lets an agent read the config can leak the secrets the
    ``forbidden`` rules are there to protect; one that lets it write can
    redirect where those secrets are loaded from.
    """

    def test_config_write_is_denied_even_without_a_secret(self):
        proc = self._write("server/config/app.yaml", "timeout: 30\n")
        self.assertEqual(_decision(proc), "deny")

    def test_config_write_with_password_is_denied(self):
        proc = self._write("server/config/app.yaml", "password: hunter2\n")
        self.assertEqual(_decision(proc), "deny")

    def test_settings_file_write_is_denied(self):
        proc = self._write("server/settings/base.py", "DEBUG = False\n")
        self.assertEqual(_decision(proc), "deny")

    def test_config_read_is_denied(self):
        """Reading is what makes the boundary real: otherwise the agent can
        lift secrets out of a file it may not write."""
        target = self.root / "server" / "config" / "app.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("token: abc\n", encoding="utf-8")
        proc = _run_hook(self.root, "Read", {"file_path": str(target)}, str(self.root))
        self.assertEqual(_decision(proc), "deny")

    def test_shell_read_of_config_is_denied(self):
        """``cat config/app.yaml`` names no write target, so the write-target
        extractor misses it and the whole rule would be bypassable."""
        target = self.root / "server" / "config" / "app.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("token: abc\n", encoding="utf-8")
        for command in (
            "cat server/config/app.yaml",
            "grep token server/config/app.yaml",
            "head -n 5 server/config/app.yaml",
            "cat server/config/app.yaml | grep token",
        ):
            with self.subTest(command=command):
                proc = _run_hook(self.root, "Bash", {"command": command}, str(self.root))
                self.assertEqual(_decision(proc), "deny")

    def test_shell_read_of_ordinary_file_is_allowed(self):
        proc = _run_hook(self.root, "Bash", {"command": "cat server/app.py"}, str(self.root))
        self.assertEqual(_decision(proc), "allow")

    def test_project_config_is_still_readable(self):
        """The guard's own file contract lives in config-shaped paths; denying
        those would stop DevFlow from reading its own state."""
        target = self.root / ".devflow" / "project.yaml"
        target.write_text("project:\n  name: x\n", encoding="utf-8")
        proc = _run_hook(self.root, "Read", {"file_path": str(target)}, str(self.root))
        self.assertEqual(_decision(proc), "allow")

    def test_ordinary_python_is_allowed(self):
        proc = self._write("server/app.py", "def handler():\n    return 1\n")
        self.assertEqual(_decision(proc), "allow")

    def test_auth_with_secret_is_asked(self):
        proc = self._write("server/auth/session.py", "API_KEY = 'sk-123'\n")
        self.assertEqual(_decision(proc), "ask")

    def test_auth_without_secret_is_allowed(self):
        proc = self._write(
            "server/auth/session.py", "def is_expired(ts, now):\n    return ts < now\n"
        )
        self.assertEqual(_decision(proc), "allow")

    def test_sensitive_marker_is_case_insensitive(self):
        proc = self._write("server/auth/db.py", "DB_PASSWORD: x\n")
        self.assertEqual(_decision(proc), "ask")

    def test_edit_without_secret_is_allowed(self):
        """Edit carries a diff snippet. When neither side mentions a
        credential, the edit is routine and passes.

        This is the deliberate loosening from the 2026-11 audit: an Edit is by
        definition a small, reviewable change, so a bare path match is not
        worth stopping for.
        """
        target = self.root / "package.json"
        target.write_text('{"name": "x"}\n', encoding="utf-8")
        proc = _run_hook(
            self.root,
            "Edit",
            {"file_path": str(target), "old_string": '"name": "x"', "new_string": '"name": "y"'},
            str(self.root),
        )
        self.assertEqual(_decision(proc), "allow")

    def test_edit_adding_a_secret_is_asked(self):
        target = self.root / "package.json"
        target.write_text('{"name": "x"}\n', encoding="utf-8")
        proc = _run_hook(
            self.root,
            "Edit",
            {"file_path": str(target), "old_string": '"name": "x"', "new_string": '"token": "abc"'},
            str(self.root),
        )
        self.assertEqual(_decision(proc), "ask")

    def test_forbidden_file_still_denied(self):
        proc = self._write(".env", "TOKEN=1\n")
        self.assertEqual(_decision(proc), "deny")


class BulkDestructiveCommandTest(unittest.TestCase):
    """Bulk-destructive commands destroy work in one shot and matched none of
    the original danger patterns (which only caught ``rm -rf /``, ``mkfs``,
    force-push and friends)."""

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

    def test_bulk_destructive_commands_are_blocked(self):
        for command in self.BULK:
            with self.subTest(command=command):
                self.assertIsNotNone(
                    check_dangerous_command(command),
                    f"bulk-destructive command was not detected: {command}",
                )

    def test_routine_commands_still_pass(self):
        for command in self.ROUTINE:
            with self.subTest(command=command):
                self.assertIsNone(
                    check_dangerous_command(command),
                    f"routine command was wrongly blocked: {command}",
                )

    def test_command_names_inside_a_commit_message_are_allowed(self):
        """The words appear as text, not as an invocation. Blocking here made
        the guard reject its own commit message."""
        for command in (
            'git commit -m "fix: stop using git reset --hard"',
            'git commit -m "docs: explain git clean -fd"',
            'echo "git checkout ." > notes.md',
            "git status  # not git clean -fd",
        ):
            with self.subTest(command=command):
                self.assertIsNone(
                    check_dangerous_command(command),
                    f"quoted mention was wrongly blocked: {command}",
                )

    def test_chained_bulk_command_is_still_blocked(self):
        """A real invocation after a chain operator must not slip through the
        segment split."""
        for command in (
            "echo hi && git reset --hard",
            "ls; git clean -fdx",
            "cd /tmp && find . -name '*.tmp' -delete",
            "sudo git branch -D main",
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(
                    check_dangerous_command(command),
                    f"chained bulk command was not detected: {command}",
                )

    def test_heredoc_body_is_not_scanned_as_a_command(self):
        """`git commit -F - <<'EOF'` passes a message on stdin. The words in
        it are prose — scanning them blocked the guard's own commit."""
        command = (
            "git commit -F - <<'EOF'\n"
            "fix: stop calling git reset --hard in CI to truncate -s 0 logs\n"
            "EOF\n"
        )
        self.assertIsNone(check_dangerous_command(command))

    def test_real_command_after_a_heredoc_is_still_blocked(self):
        command = "cat <<'EOF' > notes.txt\nhello\nEOF\ngit reset --hard\n"
        self.assertIsNotNone(check_dangerous_command(command))

    def test_expandable_strings_are_still_scanned(self):
        """Double quotes expand `$(...)`, so their contents can execute and
        must keep being checked."""
        self.assertIsNotNone(check_dangerous_command('echo "$(git reset --hard)"'))

    def test_backticks_inside_a_heredoc_are_text(self):
        """Markdown code spans in a PR body are backticks, not command
        substitution. Stripping heredocs has to happen before substitutions
        are hoisted, or writing the PR body blocks itself."""
        backtick = chr(96)
        command = (
            "cat > /tmp/pr.md <<'EOF'\n"
            f"- {backtick}git checkout .{backtick} and more\n"
            "EOF\n"
        )
        self.assertIsNone(check_dangerous_command(command))

    def test_backticks_outside_a_heredoc_still_execute(self):
        backtick = chr(96)
        self.assertIsNotNone(check_dangerous_command(f"echo {backtick}git clean -f{backtick}"))


class TempCleanupTest(unittest.TestCase):
    """Scratch-file cleanup under /tmp is routine during verification.

    It used to be blocked as a root wipe: the pattern's bare ``/`` alternative
    matched the leading slash of ``/tmp/scratch``. The QA agent hit this in the
    2026-11 dogfood, worked around it in memory, and reported it as friction —
    which is exactly the kind of thing that should become a test rather than a
    workaround.
    """

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

    def test_scratch_cleanup_is_allowed(self):
        for command in self.ALLOWED:
            with self.subTest(command=command):
                self.assertIsNone(
                    check_dangerous_command(command),
                    f"routine cleanup was blocked: {command}",
                )

    def test_root_and_home_wipes_are_still_blocked(self):
        for command in self.STILL_BLOCKED:
            with self.subTest(command=command):
                self.assertIsNotNone(
                    check_dangerous_command(command),
                    f"dangerous wipe was not blocked: {command}",
                )


class WorkspaceRootGuardTest(unittest.TestCase):
    """Multi-repo workspace: the session root is the boundary, drilled down."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="devflow-ws-test-")
        cls.ws = _make_ws(Path(cls.tmp) / "ws")
        cls.repo_a = _make_child(cls.ws, "repo-a")
        cls.repo_b = _make_child(cls.ws, "repo-b")

    @classmethod
    def tearDownClass(cls):
        import shutil

        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _decide(self, project_dir, target, cwd=None):
        return _decision(
            _run_hook(
                self.ws,
                "Write",
                {"file_path": str(target)},
                str(cwd if cwd is not None else project_dir),
                project_dir=project_dir,
            )
        )

    def test_workspace_root_can_write_across_repos(self):
        # Session at ws root: both child repos are under the root → allowed.
        self.assertEqual(self._decide(self.ws, self.repo_a / "src/main.go"), "allow")
        self.assertEqual(self._decide(self.ws, self.repo_b / "src/App.tsx"), "allow")

    def test_child_repo_root_cannot_write_sibling_repo(self):
        # Session at repo-a: repo-b is outside repo-a → denied.
        self.assertEqual(
            self._decide(self.repo_a, self.repo_b / "src/App.tsx"), "deny"
        )

    def test_child_repo_root_can_write_itself(self):
        self.assertEqual(
            self._decide(self.repo_a, self.repo_a / "src/main.go"), "allow"
        )

    def test_cwd_drift_does_not_move_the_root(self):
        # cwd drifted deep into repo-a, but launch dir is ws → still ws root,
        # so a redline file anywhere under ws is still enforced and a sibling
        # repo write is allowed.
        drifted = self.repo_a / "src/deep"
        drifted.mkdir(parents=True, exist_ok=True)
        self.assertEqual(
            self._decide(self.ws, self.repo_b / "src/App.tsx", cwd=drifted), "allow"
        )

    def test_redline_still_enforced_within_root(self):
        self.assertEqual(self._decide(self.ws, self.repo_a / ".env"), "deny")

    def test_agent_cannot_edit_devflow_config(self):
        # Inside the root, but DevFlow's own machinery → denied.
        self.assertEqual(self._decide(self.ws, self.ws / ".devflow/redlines.yaml"), "deny")
        self.assertEqual(self._decide(self.ws, self.ws / ".devflow/task.yaml"), "deny")

    def test_agent_can_write_devflow_artifact(self):
        self.assertEqual(self._decide(self.ws, self.ws / ".devflow/plan.md"), "allow")

    def test_init_window_allows_writing_config(self):
        # A never-initialised project (bare .devflow, no state file) — /devflow
        # init must be able to create project.yaml / rules/ / redlines.yaml.
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "fresh"
            (proj / ".devflow").mkdir(parents=True)
            for rel in ("project.yaml", "redlines.yaml", "rules/frontend.md"):
                self.assertEqual(
                    self._decide(proj, proj / ".devflow" / rel), "allow",
                    f"init should be able to write {rel}",
                )

    def test_init_window_rejects_non_init_paths(self):
        # Even during init, arbitrary .devflow/ files are not writable.
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "fresh"
            (proj / ".devflow").mkdir(parents=True)
            self.assertEqual(
                self._decide(proj, proj / ".devflow/random.md"), "deny"
            )

    def test_initialised_project_denies_config_without_a_task(self):
        # project.yaml already exists but no task yet → init window is closed;
        # config stays protected (a configured project can't treat itself as
        # still-initialising to rewrite its rules).
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "configured"
            (proj / ".devflow").mkdir(parents=True)
            (proj / ".devflow/project.yaml").write_text(
                'project:\n  name: x\n', encoding="utf-8"
            )
            self.assertEqual(
                self._decide(proj, proj / ".devflow/redlines.yaml"), "deny"
            )
            self.assertEqual(
                self._decide(proj, proj / ".devflow/rules/a.md"), "deny"
            )

    def test_uninitialised_dir_is_transparent(self):
        # repo-b has no .devflow; a session launched there is uninitialised.
        with tempfile.TemporaryDirectory() as td:
            plain = Path(td) / "plain"
            plain.mkdir()
            self.assertEqual(
                _decision(
                    _run_hook(plain, "Write", {"file_path": str(plain / "x.go")}, str(plain),
                              project_dir=plain)
                ),
                "allow",
            )

    def test_user_level_memory_write_allowed(self):
        # auto-memory / Memorant live outside the project root but must stay
        # writable — they are user-level infrastructure, not project files.
        memory = Path.home() / ".claude" / "projects" / "probe" / "memory" / "MEMORY.md"
        self.assertEqual(self._decide(self.ws, memory), "allow")

    def test_redline_still_applies_in_exempt_root(self):
        # The boundary exemption must not bypass the forbidden-file rule.
        secret = Path.home() / ".claude" / "projects" / "probe" / "memory" / ".env"
        self.assertEqual(self._decide(self.ws, secret), "deny")


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
