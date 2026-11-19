---
description: 从指定 DevFlow task 的断点继续流程
argument-hint: [--task <task-id>]
---

# /devflow next

从指定 task 的断点继续执行。正常推进不依赖本命令；用于会话中断恢复，或 PR 合并后的 done 清理。

## 任务选择

1. 当前目录有 `.devflow/task.yaml` 时，就用这个 task。
2. 主仓库执行时支持 `/devflow next --task <task-id>`：先看主仓库 `.devflow/task.yaml`，再用 `discover_tasks` 查活动 task 与 `.devflow/tasks/` 归档（含历史遗留 worktree 的只读兼容）。
3. 未指定且存在唯一活动 task 时使用它；多个活动 task 要求明确 `--task`。
4. 旧项目兼容读取 `.devflow/manifest.yaml`，标记 legacy。

## 执行

读 `task.current_phase`，加载 `core/orchestrator/SKILL.md` 在该 task 工作区继续：

| 值 | 行为 |
|---|------|
| `qa` | 继续澄清或诊断 |
| `prd_review` | 旧值，映射到 `plan_review` |
| `plan_review` | 重新展示方案文档，等批准 |
| `working` | 读方案文档进度继续；看缺 QA 还是缺 review，补跑 |
| `deliver_confirm` | 按 `.devflow/delivery.yaml` 幂等恢复：已完成子步骤跳过，重新三合一确认 |
| `done` | 仅当 PR 已合并：**先确认 `.devflow/tasks/<task-id>/task.yaml` 已归档，缺失则补写**（见下）、删本地分支（不删远程）、切回 base_ref。未合并则报告等待 |

产物缺失时重新生成对应产物，不编造内容。

### done 清理的状态归档

in-place 布局下所有 task 共用 `.devflow/task.yaml`，下一个 task 开工时会覆盖它。因此 done 清理必须先把当前状态落进自己的归档目录，否则该 task 的 id / branch / parent 链就只剩 git 历史可查。

复用 `core/orchestrator/task_state.py` 的 `archive_task_state(task_file)`：

- 目标 `.devflow/tasks/<task-id>/task.yaml` 不存在 → 复制当前 `task.yaml` 过去
- 已存在 → 保持原样（正式归档优先于临时快照）
- `task.yaml` 缺失、不可解析或 task id 含路径分隔符 → 跳过并提示，不阻塞清理

`create_task` 在写新状态前也会调用同一个函数兜底，所以即使跳过了这里，上一个 task 仍然可回溯。

legacy manifest 的旧 phase 就近映射（`gate_arch`/`acceptance`→`plan_review`、`gate_prd`→`plan_review`、`development`/`testing`→`working`），只做 best-effort 提示，不写回旧 manifest；旧任务建议人工收尾。
