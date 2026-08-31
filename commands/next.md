---
description: 从指定 DevFlow task 的断点继续流程
argument-hint: [--task <task-id>]
---

# /devflow next

从指定 task 的断点继续执行，不读取或修改其他 task 的状态。

## 任务选择

1. 在当前 task worktree 中执行时，读取 `.devflow/task.yaml` 和 `.devflow/context.json`。
2. 在主仓库执行时，支持 `/devflow next --task <task-id>`；通过 `git worktree list --porcelain` 找到该 task worktree。
3. 未指定 task 且存在唯一活动 task 时使用它；存在多个活动 task 时要求明确 `--task`。
4. 只有旧项目时兼容读取 `.devflow/manifest.yaml`，标记为 legacy，不把其他任务状态写入旧 manifest。

## 执行

读取目标 task 的 `task.current_phase`，加载 `core/orchestrator/SKILL.md`，仅在目标 worktree 继续：

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
| `delivery` | 继续交付闭环：探测 + 三合一确认 + commit/push/PR + 产物 publish 到 `docs/tasks/<task-id>/` |
| `gate_delivery` | 提示三合一确认（commit+push+PR）并等待签字 |
| `distill` | 执行目标 task 经验蒸馏 |
| `done` | 显示完成摘要和 branch/worktree，返回主仓库 / 清理本地 worktree |

每次阶段转换和 Agent 派发只更新目标 task 的 `task.yaml` 与 `context.json`。Gate 阶段（含 `gate_delivery`）等待用户审批；自动阶段（含 `delivery`）停止时提示再次运行 `/devflow next --task <task-id>`。

> `delivery` 是 DELIVERY 交付闭环的自动阶段（prompt 继续执行），`gate_delivery` 是其中的人工三合一确认点（等待签字），二者语义不同：不要把 `gate_delivery` 当作自动继续。

> **publish 幂等**：产物发布（publish 到 `docs/tasks/<task-id>/`）是幂等操作——重复执行时，已归档产物内容未变则跳过（skip），不会重复生成或覆盖；只有内容不同才报告冲突并要求人工处理。因此中断恢复或重复运行 `/devflow next --task <task-id>` 是安全的。
