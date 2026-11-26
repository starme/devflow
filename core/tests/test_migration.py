#!/usr/bin/env python3
"""Regression tests for automatic legacy metadata migration."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
from migration import migrate_legacy_project


def test_migrates_without_changing_manifest_and_is_idempotent():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        devflow = root / ".devflow"
        devflow.mkdir()
        manifest = devflow / "manifest.yaml"
        original = (
            "project:\n"
            '  name: "demo"\n'
            '  created_at: "2026-08-20T00:00:00Z"\n'
            '  current_phase: "gate_prd"\n'
            '  work_type: "feature"\n'
            '  category: "agent_plugin"\n'
            '  category_confidence: "0.9"\n'
            "  capabilities: [plugin, skill]\n"
            "adapter:\n"
            '  name: "claude-code"\n'
            '  capability: "hard"\n'
            "workspace:\n"
            f'  root: "{root}"\n'
            "phases:\n"
            "  classify:\n"
            '    task_description: "Add isolation"\n'
        )
        manifest.write_text(original, encoding="utf-8")

        first = migrate_legacy_project(root)
        second = migrate_legacy_project(root)

        assert first["status"] == "migrated"
        assert second["status"] == "already_migrated"
        assert manifest.read_text(encoding="utf-8") == original
        assert (devflow / "project.yaml").is_file()
        task = (devflow / "tasks" / "legacy" / "task.yaml").read_text(encoding="utf-8")
        assert 'current_phase: "gate_prd"' in task
        assert 'mode: "legacy"' in task

