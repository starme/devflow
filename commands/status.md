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

2. task id、kind、描述、`current_phase`（qa / plan_review / working / deliver_confirm / done；旧值 `prd_review` 按 `plan_review` 显示）
3. branch、worktree、base_ref、固化 base_commit
4. 产物（区分工作区草稿与已归档 `.devflow/tasks/<task-id>/` 两个路径，已发布与未发布明确区分）：
   - 方案文档：`.devflow/plan.md`（需求 + 备选方案 + 验收标准 + 踩坑 + 待办支线 + 偏差）
   - 旧任务兼容：`.devflow/prd.md` / `.devflow/card.md`（归档名 `prd-<task-slug>.md` / `card.md`）
   - 验证报告：`.devflow/verification-report.md`（含各轮结论）
   - 审查报告：`.devflow/review-report.md`（high / medium / low 分级）
   - 交付状态：`.devflow/delivery.yaml`（commit、pushed、remote、PR URL、清理状态）
5. 验证与审查摘要（最近一轮 overall、FAIL / SKIP / MANUAL 数、review 各等级条数）与下一步操作

   review 的条数**必须**来自 `core/orchestrator/task_summary.py`，不要自己数。
   **两个路径都要传**——任务归档后报告在归档目录，只查工作区会误报「未审查」：

   ```bash
   python3 "$CLAUDE_PLUGIN_ROOT/core/orchestrator/task_summary.py" \
     --report <worktree>/.devflow/review-report.md \
     --report <project_root>/.devflow/tasks/<task-id>/review-report.md
   ```

   按顺序取第一个存在的报告。它的四种输出要原样呈现，**不可改写**：

   - `review: 未审查` —— 两个路径都没有报告
   - `review: 报告无法读取（文件存在但打不开，检查权限）` —— 存在但读不了，**不是「未审查」**
   - `review: 报告存在但无法解析（有分节，但没有可识别的 finding 条目）` ——
     **不能显示成 0 条**；「没解析到」和「没有问题」是两件事
   - `review: N high / N medium / N low` —— 正常计数

不同 task 的状态必须分别显示，不得从共享文件推断。
