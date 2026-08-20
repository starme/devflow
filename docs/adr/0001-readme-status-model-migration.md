# ADR-0001：项目状态从单 manifest 拆分为 project.yaml + task.yaml

## 状态
已接受（记录现有实现，供 README 与后续文档对齐）

## 背景
早期 DevFlow 用单个 `.devflow/manifest.yaml` 承载项目级配置（分类、workspace、adapter、redlines/rules、Memorant）与需求级状态（current_phase、work_type、prd、测试轮次、产物引用）。随着引入「每个需求独立 git worktree 隔离」的特性，单文件无法区分「仓库长期事实」与「某个需求的运行状态」，多需求并发时互相覆盖。

## 决策
拆分为四类状态文件 + legacy 兼容：

1. `.devflow/project.yaml` —— 项目长期配置，不含当前 phase/描述/分支/PRD。
2. `.devflow/task.yaml` —— 每个 task worktree 一份，含 task id/kind/description、`git.base_ref`/`git.base_commit`、branch/worktree、selected tracks、当前 phase、产物引用。
3. `.devflow/scope.yaml` —— 架构 Agent 为当前 task 生成的范围与契约。
4. `.devflow/context.json` —— 运行时临时上下文（task_id/run_id/phase/agent/cwd/adapter）。
5. `.devflow/manifest.yaml` —— legacy，仅旧项目兼容读取，不删除、不覆盖。

## 理由
- 项目长期事实与需求运行状态解耦，避免并发覆盖。
- 每个 task 独立 worktree 天然匹配独立 `task.yaml`。
- `core/orchestrator/migration.py` 提供幂等迁移，老项目无缝过渡。

## 否决的替代方案
- **继续扩展单 manifest 加并发锁**：锁粒度难定，多 worktree 下状态同步复杂、易脏。
- **删除 legacy manifest 强制迁移**：破坏已有项目，违背「不静默破坏」红线。

## 适用条件
- 新项目 `/devflow init` 直接生成 `project.yaml`；`/devflow start`/`fix` 生成 task worktree 与 `task.yaml`。
- 旧项目存在 `manifest.yaml` 时走 legacy 兼容路径，迁移是幂等、可重复的。
