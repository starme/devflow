import tempfile
import unittest
from pathlib import Path

from project_analyzer import analyze_project, select_tracks


class ProjectAnalyzerTest(unittest.TestCase):
    def test_detects_agent_plugin_and_plugin_tracks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".claude-plugin").mkdir()
            (root / ".claude-plugin" / "plugin.json").write_text('{"name":"demo"}', encoding="utf-8")
            (root / "commands").mkdir()
            (root / "hooks").mkdir()
            (root / "SKILL.md").write_text("# A skill", encoding="utf-8")

            analysis = analyze_project(root)

            self.assertEqual(analysis.primary_category, "agent_plugin")
            self.assertIn("plugin", analysis.capabilities)
            self.assertIn("command", analysis.tracks)
            self.assertIn("hook", analysis.tracks)
            self.assertNotIn("backend", analysis.tracks)
            self.assertNotIn("frontend", analysis.tracks)

    def test_detects_mcp_server_from_protocol_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "server.py").write_text(
                "from mcp.server.fastmcp import FastMCP\nserver = FastMCP('demo')\n",
                encoding="utf-8",
            )

            analysis = analyze_project(root)

            self.assertEqual(analysis.primary_category, "mcp_server")
            self.assertIn("mcp", analysis.capabilities)
            self.assertIn("tool", analysis.tracks)

    def test_preserves_application_tracks_when_stack_is_present(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            (root / "web").mkdir()
            (root / "web" / "package.json").write_text("{}", encoding="utf-8")

            analysis = analyze_project(root)

            self.assertEqual(analysis.primary_category, "traditional_application")
            self.assertIn("backend", analysis.tracks)
            self.assertIn("frontend", analysis.tracks)

    def test_secret_files_are_not_used_as_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".env").write_text("MCP_SERVER=true\n", encoding="utf-8")
            (root / "secrets.yaml").write_text("plugin: true\n", encoding="utf-8")

            analysis = analyze_project(root)

            self.assertEqual(analysis.primary_category, "library_or_other")
            self.assertEqual(analysis.evidence[0].rule, "default")
            self.assertNotIn(".env", " ".join(e.path for e in analysis.evidence))

    def test_confirmed_category_selects_compatible_tracks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            analysis = analyze_project(temp_dir)

            tracks = select_tracks(analysis, "skill")

            self.assertIn("skill", tracks)
            self.assertIn("evaluation", tracks)
            self.assertNotIn("backend", tracks)


if __name__ == "__main__":
    unittest.main()
