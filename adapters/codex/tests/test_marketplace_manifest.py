import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
PLUGIN = ROOT / ".codex-plugin" / "plugin.json"
CLAUDE_PLUGIN = ROOT / ".claude-plugin" / "plugin.json"
SKILL = ROOT / "plugins" / "devflow" / "skills" / "devflow" / "SKILL.md"

# Semver, matching the manifest convention (MAJOR.MINOR.PATCH).
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


class MarketplaceManifestTest(unittest.TestCase):
    def test_repository_marketplace_manifest_points_to_repo_root(self):
        marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
        self.assertEqual(marketplace["name"], "devflow-marketplace")
        plugin = marketplace["plugins"][0]
        self.assertEqual(plugin["name"], "devflow")
        self.assertEqual(plugin["source"]["path"], ".")

    def test_plugin_manifest_exposes_devflow_skill(self):
        plugin = json.loads(PLUGIN.read_text(encoding="utf-8"))
        self.assertEqual(plugin["name"], "devflow")
        # Assert the format, not a literal: pinning the number made every
        # release fail this test for no defect.
        self.assertRegex(plugin["version"], _VERSION)
        self.assertEqual(plugin["author"]["name"], "starme")
        self.assertEqual(plugin["skills"], "./plugins/devflow/skills/")
        self.assertTrue(SKILL.is_file())

    def test_claude_and_codex_manifests_share_version(self):
        # Both manifests ship the same plugin, so a release must bump both or
        # the marketplace serves two versions of one name.
        codex = json.loads(PLUGIN.read_text(encoding="utf-8"))
        claude = json.loads(CLAUDE_PLUGIN.read_text(encoding="utf-8"))
        self.assertEqual(codex["version"], claude["version"])

    def test_marketplace_source_includes_core_and_codex_manifest(self):
        source = json.loads(MARKETPLACE.read_text(encoding="utf-8"))["plugins"][0]["source"]["path"]
        plugin_root = (ROOT / source).resolve()
        self.assertEqual(plugin_root, ROOT.resolve())
        self.assertTrue((plugin_root / ".codex-plugin" / "plugin.json").is_file())
        self.assertTrue((plugin_root / "core" / "orchestrator").is_dir())
        self.assertTrue((plugin_root / "core" / "orchestrator" / "delivery.py").is_file())
        self.assertTrue((plugin_root / "core" / "orchestrator" / "artifact_publish.py").is_file())


if __name__ == "__main__":
    unittest.main()
