---
description: DevFlow 开始新功能开发
argument-hint: <需求描述>
---

# /devflow start

开始一个新功能：锚定 Q&A → PRD → GATE-1 → 方案卡 → GATE-2 → 实现 → GATE-V → GATE-3 交付。

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
4. **默认 in-place**：在主仓库 `checkout -b`，写入 `<project_root>/.devflow/task.yaml`（`current_phase: qa`）。`project_root` 是持有 `.devflow/` 的目录——`create_task` 从 `repo_root` 向上查找最近的 `project.yaml` 并读其 `workspace.root`；找不到时退回 `repo_root`，所以普通项目仍写在自己仓库里。
5. **后来者**：若主仓库已有未完成 `task.yaml`（含写在 `project_root` 的那份），为新 task 建 `../.devflow-worktrees/<repo>/<task-id>/`，复制 `project.yaml` / `redlines.yaml` / `rules/`，先到的需求不搬家。
6. 向用户报告 task id、branch、工作区路径（主仓库或 worktree）和 base commit。

**多仓库（前后端分离）**：`project.yaml` 声明 `workspaces:` 端点列表时，`create_task` 在每个端点仓库建同名分支、各自固化 `base_commit`（记录在 `task.yaml` 的 `git.endpoints`）；交付时每个改动过的端点各开一个 PR。

只读对照主分支（查线上）不要用本命令，用临时 `git worktree add` 或 `git show`。

## 执行

加载 `core/orchestrator/SKILL.md` 按流程契约推进：

1. **qa**：需求锚定协议——冻结原话 → 第一轮核心诉求复述确认 → 填空式追问（每轮展示 running summary，`[推断]` 条目显式确认）→ 写 `.devflow/prd.md`（硬约束见契约）。
2. **prd_review（GATE-1）**：展示漂移聚焦审查（核心诉求复述 + 需求明细表 + 超出原话的条目清单），等用户批准。批准前待确认项必须清零。
3. 写 `.devflow/card.md`（方案要点 / 影响范围 / 风险 / 验收标准表，每条映射 R#）。
4. **plan_review（GATE-2）**：展示方案卡，等用户批准。批准即方案与验收标准冻结。
5. **working**：主线程在该 task 工作区直接实现，勾选 card.md 进度；偏差记录在"偏差"一节。完成后派 `devflow-verifier`（GATE-V），读 `.devflow/verification-report.md`：全 PASS 进 GATE-3；有 FAIL 自己修复重验（连续 3 轮失败停下报告用户）。
6. **deliver_confirm（GATE-3）**：delivery.py 只读探测 + artifact_publish 归档 + 三合一确认（附验证报告摘要与 manual 验收项）→ commit + push + PR。**PR 创建后暂停，永不自动 merge。**
7. **distill**：经验写 Memorant（不可用写 `.devflow/retrospective.md`）。PR 合并后 `/devflow next` 做 done 清理。

## 注意

- 需求澄清在当前会话完成，不派 subagent；唯一派发的 Agent 是 `devflow-verifier`。
- Gate 等人时停；其余阶段直接干到下一个 Gate，不要求用户打 `/devflow next`。
- 不自动 merge。交付确认通过后才 push 和创建 PR。
- Memorant 不可用时静默降级，不阻塞流程。
