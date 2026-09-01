#!/usr/bin/env python3
"""Tests for one-shot legacy deliverable archive migration (archive_migration.py).

Covers the legacy PRD migration (copy + pointer file + manifest sync), the four
flat deliverables moved into semantic ``legacy-*`` directories, idempotent
second-run skip, and conflict refusal on a differing target.  Every fixture is
built under ``tempfile`` so tests never touch a real repository.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ORCHESTRATOR = Path(__file__).resolve().parents[1] / "orchestrator"
sys.path.insert(0, str(ORCHESTRATOR))

import archive_migration as am  # noqa: E402


def _manifest(prd_path: str = ".devflow/agent-plugin-compatibility-prd.md") -> str:
    return (
        "project:\n"
        "  name: \"demo\"\n"
        "\n"
        "phases:\n"
        "  prd_writing:\n"
        "    status: \"completed\"\n"
        f"    prd_path: \"{prd_path}\"\n"
        "  architecture:\n"
        "    status: \"pending\"\n"
        "    architecture_doc_path: \"docs/architecture.md\"\n"
        "\n"
        "artifacts:\n"
        f"  prd: \"{prd_path}\"\n"
        "  architecture_doc: null\n"
    )


class _Fixture:
    def __init__(self, temp: str) -> None:
        self.root = Path(temp)
        self.devflow = self.root / ".devflow"
        self.devflow.mkdir()

    def write_manifest(self, content: str) -> Path:
        path = self.devflow / "manifest.yaml"
        path.write_text(content, encoding="utf-8")
        return path

    def write(self, rel: str, content: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path


class LegacyPrdMigrationTest(unittest.TestCase):
    def test_migrates_prd_with_pointer_and_manifest_sync(self):
        f = _Fixture(tempfile.mkdtemp())
        f.write_manifest(_manifest())
        f.write(".devflow/agent-plugin-compatibility-prd.md", "legacy prd body")

        result = am.migrate_legacy_archive(f.root)

        self.assertEqual(result["status"], "migrated")
        # Target holds the original PRD content.
        target = f.root / ".devflow" / "tasks" / "legacy" / "prd-agent-plugin-compatibility.md"
        self.assertEqual(target.read_text(encoding="utf-8"), "legacy prd body")
        # Original position is now a pointer to the migrated path, not the body.
        pointer = f.root / ".devflow" / "agent-plugin-compatibility-prd.md"
        pointer_text = pointer.read_text(encoding="utf-8")
        self.assertIn("prd-agent-plugin-compatibility.md", pointer_text)
        self.assertNotIn("legacy prd body", pointer_text)
        # Manifest rewrite: prd_writing.prd_path and artifacts.prd now point at
        # the migrated path.
        manifest = (f.root / ".devflow" / "manifest.yaml").read_text(encoding="utf-8")
        self.assertIn(
            'prd_path: ".devflow/tasks/legacy/prd-agent-plugin-compatibility.md"',
            manifest,
        )
        self.assertIn(
            'prd: ".devflow/tasks/legacy/prd-agent-plugin-compatibility.md"', manifest
        )


class FlatArtifactMigrationTest(unittest.TestCase):
    def test_migrates_flat_artifacts_into_semantic_dirs(self):
        f = _Fixture(tempfile.mkdtemp())
        f.write_manifest(_manifest())
        f.write("PRD-DevFlow.md", "prd v1")
        f.write("review-report.md", "review")
        f.write("docs/architecture.md", "arch v2")
        f.write("docs/delivery-report.md", "delivery v2")

        result = am.migrate_legacy_archive(f.root)

        self.assertEqual(result["status"], "migrated")
        cases = [
            (".devflow/tasks/legacy-v01-prd/PRD-DevFlow.md", "prd v1"),
            (".devflow/tasks/legacy-doc-review/review-report.md", "review"),
            (".devflow/tasks/legacy-v02-arch/architecture.md", "arch v2"),
            (".devflow/tasks/legacy-v02-delivery/delivery-report.md", "delivery v2"),
        ]
        for rel, expected in cases:
            path = f.root / rel
            self.assertTrue(path.is_file(), rel)
            self.assertEqual(path.read_text(encoding="utf-8"), expected)
        # Each semantic dir carries a minimal README source index.
        for rel, _ in cases:
            readme = f.root / rel.removesuffix(Path(rel).name) / "README.md"
            self.assertTrue(readme.is_file(), f"README missing for {rel}")
        # Original files are preserved (copy2, never deleted).
        self.assertTrue((f.root / "PRD-DevFlow.md").is_file())
        self.assertTrue((f.root / "docs" / "architecture.md").is_file())
        # architecture_doc_path re-pointed off docs/architecture.md.
        manifest = (f.root / ".devflow" / "manifest.yaml").read_text(encoding="utf-8")
        self.assertIn(
            'architecture_doc_path: ".devflow/tasks/legacy-v02-arch/architecture.md"',
            manifest,
        )


class IdempotencyTest(unittest.TestCase):
    def test_second_run_skips_and_keeps_content(self):
        f = _Fixture(tempfile.mkdtemp())
        f.write_manifest(_manifest())
        f.write(".devflow/agent-plugin-compatibility-prd.md", "prd")
        f.write("PRD-DevFlow.md", "flat")
        self.assertEqual(am.migrate_legacy_archive(f.root)["status"], "migrated")

        second = am.migrate_legacy_archive(f.root)

        self.assertEqual(second["status"], "already_migrated")
        target = f.root / ".devflow" / "tasks" / "legacy" / "prd-agent-plugin-compatibility.md"
        self.assertEqual(target.read_text(encoding="utf-8"), "prd")

    def test_conflict_on_differing_target_raises(self):
        f = _Fixture(tempfile.mkdtemp())
        f.write_manifest(_manifest())
        f.write(".devflow/agent-plugin-compatibility-prd.md", "new prd")
        target = f.root / ".devflow" / "tasks" / "legacy" / "prd-agent-plugin-compatibility.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("stale prd", encoding="utf-8")

        with self.assertRaises(am.ArchiveMigrationConflict):
            am.migrate_legacy_archive(f.root)


if __name__ == "__main__":
    unittest.main()