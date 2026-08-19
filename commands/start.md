---
description: DevFlow 开始新功能开发
argument-hint: <需求描述>
---

# /devflow start

开始一个新功能的完整开发流程。

## 前置检查

1. 检查当前目录是否已执行过 `/devflow init`（`.devflow/manifest.yaml` 是否存在）。
   - 如果不存在，提示用户先运行 `/devflow init`。
2. 读取 `.devflow/manifest.yaml`。
3. 检查 `project.current_phase` 是否为 `idle` 或 `done`。
   - 如果有正在进行的流程，提示用户先用 `/devflow status` 查看，或 `/devflow next` 继续。

## 执行

1. 将用户的需求描述（`$ARGUMENTS`）写入 manifest：
   - `phases.classify.task_description`
   - `project.current_phase: classify`
   - `phases.classify.status: in_progress`
2. 生成 `run_id`（`YYYYMMDD-HHMMSS-xxxxxx`），创建 `.devflow/runs/<run_id>/` 目录，写入 `.devflow/context.json`（包含 run_id、current_phase、current_agent: "manager"、cwd、workspace）。
3. 加载编排逻辑：读取 `core/orchestrator/SKILL.md`。
4. 按 SKILL.md 中"阶段 1：CLASSIFY"开始执行：
   - 初判 work_type 为 `feature`（`/devflow start` 明确是新功能）。
   - 用一句话告诉用户流程预览。
   - 不反对则自动进入 PRODUCT_QA（主线程苏格拉底追问）。
5. 之后按状态机自动流转：PRD_WRITING → GATE_PRD → ARCHITECTURE → GATE_ARCH → DEVELOPMENT → TESTING → ACCEPTANCE → DISTILL → DONE。
6. Gate 阶段暂停等待用户审批；自动阶段结束时 Stop Hook 会阻止会话立即结束，并提示 Manager 继续执行 `/devflow next`。若宿主仍结束会话，用户执行 `/devflow next` 恢复。每次阶段转换和 Agent 派发时更新 context.json。

## 注意

- 需求澄清（Q&A）在当前对话中进行，不派 subagent。
- 所有 Agent 调用使用 Task 工具，subagent name 对应 agents/ 目录下的定义。
- Memorant 不可用时静默降级，不阻塞流程。
