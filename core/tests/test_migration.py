#!/usr/bin/env python3
"""Regression tests for automatic legacy metadata migration."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
from migration import migrate_legacy_project  # noqa: E402


class MigrationTest(unittest.TestCase):
    def test_migrates_without_changing_manifest_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            manifest = devflow / "manifest.yaml"
            original = (
                "project:\n"
                "  name: \"demo\"\n"
                "  created_at: \"2026-08-20T00:00:00Z\"\n"
                "  current_phase: \"gate_prd\"\n"
                "  work_type: \"feature\"\n"
                "  category: \"agent_plugin\"\n"
                "  category_confidence: \"0.9\"\n"
                "  capabilities: [plugin, skill]\n"
                "adapter:\n"
                "  name: \"claude-code\"\n"
                "  capability: \"hard\"\n"
                "workspace:\n"
                f"  root: \"{root}\"\n"
                "phases:\n"
                "  classify:\n"
                "    task_description: \"Add isolation\"\n"
            )
            manifest.write_text(original, encoding="utf-8")

            first = migrate_legacy_project(root)
            second = migrate_legacy_project(root)

            self.assertEqual(first["status"], "migrated")
            self.assertEqual(second["status"], "already_migrated")
            self.assertEqual(manifest.read_text(encoding="utf-8"), original)
            self.assertTrue((devflow / "project.yaml").is_file())
            task = (devflow / "tasks" / "legacy" / "task.yaml").read_text(encoding="utf-8")
            self.assertIn('current_phase: "gate_prd"', task)
            self.assertIn('mode: "legacy"', task)


if __name__ == "__main__":
    unittest.main()
