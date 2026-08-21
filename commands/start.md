---
description: DevFlow 开始新功能开发
argument-hint: <需求描述>
---

# /devflow start

开始一个新功能的完整开发流程。**每次 start 都创建独立的 DevFlow task 和 Git worktree**；PRD、架构、代码、测试和验收产物都属于同一个 task。

## 前置检查

1. 确认当前目录位于 Git 仓库，并且项目已执行 `/devflow init`。
2. 读取项目级 `.devflow/project.yaml`。只有旧项目时，兼容读取 `.devflow/manifest.yaml`，不覆盖旧流程状态。
3. 检查主工作区是否有未提交修改；默认拒绝把临时修改静默带入新 task。
4. 当前已有其他活动 task 不会阻止新 task；只有同一 task 重复 start 才拒绝。

## 创建隔离 task

在 CLASSIFY 之前执行统一 task manager：

```text
/devflow start "需求描述" [--base <git-ref>]
```

1. 生成唯一 `task_id` 和 slug。
2. 默认从当前主分支（或显式 `--base`）解析并固化 `git.base_commit`。
3. 创建唯一分支 `feature/<slug>-<short-id>`。
4. 创建仓库外 worktree：`../.devflow-worktrees/<repo>/<task-id>/`。
5. 在新 worktree 写入 `.devflow/task.yaml`，记录 task 描述、kind、base_ref/base_commit、branch、worktree。
6. 复制/引用项目级 `project.yaml`、rules 和 redlines；创建 task 专属 `context.json`。
7. 后续 Manager 和 Agent 的 `cwd` 固定为该 task worktree；不要再写主仓库的活动 manifest。

向用户报告 task id、branch、worktree 和 base commit。不同需求即使同时处于 `gate_prd` 或 `development`，也必须分别使用各自 task worktree。

## 执行

1. 将需求描述写入 task 的 `task.description`，将 `task.kind` 设为 `feature`，`current_phase` 设为 `classify`。
2. 读取项目分类快照与 capabilities；根据当前需求选择 `workflow.selected_tracks`。低置信度分类先要求确认。
3. 生成该 task 的 run_id 和 `.devflow/context.json`（包含 `task_id`、`run_id`、`project_root`、`task_root`、`worktree`、`branch`、phase、agent、adapter）。
4. 加载 `core/orchestrator/SKILL.md`，在该 worktree 内按 `CLASSIFY → PRODUCT_QA → PRD_WRITING → GATE_PRD → ARCHITECTURE → GATE_ARCH → DEVELOPMENT → TESTING → ACCEPTANCE → DELIVERY → DISTILL → DONE` 推进。
5. Gate 阶段暂停等待用户审批；自动阶段结束时 Stop Hook 提示 `/devflow next --task <task_id>`。

研发阶段在 task worktree 内按 task 粒度 commit，收尾时统一「commit + push + 创建 PR」走一次三合一交付闭环（PR 创建后暂停不自动合并），交付完成后清理本地 worktree/branch 并切回主分支。

## 注意

- 需求澄清在当前 task 会话完成，不派 subagent。
- 同一需求的各 Agent 默认共享 task worktree；不同需求绝不共享。
- 不自动 merge、push、删除分支或 worktree。
- Memorant 不可用时静默降级，不阻塞流程。
