---
description: 从断点继续 DevFlow 流程
---

# /devflow next

从中断处继续执行 DevFlow 流程。

## 执行

1. 读取 `.devflow/manifest.yaml`。
2. 如果 `current_phase` 是 `idle`，提示用户使用 `/devflow start` 或 `/devflow fix` 开始任务。
3. 如果 `current_phase` 是 `done`，显示完成摘要。
4. 加载编排逻辑（`core/orchestrator/SKILL.md`）。
5. 根据当前阶段继续：

| 当前阶段 | 行为 |
|---------|------|
| `classify` | 继续分类确认（如果用户尚未确认） |
| `product_qa` | 继续需求澄清追问 |
| `prd_writing` | 派产品 Agent 写 PRD（自动） |
| `gate_prd` | 提示用户审阅 PRD 并等待批准 |
| `architecture` | 派架构 Agent（自动） |
| `gate_arch` | 提示用户审阅技术方案并等待批准 |
| `development` | 继续派研发 Agent（自动） |
| `testing` | 继续测试/失败路由循环（自动） |
| `acceptance` | 派产品 Agent 验收，或等待用户签字 |
| `distill` | 执行经验蒸馏（自动） |

6. 检查 `.devflow/` 下的产物文件是否完整：
   - 如果阶段已标记 completed 但产物文件缺失，回退该阶段重新执行。
   - 如果阶段是 in_progress 但产物已存在且完整，推进到下一阶段。
7. 自动阶段（prd_writing、architecture、development、testing、distill）无需用户干预，自动继续。
8. Gate 阶段提示用户审批；自动阶段由 Stop Hook 尝试阻止会话结束并继续，若宿主未继续则用户再次运行 `/devflow next`。Stop Hook 已激活时不会重复阻止，避免无限循环。

如果 `$ARGUMENTS` 包含反馈内容（如用户在 Gate 阶段说"通过"或修改意见），将其作为审批输入处理。
