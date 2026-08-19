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

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "redline-guard.py"


def _run_hook(project_root, tool_name, tool_input, cwd):
    """Invoke redline-guard.py and return the subprocess result."""
    payload = {"tool_name": tool_name, "tool_input": tool_input, "cwd": cwd}
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=project_root,
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
            "  root: \"{root}\"\n"
            "  backend:\n"
            "    path: \"server\"\n"
            "  frontend:\n"
            "    path: \"web\"\n"
            "  contract:\n"
            "    path: \".devflow/contracts\"\n"
        ).format(root=cls.root)
        (cls.root / ".devflow" / "manifest.yaml").write_text(manifest, encoding="utf-8")

        redlines = (
            "forbidden:\n"
            "  - \".env\"\n"
            "protected:\n"
            "  - \".github/**\"\n"
            "approval_required:\n"
            "  - \"package.json\"\n"
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
        (self.root / ".devflow" / "context.json").write_text(
            json.dumps(ctx), encoding="utf-8"
        )

    # --- boundary matrix -------------------------------------------------

    def test_backend_writes_backend_allowed(self):
        self._write_context(self.backend)
        target = self.backend / "internal" / "handler.go"
        proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.backend))
        self.assertEqual(_decision(proc), "allow")

    def test_backend_writes_frontend_denied(self):
        self._write_context(self.backend)
        target = self.frontend / "src" / "App.tsx"
        proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.backend))
        self.assertEqual(_decision(proc), "deny")

    def test_frontend_writes_backend_denied(self):
        self._write_context(self.frontend, agent="devflow-frontend-dev")
        target = self.backend / "internal" / "handler.go"
        proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.frontend))
        self.assertEqual(_decision(proc), "deny")

    def test_dev_agent_writes_contract_denied(self):
        self._write_context(self.backend)
        target = self.contracts / "api.yaml"
        proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.backend))
        self.assertEqual(_decision(proc), "deny")

    # --- redline regression ---------------------------------------------

    def test_forbidden_file_denied(self):
        self._write_context(self.backend)
        target = self.root / ".env"
        proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.backend))
        self.assertEqual(_decision(proc), "deny")

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
            "  root: \"{root}\"\n"
            "  backend:\n"
            "    path: \"server\"\n"
            "  frontend:\n"
            "    path: \"web\"\n"
            "  contract:\n"
            "    path: \".devflow/contracts\"\n"
        ).format(root=cls.root)
        (cls.root / ".devflow" / "manifest.yaml").write_text(manifest, encoding="utf-8")

        redlines = (
            "forbidden:\n"
            "  - \".env\"\n"
            "protected:\n"
            "  - \".github/**\"\n"
            "approval_required:\n"
            "  - \"package.json\"\n"
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
        (self.root / ".devflow" / "context.json").write_text(
            json.dumps(ctx), encoding="utf-8"
        )

    def test_worktree_backend_writes_backend_code_allowed(self):
        """Backend agent in worktree can write to worktree's server/ dir."""
        self._write_context(self.wt_backend)
        target = self.wt_backend / "internal" / "handler.go"
        proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.wt_backend))
        self.assertEqual(_decision(proc), "allow")

    def test_worktree_backend_writes_frontend_denied(self):
        """Backend agent in worktree cannot write to worktree's web/ dir."""
        self._write_context(self.wt_backend)
        target = self.wt_frontend / "src" / "App.tsx"
        proc = _run_hook(self.root, "Write", {"file_path": str(target)}, str(self.wt_backend))
        self.assertEqual(_decision(proc), "deny")

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
            self.root, "Write",
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


class WorktreeSyncTest(unittest.TestCase):
    """Tests for worktree_sync.py artifact collection."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="devflow-sync-test-")
        cls.root = Path(cls.tmp) / "project"
        cls.wt1 = cls.root / ".claude" / "worktrees" / "agent-aaa"
        cls.wt2 = cls.root / ".claude" / "worktrees" / "agent-bbb"

        # Main .devflow
        (cls.root / ".devflow").mkdir(parents=True)
        (cls.root / ".devflow" / "manifest.yaml").write_text("project:\n", encoding="utf-8")
        (cls.root / ".devflow" / "redlines.yaml").write_text("forbidden: []\n", encoding="utf-8")
        (cls.root / ".devflow" / "rules").mkdir()
        (cls.root / ".devflow" / "rules" / "project.md").write_text("rules", encoding="utf-8")

        # Worktree 1 with artifacts
        (cls.wt1 / ".devflow").mkdir(parents=True)
        (cls.wt1 / ".devflow" / "scope.yaml").write_text("scope: v1", encoding="utf-8")
        (cls.wt1 / ".devflow" / "backend-task-report.md").write_text("report", encoding="utf-8")
        (cls.wt1 / ".devflow" / "runs" / "run1").mkdir(parents=True)
        (cls.wt1 / ".devflow" / "runs" / "run1" / "audit.log").write_text("log", encoding="utf-8")

        # Worktree 2 with different artifacts
        (cls.wt2 / ".devflow").mkdir(parents=True)
        (cls.wt2 / ".devflow" / "frontend-task-report.md").write_text("fe report", encoding="utf-8")

        # Worktree 1 also has a protected file that should NOT be collected
        (cls.wt1 / ".devflow" / "redlines.yaml").write_text("EVIL", encoding="utf-8")
        (cls.wt1 / ".devflow" / "rules").mkdir()
        (cls.wt1 / ".devflow" / "rules" / "evil.md").write_text("evil", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_collect_artifacts(self):
        sync_script = Path(__file__).resolve().parent.parent / "orchestrator" / "worktree_sync.py"
        proc = subprocess.run(
            [sys.executable, str(sync_script), "collect", "--root", str(self.root)],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        result = json.loads(proc.stdout)

        # scope.yaml and reports should be collected
        self.assertTrue((self.root / ".devflow" / "scope.yaml").is_file())
        self.assertTrue((self.root / ".devflow" / "backend-task-report.md").is_file())
        self.assertTrue((self.root / ".devflow" / "frontend-task-report.md").is_file())

        # runs/ directory should be collected
        self.assertTrue((self.root / ".devflow" / "runs" / "run1" / "audit.log").is_file())

        # Protected files should NOT be overwritten
        self.assertEqual(
            (self.root / ".devflow" / "redlines.yaml").read_text(encoding="utf-8"),
            "forbidden: []\n"
        )
        self.assertFalse((self.root / ".devflow" / "rules" / "evil.md").exists())

        # Result should report synced files
        synced_files = []
        for wt in result.get("synced", []):
            synced_files.extend(wt["files"])
        self.assertIn("scope.yaml", synced_files)
        self.assertIn("backend-task-report.md", synced_files)
        self.assertNotIn("redlines.yaml", synced_files)
        self.assertNotIn("rules/evil.md", synced_files)

    def test_symlink_artifact_outside_worktree_is_skipped(self):
        outside = Path(self.tmp) / "outside-secret.txt"
        outside.write_text("secret", encoding="utf-8")
        link = self.wt1 / ".devflow" / "leaked.md"
        link.symlink_to(outside)

        sync_script = Path(__file__).resolve().parent.parent / "orchestrator" / "worktree_sync.py"
        proc = subprocess.run(
            [sys.executable, str(sync_script), "collect", "--root", str(self.root)],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        result = json.loads(proc.stdout)

        self.assertFalse((self.root / ".devflow" / "leaked.md").exists())
        synced_files = [path for wt in result["synced"] for path in wt["files"]]
        self.assertNotIn("leaked.md", synced_files)


if __name__ == "__main__":
    unittest.main(verbosity=2)