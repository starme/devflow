---
description: 显示 DevFlow 当前状态
---

# /devflow status

读取 `.devflow/manifest.yaml`，展示项目状态。

## 输出内容

1. **项目信息**：名称、项目类别、分类置信度、工作类型（feature/bugfix/chore）、当前阶段
2. **识别结果**：检测到的 capabilities、分类证据摘要、候选类别（如有）
3. **工作区**：后端/前端路径和技术栈（如存在），以及 plugin/skill/agent/hook/MCP 相关路径（如存在）
4. **生命周期轨道**：读取 `workflow.tracks`，按类别显示实际启用的阶段；不要默认展示不适用的 backend/frontend 轨道
5. **阶段进度**：
   - 传统应用：classify → product_qa → prd_writing → gate_prd → architecture → gate_arch → development → testing → acceptance → distill → done
   - AI Agent / Plugin / Skill / MCP：classify → product_qa → prd_writing → gate_prd → architecture → gate_arch → selected implementation tracks → evaluation/testing → acceptance → distill → done
   - bugfix/chore：按类别裁剪阶段
   - 已完成 ✓、当前 ►、待执行 ○、跳过 —
6. **开发任务**：调度了哪些 Agent/track、边界、是否并行、任务完成数/总数、blocked 任务
7. **测试进度**：当前轮次/最大轮次、通过/失败数
8. **产物清单**：PRD、scope、架构文档、契约、评估报告、测试报告、验收报告的路径
9. **适配层**：平台名称、hard/soft 能力、已验证能力；Codex 的 soft 限制必须明确显示
10. **Memorant 状态**：启用/降级、已沉淀记忆数
11. **下一步**：根据类别、轨道和当前阶段给出建议操作

格式清晰简洁。如果 manifest 不存在，提示运行 `/devflow init`。
