---
description: 从指定 DevFlow task 的断点继续流程
argument-hint: [--task <task-id>]
---

# /devflow next

从指定 task 的断点继续执行，不读取或修改其他 task 的状态。正常自动阶段不应依赖本命令；本命令用于会话中断后恢复，或 PR 合并后做 DONE 清理。

## 任务选择

1. 当前目录有 `.devflow/task.yaml` 时，就用这个 task（主工作区 in-place 或后来者 worktree 都一样）。
2. 在主仓库执行时，支持 `/devflow next --task <task-id>`；先看主仓库 `.devflow/task.yaml`，再用 `discover_tasks` / `git worktree list` 找后来者 worktree。
3. 未指定 task 且存在唯一活动 task 时使用它；存在多个活动 task 时要求明确 `--task`。
4. 只有旧项目时兼容读取 `.devflow/manifest.yaml`，标记为 legacy，不把其他任务状态写入旧 manifest。

## 执行

读取目标 task 的 `task.current_phase`，加载 `core/orchestrator/SKILL.md`，在该 task 的工作区继续：

| 当前阶段 | 行为 |
|---------|------|
| `classify` | 继续分类确认 |
| `product_qa` | 继续需求澄清 |
| `prd_writing` | 派产品 Agent |
| `gate_prd` | 提示审阅 PRD 并等待批准 |
| `architecture` | 派架构 Agent |
| `gate_arch` | 提示审阅技术方案并等待批准 |
| `development` | 继续派目标 task 的研发 Agent |
| `testing` | 继续测试/失败路由 |
| `acceptance` | 执行目标 task 验收 |
| `delivery` | 交付闭环：探测、三合一确认、commit/push/PR，并把过程物料 publish 到 `.devflow/tasks/<task-id>/`。确认前不要停；等人签字时可以停 |
| `distill` | 执行目标 task 经验蒸馏 |
| `done` | 仅当 PR 已合并：清理后来者 worktree（若有）、删本地分支、切回 `base_ref`。未合并则报告并等待 |

每次阶段转换和 Agent 派发只更新目标 task 的 `task.yaml` 与 `context.json`。Gate 阶段等待用户审批。自动阶段由 Stop hook 续跑到 Gate，不要提示用户再打 `/devflow next`。

`delivery` 的确认点嵌在本阶段内，`current_phase` 不要改成 `gate_delivery`。

> **publish 幂等**：DELIVERY 才归档到 `.devflow/tasks/<task-id>/`。重复执行时内容未变则 skip；内容不同则 conflict，不覆盖。
