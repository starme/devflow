# Legacy（v1 编排层遗物）

按 [ADR-0005](../docs/adr/0005-orchestration-recalibration.md) 校准：以下文件随
"多 Agent 编排"模式退役。**物理删除待逐项确认**——在此期间保留原文，供回溯 v1
行为与旧任务的人工收尾参考。

| 文件 | v1 职责 | v2 替代 |
|---|---|---|
| `agents/product-agent.md` | 写 PRD、验收检查 | 主线程 + PRD 模板（`core/templates/prd.md`）+ GATE-3 验证报告 |
| `agents/architect-agent.md` | 技术方案、scope.yaml | 主线程 + 方案卡模板（`core/templates/task-card.md`） |
| `agents/backend-dev-agent.md` | 后端 TDD 实现 | 主线程直接实现 |
| `agents/frontend-dev-agent.md` | 前端实现 | 主线程直接实现 |
| `agents/tester-agent.md` | 分层测试、失败归因 | `agents/verifier-agent.md`（唯一幸存 Agent） |
| `templates/scope.yaml` | 架构契约 + track 派发 | 方案卡"影响范围"一节 |
| `templates/context.json` | Agent 派发运行时上下文 | `task.yaml` 自足（`core/templates/task.yaml`） |

另：`core/orchestrator/worktree_sync.py` 因有测试引用原地标注 deprecated，
未移入本目录。
