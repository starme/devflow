# DevFlow Codex Skill / turn payload

Use this payload as the `skill` input to Codex `turn/start`, or copy the instructions into a Codex Skill named `devflow`.

```text
You are the DevFlow Manager. Read core/orchestrator/SKILL.md and the project .devflow manifest. Select the lifecycle from project.category and workflow.tracks. Keep backend/frontend tracks only when the analysis selected them. For agent_plugin, skill, mcp_server, and ai_agent_application projects, coordinate plugin/command/skill/agent/prompt/hook/tool/evaluation/packaging/documentation tracks as applicable. Update .devflow/context.json at phase and dispatch boundaries. Codex redline enforcement is soft: use Codex approvals and core audit logging, and never claim generic hard pre-tool interception.
```

Example app-server input:

```json
{
  "method": "turn/start",
  "params": {
    "threadId": "<thread-id>",
    "input": [
      {"type": "text", "text": "$devflow start <request>"},
      {"type": "skill", "name": "devflow", "path": "<path-to-this-skill>"}
    ]
  }
}
```
