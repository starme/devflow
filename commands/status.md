---
description: 显示 DevFlow 项目或 task 状态
argument-hint: [--task <task-id>] [--all]
---

# /devflow status

DevFlow 将项目级配置与 task 状态分开读取。

## 输出范围

- `/devflow status`：当前 worktree 的 task；主仓库只有一个活动 task 时显示它。
- `/devflow status --task <task-id>`：显示指定 task。
- `/devflow status --all`：通过 `git worktree list --porcelain` 发现并汇总全部 DevFlow task worktree。
- 旧项目没有 `project.yaml`/`task.yaml` 时读取 `.devflow/manifest.yaml`，明确标记 `legacy single-manifest`。

## 输出内容

### 项目级（来自 `.devflow/project.yaml`）

1. 项目名称、类别、置信度和证据摘要
2. capabilities、workspace 路径和支持的 adapters
3. redline 能力和 Memorant 状态

### task/分支级（来自目标 worktree 的 `.devflow/task.yaml`）

4. task id、kind、描述、当前阶段和状态
5. branch、worktree、base_ref、固化的 base_commit
6. 当前需求实际启用的 `workflow.selected_tracks`
7. PRD、架构、scope、测试和验收产物
8. 测试轮次、blocked 项和下一步操作

不同 task 的阶段、产物和测试状态必须分别显示，不得从共享 manifest 推断。
