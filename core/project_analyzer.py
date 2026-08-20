#!/usr/bin/env python3
"""Evidence-based project classification and lifecycle track selection."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Dict, Iterable, List, Optional, Set, Tuple, Union


CATEGORIES = (
    "traditional_application",
    "ai_agent_application",
    "agent_plugin",
    "skill",
    "mcp_server",
    "ai_tool_or_workflow",
    "library_or_other",
)

TRACKS_BY_CATEGORY = {
    "traditional_application": ("product", "architecture", "backend", "frontend", "integration", "testing", "acceptance", "distill"),
    "ai_agent_application": ("product", "architecture", "agent", "prompt", "integration", "evaluation", "testing", "acceptance", "distill"),
    "agent_plugin": ("product", "architecture", "plugin", "command", "skill", "agent", "hook", "evaluation", "packaging", "documentation", "testing", "acceptance", "distill"),
    "skill": ("product", "architecture", "skill", "prompt", "evaluation", "packaging", "documentation", "testing", "acceptance", "distill"),
    "mcp_server": ("product", "architecture", "mcp", "tool", "integration", "evaluation", "packaging", "documentation", "testing", "acceptance", "distill"),
    "ai_tool_or_workflow": ("product", "architecture", "agent", "prompt", "tool", "integration", "evaluation", "documentation", "testing", "acceptance", "distill"),
    "library_or_other": ("product", "architecture", "implementation", "testing", "documentation", "acceptance", "distill"),
}

SAFE_TEXT_NAMES = {"README", "README.md", "README.rst", "README.txt", "AGENTS.md", "SKILL.md"}
IGNORED_DIRS = {".git", ".devflow", ".claude", "node_modules", "__pycache__", ".venv", "venv"}
SECRET_PATTERNS = (".env", ".pem", ".key", "secrets.", "credentials.")


@dataclass(frozen=True)
class Evidence:
    path: str
    rule: str
    summary: str
    weight: int
    category: Optional[str] = None


@dataclass(frozen=True)
class CategoryScore:
    category: str
    score: int


@dataclass
class ProjectAnalysis:
    primary_category: str
    confidence: float
    evidence: List[Evidence] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    tracks: List[str] = field(default_factory=list)
    alternatives: List[CategoryScore] = field(default_factory=list)
    ambiguous: bool = False

    def as_dict(self) -> Dict[str, object]:
        return {
            "primary_category": self.primary_category,
            "confidence": self.confidence,
            "evidence": [e.__dict__ for e in self.evidence],
            "capabilities": self.capabilities,
            "tracks": self.tracks,
            "alternatives": [s.__dict__ for s in self.alternatives],
            "ambiguous": self.ambiguous,
        }


def _is_secret(path: Path) -> bool:
    name = path.name.lower()
    return (
        name == ".env"
        or name.startswith(".env.")
        or name.startswith("secrets.")
        or name.startswith("credentials.")
        or name.endswith((".pem", ".key"))
    )


def _read_text(path: Path, limit: int = 100_000) -> str:
    try:
        if _is_secret(path) or not path.is_file() or path.stat().st_size > limit:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _iter_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if any(part in IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file() and not _is_secret(path):
            yield path


def _add(evidence: List[Evidence], path: str, rule: str, summary: str, weight: int, category: Optional[str] = None) -> None:
    evidence.append(Evidence(path, rule, summary, weight, category))


def _detect_capabilities(root: Path, files: List[Path]) -> Set[str]:
    capabilities: set[str] = set()
    names = {path.name for path in files}
    dirs = {part for path in files for part in path.relative_to(root).parts[:-1]}
    if any(name in {"go.mod", "composer.json", "pyproject.toml", "requirements.txt", "Cargo.toml", "pom.xml"} for name in names):
        capabilities.add("backend")
    if "package.json" in names or "web" in dirs or "frontend" in dirs:
        capabilities.add("frontend")
    if "SKILL.md" in names or "skills" in dirs:
        capabilities.add("skills")
    if "AGENTS.md" in names or "agents" in dirs:
        capabilities.add("agents")
    if "hooks" in dirs or any("hook" in path.name.lower() for path in files):
        capabilities.add("hooks")
    if "commands" in dirs or any("command" in path.name.lower() for path in files):
        capabilities.add("commands")
    if "prompts" in dirs or "prompt" in dirs:
        capabilities.add("prompts")
    if "evals" in dirs or "evaluations" in dirs or "tests" in dirs:
        capabilities.add("evaluations")
    if "mcp" in dirs or any("mcp" in path.name.lower() for path in files):
        capabilities.add("mcp")
    if any(name in {"plugin.json", "marketplace.json"} for name in names) or ".claude-plugin" in dirs:
        capabilities.add("plugin")
    if "Dockerfile" in names or "install.sh" in names or "package.json" in names:
        capabilities.add("packaging")
    return capabilities


def analyze_project(root: Union[str, Path]) -> ProjectAnalysis:
    """Classify a repository using explainable, safe filesystem evidence."""
    project_root = Path(root).resolve()
    files = list(_iter_files(project_root))
    evidence: List[Evidence] = []
    scores = {category: 0 for category in CATEGORIES}
    capabilities = _detect_capabilities(project_root, files)

    def signal(category: str, path: str, rule: str, summary: str, weight: int) -> None:
        scores[category] += weight
        _add(evidence, path, rule, summary, weight, category)

    names = {path.name for path in files}
    relative = {str(path.relative_to(project_root)) for path in files}
    if any(path.startswith(".claude-plugin/") for path in relative) or "plugin.json" in names:
        signal("agent_plugin", ".claude-plugin", "plugin_manifest", "Claude plugin metadata detected", 10)
    if "SKILL.md" in names or "skills" in {p for path in files for p in path.relative_to(project_root).parts}:
        signal("skill", "SKILL.md", "skill_definition", "Skill definition or skills directory detected", 9)
    if "AGENTS.md" in names or "agents" in {p for path in files for p in path.relative_to(project_root).parts}:
        signal("ai_agent_application", "AGENTS.md", "agent_instructions", "Agent instructions or agent directory detected", 7)
    if "mcp" in capabilities:
        signal("mcp_server", "mcp", "mcp_artifact", "MCP-related directory or file detected", 10)
    for path in files:
        if path.name not in SAFE_TEXT_NAMES and path.suffix.lower() not in {".json", ".toml", ".yaml", ".yml", ".py", ".ts", ".js", ".rs", ".go"}:
            continue
        text = _read_text(path)
        lower = text.lower()
        if "model context protocol" in lower or "mcpserver" in lower or "mcp.server" in lower or "@modelcontextprotocol" in lower:
            capabilities.add("mcp")
            signal("mcp_server", str(path.relative_to(project_root)), "mcp_protocol", "MCP protocol reference detected", 8)
        if re.search(r"\b(agent|llm|language model|prompt|tool calling|function calling)\b", lower):
            signal("ai_agent_application", str(path.relative_to(project_root)), "ai_terminology", "AI agent terminology detected", 2)
        if "plugin" in lower and ("claude" in lower or "codex" in lower or "skill" in lower):
            signal("agent_plugin", str(path.relative_to(project_root)), "plugin_documentation", "AI plugin documentation detected", 4)

    if capabilities & {"backend", "frontend"}:
        signal("traditional_application", "project markers", "application_stack", "Traditional application stack marker detected", 6)
    if not evidence:
        signal("library_or_other", ".", "default", "No stronger project category evidence detected", 1)

    ranked = sorted((CategoryScore(category, score) for category, score in scores.items()), key=lambda item: (-item.score, item.category))
    top, second = ranked[0], ranked[1]
    total = sum(score for score in scores.values()) or 1
    confidence = round(min(1.0, max(0.0, top.score / total)), 2)
    ambiguous = top.score == 0 or (top.score == second.score and top.score > 0) or top.score - second.score <= 2
    category = top.category
    selected_tracks = list(TRACKS_BY_CATEGORY[category])
    if "backend" in capabilities and "backend" not in selected_tracks:
        selected_tracks.insert(3, "backend")
    if "frontend" in capabilities and "frontend" not in selected_tracks:
        selected_tracks.insert(4, "frontend")
    return ProjectAnalysis(category, confidence, evidence, sorted(capabilities), selected_tracks, ranked[1:4], ambiguous)


def select_tracks(analysis: ProjectAnalysis, confirmed_category: Optional[str] = None) -> List[str]:
    """Return tracks for an analysis, optionally honoring a user confirmation."""
    category = confirmed_category or analysis.primary_category
    if category not in TRACKS_BY_CATEGORY:
        raise ValueError(f"unsupported project category: {category}")
    tracks = list(TRACKS_BY_CATEGORY[category])
    for capability, track in (("backend", "backend"), ("frontend", "frontend")):
        if capability in analysis.capabilities and track not in tracks:
            tracks.insert(3, track)
    return tracks
