---
description: DevFlow 开始新功能开发
argument-hint: <需求描述>
---

# /devflow start

开始一个新功能的完整开发流程。默认在**主工作区**创建 task 和功能分支；只有主工作区已有未完成 task 时，后来者才进隔离 worktree。

## 前置检查

1. 确认当前目录位于 Git 仓库，并且项目已执行 `/devflow init`。
2. 读取项目级 `.devflow/project.yaml`。只有旧项目时，兼容读取 `.devflow/manifest.yaml`，不覆盖旧流程状态。
3. 主工作区还没有活动 task 时：有已跟踪未提交改动则拒绝，避免把临时修改带进新分支。
4. 主工作区已有活动 task 时：允许再开新 task，后来者进 worktree，不要求主工作区干净。
5. 同一 task 重复 start 才拒绝。

## 创建 task

```text
/devflow start "需求描述" [--base <git-ref>]
```

用统一 task manager（`core/orchestrator/worktree_manager.py` 的 `create_task`）：

1. 生成唯一 `task_id` 和 slug。
2. 默认从当前主分支（或显式 `--base`）解析并固化 `git.base_commit`。
3. 创建唯一分支 `feature/<slug>-<short-id>`。
4. **默认 in-place**：在主仓库 `checkout -b`，写入 `.devflow/task.yaml` 和 `context.json`（含 `project_root`、`repo_root`）。
5. **后来者**：若主仓库已有未完成 `task.yaml`，为新 task 建 `../.devflow-worktrees/<repo>/<task-id>/`，复制 `project.yaml` / `redlines.yaml` / `rules/`，先到的需求不搬家。
6. 向用户报告 task id、branch、工作区路径（主仓库或 worktree）和 base commit。

只读对照主分支（查线上）不要用本命令，用临时 `git worktree add` 或 `git show`。

## 执行

1. `task.kind` 为 `feature`，`current_phase` 为 `classify`。
2. 读取项目分类快照与 capabilities；根据当前需求选择 `workflow.selected_tracks`。低置信度分类先要求确认。
3. 更新该 task 的 `.devflow/context.json`（`task_id`、`run_id`、`project_root`、`repo_root`、`task_root`、工作区路径、`branch`、phase、agent、adapter）。
4. 加载 `core/orchestrator/SKILL.md`，按 `CLASSIFY → PRODUCT_QA → PRD_WRITING → GATE_PRD → ARCHITECTURE → GATE_ARCH → DEVELOPMENT → TESTING → ACCEPTANCE → DELIVERY → DISTILL → DONE` 推进。
5. Gate 阶段暂停等待用户审批。自动阶段由 Stop hook 拦住结束，模型继续用工具干到下一个 Gate，不要提示用户打 `/devflow next`。

研发在该 task 的工作区（主仓库或后来者 worktree）进行。收尾「commit + push + 创建 PR」走一次三合一确认（PR 创建后暂停不自动合并）。PR 合并后再 `/devflow next` 做 DONE 清理。

过程物料（PRD / 方案 / 完成度 / 测试 / 验收）在 **DELIVERY** 归档到 `.devflow/tasks/<task-id>/`，不是每个里程碑都发布。

## 注意

- 需求澄清在当前会话完成，不派 subagent。
- 同一需求的各 Agent 共享该 task 的工作区，cwd 钉在那里，不要再派到 `.claude/worktrees/agent-*` 再 collect。
- 不自动 merge。交付确认通过后才 push 和创建 PR。
- Memorant 不可用时静默降级，不阻塞流程。
