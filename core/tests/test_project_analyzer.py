import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from project_analyzer import analyze_project, select_tracks


def test_detects_agent_plugin_and_plugin_tracks():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / ".claude-plugin").mkdir()
        (root / ".claude-plugin" / "plugin.json").write_text(
            '{"name":"demo"}', encoding="utf-8"
        )
        (root / "commands").mkdir()
        (root / "hooks").mkdir()
        (root / "SKILL.md").write_text("# A skill", encoding="utf-8")

        analysis = analyze_project(root)

        assert analysis.primary_category == "agent_plugin"
        assert "plugin" in analysis.capabilities
        assert "command" in analysis.tracks
        assert "hook" in analysis.tracks
        assert "backend" not in analysis.tracks
        assert "frontend" not in analysis.tracks


def test_detects_mcp_server_from_protocol_evidence():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "server.py").write_text(
            "from mcp.server.fastmcp import FastMCP\nserver = FastMCP('demo')\n",
            encoding="utf-8",
        )

        analysis = analyze_project(root)

        assert analysis.primary_category == "mcp_server"
        assert "mcp" in analysis.capabilities
        assert "tool" in analysis.tracks


def test_preserves_application_tracks_when_stack_is_present():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
        (root / "web").mkdir()
        (root / "web" / "package.json").write_text("{}", encoding="utf-8")

        analysis = analyze_project(root)

        assert analysis.primary_category == "traditional_application"
        assert "backend" in analysis.tracks
        assert "frontend" in analysis.tracks


def test_secret_files_are_not_used_as_evidence():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / ".env").write_text("MCP_SERVER=true\n", encoding="utf-8")
        (root / "secrets.yaml").write_text("plugin: true\n", encoding="utf-8")

        analysis = analyze_project(root)

        assert analysis.primary_category == "library_or_other"
        assert analysis.evidence[0].rule == "default"
        assert ".env" not in " ".join(e.path for e in analysis.evidence)


def test_confirmed_category_selects_compatible_tracks():
    with tempfile.TemporaryDirectory() as temp_dir:
        analysis = analyze_project(temp_dir)

        tracks = select_tracks(analysis, "skill")

        assert "skill" in tracks
        assert "evaluation" in tracks
        assert "backend" not in tracks

