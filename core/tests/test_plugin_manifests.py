"""Cross-manifest consistency tests.

DevFlow ships three plugin manifests for two hosts:

- ``.claude-plugin/plugin.json``      — Claude Code
- ``.codex-plugin/plugin.json``       — Codex (marketplace source)
- ``plugins/devflow/.codex-plugin/plugin.json`` — nested Skill-only fallback

They are maintained by hand, so a version bump applied to one and forgotten in
the others ships a broken release. That already happened once (PR #14, where a
marketplace test still asserted 1.0.1 while the main manifest had moved on).
These tests pin the fields that must agree.

``skills`` legitimately differs between the root manifests and the nested
fallback (relative to each package root), so only existence is asserted.
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PLUGIN_MANIFESTS = {
    "claude": ROOT / ".claude-plugin" / "plugin.json",
    "codex-root": ROOT / ".codex-plugin" / "plugin.json",
    "codex-nested": ROOT / "plugins" / "devflow" / ".codex-plugin" / "plugin.json",
}

MARKETPLACES = {
    "claude": ROOT / ".claude-plugin" / "marketplace.json",
    "codex": ROOT / ".agents" / "plugins" / "marketplace.json",
}


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


class PluginManifestTest(unittest.TestCase):
    def test_all_plugin_manifests_exist(self):
        for label, path in PLUGIN_MANIFESTS.items():
            with self.subTest(manifest=label):
                self.assertTrue(path.is_file(), f"{label} manifest missing: {path}")

    def test_plugin_names_agree(self):
        names = {label: _load(p)["name"] for label, p in PLUGIN_MANIFESTS.items()}
        self.assertEqual(set(names.values()), {"devflow"}, names)

    def test_plugin_versions_agree(self):
        versions = {label: _load(p)["version"] for label, p in PLUGIN_MANIFESTS.items()}
        self.assertEqual(
            len(set(versions.values())),
            1,
            f"plugin versions drifted apart: {versions}",
        )

    def test_skill_directories_resolve(self):
        # Root manifests are published from the repo root; the nested fallback
        # is published from its own package directory.
        package_roots = {
            "claude": ROOT,
            "codex-root": ROOT,
            "codex-nested": ROOT / "plugins" / "devflow",
        }
        for label, path in PLUGIN_MANIFESTS.items():
            with self.subTest(manifest=label):
                skills = _load(path).get("skills")
                if not skills:
                    continue
                self.assertTrue(
                    (package_roots[label] / skills).is_dir(),
                    f"{label}: skills path {skills!r} does not resolve",
                )


class MarketplaceManifestTest(unittest.TestCase):
    def test_marketplaces_share_a_name(self):
        names = {label: _load(p)["name"] for label, p in MARKETPLACES.items()}
        self.assertEqual(set(names.values()), {"devflow-marketplace"}, names)

    def test_marketplaces_expose_the_devflow_plugin(self):
        for label, path in MARKETPLACES.items():
            with self.subTest(marketplace=label):
                plugins = _load(path)["plugins"]
                self.assertEqual([p["name"] for p in plugins], ["devflow"])


if __name__ == "__main__":
    unittest.main()
