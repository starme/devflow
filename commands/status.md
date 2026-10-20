---
description: 显示 DevFlow 项目或 task 状态
argument-hint: [--task <task-id>] [--all]
---

# /devflow status

## 输出范围

- `/devflow status`：当前 worktree 的 task；主仓库只有一个活动 task 时显示它。
- `/devflow status --task <task-id>`：显示指定 task。
- `/devflow status --all`：通过 `git worktree list --porcelain` 发现并汇总全部 DevFlow task worktree。
- 旧项目没有 `project.yaml`/`task.yaml` 时读取 `.devflow/manifest.yaml`，明确标记 `legacy single-manifest`。

## 输出内容

### 项目级（`.devflow/project.yaml`）

1. 项目名称、类别、capabilities、workspace 路径、adapter 与 redline 能力、Memorant 状态

### task 级（目标 worktree 的 `.devflow/task.yaml`）

2. task id、kind、描述、`current_phase`（qa / prd_review / plan_review / working / deliver_confirm / done）
3. branch、worktree、base_ref、固化 base_commit
4. 产物（区分工作区草稿与已归档 `.devflow/tasks/<task-id>/` 两个路径，已发布与未发布明确区分）：
   - PRD：`.devflow/prd.md`（归档名 `prd-<task-slug>.md`）
   - 方案卡：`.devflow/card.md`（含进度勾选与偏差记录）
   - 验证报告：`.devflow/verification-report.md`（含各轮结论）
   - 交付状态：`.devflow/delivery.yaml`（commit、pushed、remote、PR URL、清理状态）
5. 验证结论摘要（最近一轮 overall 与 FAIL / SKIP / MANUAL 数）与下一步操作

不同 task 的状态必须分别显示，不得从共享文件推断。
