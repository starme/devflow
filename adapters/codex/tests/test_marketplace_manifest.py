import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
PLUGIN = ROOT / "plugins" / "devflow" / ".codex-plugin" / "plugin.json"
SKILL = ROOT / "plugins" / "devflow" / "skills" / "devflow" / "SKILL.md"


class MarketplaceManifestTest(unittest.TestCase):
    def test_repository_marketplace_manifest_points_to_plugin(self):
        marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
        self.assertEqual(marketplace["name"], "devflow-marketplace")
        plugin = marketplace["plugins"][0]
        self.assertEqual(plugin["name"], "devflow")
        self.assertEqual(plugin["source"]["path"], "./plugins/devflow")

    def test_plugin_manifest_exposes_devflow_skill(self):
        plugin = json.loads(PLUGIN.read_text(encoding="utf-8"))
        self.assertEqual(plugin["name"], "devflow")
        self.assertEqual(plugin["skills"], "./skills/")
        self.assertTrue(SKILL.is_file())

    def test_marketplace_source_stays_inside_repository(self):
        source = json.loads(MARKETPLACE.read_text(encoding="utf-8"))["plugins"][0]["source"]["path"]
        self.assertFalse((ROOT / source).resolve().relative_to(ROOT.resolve()).parts == ())
        self.assertTrue((ROOT / source / ".codex-plugin" / "plugin.json").is_file())


if __name__ == "__main__":
    unittest.main()
