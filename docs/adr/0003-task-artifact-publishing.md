# ADR-0003：Task 产物发布与文档命名空间（Task Artifact Publishing）

## 状态

已提议（Proposed）——本 ADR 与 `docs/architecture.md` 一并作为功能方案冻结，待 GATE_ARCH 审批后落地。

## 背景

DEVFLOW 的 task 产物（PRD、架构方案、scope、诊断、测试与验收报告）此前只存在于 task worktree 的 `.devflow/` 目录内。Agent 的 `collect` 机制会把 agent 子任务产物平铺回收进主工作区的 `.devflow/`，但有三个问题：

1. **产物无稳定归宿**：正式 task 的产物没有独立命名空间，随 worktree 清理而消失，无法沉淀为可追溯的项目交付记录。
2. **Agent 回收与正式发布耦合**：agent 子任务的临时产物回收逻辑（`collect`）与正式 task 产物的发布语义混在一起，容易被误当作同一件事。
3. **命名不稳定**：PRD 文件名在不同 task 里都是 `prd.md`，若平铺到同一目录会互相覆盖，无法区分是哪个 task 的哪份 PRD。

本功能补齐「正式 task 产物发布」这一环，与既有 `DELIVERY` 交付闭环衔接。

## 决策

1. **发布与回收分离**：Agent 子任务产物回收（`collect`）继续走 `.devflow/` 平铺路径；正式 task 产物发布（`publish`）是独立能力，由 `DELIVERY` 阶段显式调用 `artifact_publish.py publish`，二者不是同一件事。`collect` 入口增加守卫，跳过 `.devflow-worktrees/` 下的正式 task worktree，避免正式产物被平铺回收。

2. **`docs/tasks/<task-id>/` 命名空间**：正式 task 产物发布到主工作区的 `docs/tasks/<task-id>/` 目录，形成稳定、可追溯的交付记录。每个 task 一个独立子目录，互不覆盖；目录内写入一份 `README.md` 作为来源索引（含 `task_id`/`slug`/`branch`/`base_ref`/`base_commit`/`kind` 及 artifacts 映射，不写绝对 worktree 路径）。

3. **PRD 语义化命名**：PRD 发布为 `prd-<task-slug>.md`（slug 取自 `task.yaml` 的 `task.slug`，仅 `[a-z0-9-]`），其余 artifact（architecture/scope/diagnosis/test-report/acceptance-* 等）保持固定文件名。task worktree 内仍保留原始文件名 `.devflow/prd.md`，只在发布时映射。

4. **幂等 + 拒绝覆盖的冲突策略**：发布前按内容哈希判定——目标不存在则创建（create）；内容哈希相同则跳过（skip，幂等）；内容不同则报告冲突（conflict）并拒绝覆盖，不做「最后写入者获胜」。重复发布天然幂等；已落盘文件保留，不做整体回滚。

5. **方案 A 双路径引用**：`task.yaml` 的 `artifacts` 段采用「worktree 临时路径 + 已发布路径」双路径引用——每个 artifact 既保留 task 内 `.devflow/<name>`，又新增 `docs/tasks/<task-id>/<target>`（PRD 为 `prd-<task-slug>.md`）。只写 task worktree 自己的 `task.yaml`，绝不写项目根 `.devflow/task.yaml`。

## 理由

- **分离关注点**：Agent 回收解决「子任务临时产物归集」，正式发布解决「项目成果沉淀」，二者目标、目标路径、幂等语义都不同，分开实现避免语义回退。
- **目录级命名空间可追溯**：`docs/tasks/<task-id>/` 让每个 task 的成果互不覆盖（两个 task 同名 PRD 也能共存），并提供 `README.md` 来源索引支撑追溯。
- **语义化命名可辨识**：`prd-<task-slug>.md` 让 PRD 文件名自解释，避免多个 `prd.md` 平铺的歧义；其余产物固定名保持简单。
- **幂等 + 拒绝覆盖保证安全**：发布可重试（中断恢复、重复运行 `/devflow next`），又不静默覆盖已有成果，任何冲突都显式暴露给用户决策，符合「不静默破坏」红线。
- **只读探测与写落盘分离**：发布是「读 task worktree 源 + 写主工作区 `docs/` + 写 task worktree `task.yaml`」的混合操作，由 Manager 用 Bash 调用 `publish` 子命令执行，保证落盘能被 PreToolUse hook 审计。

## 否决的替代方案

- **把 publish 并入 agent collect（平铺到 `.devflow/`）**：混淆「子任务临时回收」与「正式成果沉淀」两种语义，PRD 固定名会互相覆盖，且无 `docs/tasks/` 命名空间无法提供稳定追溯。
- **PRD 用固定名 `prd.md`（不语义化）**：多个 task 的 PRD 无法在同一命名空间内区分，需依赖目录名人工辨别，失去自解释性。
- **冲突时「最后写入者获胜」（静默覆盖）**：重跑或并发发布会无提示覆盖已有成果，违背「不静默破坏」红线，无法追溯内容变更。
- **强制迁移单一 manifest（丢弃 worktree 内产物）**：破坏 worktree 内 `.devflow/prd.md` 等既有产物路径，违背「不静默破坏」；方案 A 双路径引用既保留 worktree 内草稿，又补充已发布路径，向前兼容。
- **task.yaml 的 `artifacts` 只写已发布路径（丢弃 worktree 路径）**：交付后 worktree 若未立即清理，缺少 worktree 内路径会让状态展示与调试失去指向；双路径更稳健。

## 适用条件

- 所有 `work_type`（feature / bugfix / chore）在 `DELIVERY` 阶段都走产物发布闭环；PRD 仅在 feature 流程存在，bugfix/chore 无 PRD 时跳过该 artifact。
- 发布目标固定为主工作区 `docs/tasks/<task-id>/`，与 worktree 具体位置解耦（README 索引不写任何绝对 worktree 路径，跨机器可移植）。
- legacy manifest 项目同样适用：正式 task 通过 `task.yaml` 识别（不靠目录名猜测），发布能力与项目新旧无关。