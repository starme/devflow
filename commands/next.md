---
description: 从指定 DevFlow task 的断点继续流程
argument-hint: [--task <task-id>]
---

# /devflow next

从指定 task 的断点继续执行。正常推进不依赖本命令；用于会话中断恢复，或 PR 合并后的 done 清理。

## 任务选择

1. 当前目录有 `.devflow/task.yaml` 时，就用这个 task（主工作区 in-place 或后来者 worktree 都一样）。
2. 主仓库执行时支持 `/devflow next --task <task-id>`：先看主仓库 `.devflow/task.yaml`，再用 `discover_tasks` / `git worktree list` 找后来者 worktree。
3. 未指定且存在唯一活动 task 时使用它；多个活动 task 要求明确 `--task`。
4. 旧项目兼容读取 `.devflow/manifest.yaml`，标记 legacy。

## 执行

读 `task.current_phase`，加载 `core/orchestrator/SKILL.md` 在该 task 工作区继续：

| 值 | 行为 |
|---|------|
| `qa` | 继续澄清（feature 走锚定协议）或诊断 |
| `prd_review` | 重新展示漂移聚焦审查，等批准 |
| `plan_review` | 重新展示方案卡，等批准 |
| `working` | 读 card.md 进度清单继续实现；完成后进 GATE-V |
| `deliver_confirm` | 按 `.devflow/delivery.yaml` 幂等恢复：已完成子步骤跳过，重新三合一确认 |
| `done` | 仅当 PR 已合并：清理后来者 worktree（若有）、删本地分支（不删远程）、切回 base_ref。未合并则报告等待 |

产物缺失时重新生成对应产物，不编造内容。

legacy manifest 的旧 phase 就近映射（`gate_prd`→`prd_review`、`gate_arch`/`acceptance`→`plan_review`、`development`/`testing`→`working`），只做 best-effort 提示，不写回旧 manifest；旧任务建议人工收尾。
