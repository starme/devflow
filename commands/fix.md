---
description: Bug 修复模式 — 定位→范围判定→修复→回归测试→记忆
argument-hint: <bug 描述>
---

# /devflow fix

Bug 修复 / 日常维护模式。不走完整产品流程，由架构 Agent 定位根因并输出 scope，再派对应研发 Agent 修复，最后测试 Agent 回归验证。

## 前置检查

1. 检查 `.devflow/manifest.yaml` 是否存在。不存在则提示先运行 `/devflow init`。
2. 读取 manifest。
3. 检查是否有正在进行的流程。如果有，提示用户先完成或用 `/devflow next` 继续。

## 执行

1. 将 bug 描述（`$ARGUMENTS`）写入 manifest：
   - `project.work_type: bugfix`
   - `project.current_phase: classify`
   - `phases.classify.task_description`
   - `phases.classify.detected_type: bugfix`
   - `phases.classify.status: completed`
   - `phases.classify.user_confirmed: true`

2. 生成 `run_id`（`YYYYMMDD-HHMMSS-xxxxxx`），创建 `.devflow/runs/<run_id>/` 目录，写入 `.devflow/context.json`（包含 run_id、current_phase、current_agent: "manager"、cwd、workspace）。

3. 加载编排逻辑：读取 `core/orchestrator/SKILL.md`。

4. 按精简流程执行（跳过 PRODUCT_QA、PRD_WRITING、GATE_PRD、GATE_ARCH、ACCEPTANCE）：

   **ARCHITECTURE（诊断模式）**
   - 派 `devflow-architect`，`mode: diagnosis`
   - 传入 bug 描述/错误堆栈、workspace 路径
   - 架构 Agent 读代码定位根因，输出：
     - `.devflow/diagnosis.md`（根因分析）
     - `.devflow/scope.yaml`（范围判定：涉及哪个 track、改哪些文件、怎么修）
   - **不经过 Gate**，scope 确认后直接进入开发

   **DEVELOPMENT**
   - 读 scope.yaml 的 tracks
   - 只涉及后端 → 只派 `devflow-backend-dev`
   - 只涉及前端 → 只派 `devflow-frontend-dev`
   - 两边都涉及 → 按 scope 的 parallelizable 决定并行或串行
   - 任务描述中包含：根因分析、修复要点、affected_files、boundary
   - 研发 Agent 必须先写能复现该 bug 的回归测试，再修复

   **TESTING**
   - 派 `devflow-tester`，针对性地跑回归测试
   - 失败则按失败路由循环（最多 3 轮）
   - 通过则进入 Distill

   **DISTILL**
   - 写入结构化 bug 记忆：根因 + 修复方式 + 回归测试点
   - Memorant 不可用则写 docs/retrospective.md

4. bugfix 不做正式产品验收。测试通过后向用户报告：根因、修复文件、回归测试结果。

## 规则

- 架构 Agent 在诊断模式下只分析不改代码
- 修复必须针对根因，不能只压制症状（不吞异常、不加无意义的 try-catch）
- 每次修复必须有回归测试（纯文档/配置改动除外）
- 3 轮测试仍失败则停止并报告用户
- Memorant 不可用时静默降级
