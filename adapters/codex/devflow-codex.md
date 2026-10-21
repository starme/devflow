# DevFlow Codex Skill / turn payload

Use this payload as the `skill` input to Codex `turn/start`, or copy the instructions into a Codex Skill named `devflow`.

```text
You are executing DevFlow in Codex. Read core/orchestrator/SKILL.md, the
project's .devflow/project.yaml, and the current task's .devflow/task.yaml.
Work through the six statuses (qa → prd_review → plan_review → working →
deliver_confirm → done) directly on the task's feature branch — you implement
yourself; there is no role-agent dispatch. Codex redline enforcement is soft:
use Codex approvals and core audit logging, and never claim generic hard
pre-tool interception. For GATE-V, execute the plan card's acceptance criteria
in the main thread and mark the report "main-thread verification, not an
independent verifier". Delivery is soft — commit/push go through host approval
and PR creation is routed via the host (gh_pr_url), never claimed as a hard PR
capability, and the PR is never merged automatically.
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
