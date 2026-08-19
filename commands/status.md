---
description: 显示 DevFlow 当前状态
---

# /devflow status

读取 `.devflow/manifest.yaml`，展示项目状态。

## 输出内容

1. **项目信息**：名称、工作类型（feature/bugfix/chore）、当前阶段
2. **工作区**：后端路径和技术栈、前端路径和技术栈
3. **阶段进度**：根据 work_type 显示对应的阶段流程
   - feature：classify → product_qa → prd_writing → gate_prd → architecture → gate_arch → development → testing → acceptance → distill → done
   - bugfix/chore：classify → architecture → development → testing → distill → done
   - 已完成 ✓、当前 ►、待执行 ○、跳过 —
4. **开发任务**：
   - 调度了哪些 Agent（后端/前端）
   - 是否并行
   - 任务完成数/总数
   - blocked 任务列表
5. **测试进度**：当前轮次/最大轮次、通过/失败数
6. **产物清单**：PRD、scope、架构文档、测试报告、验收报告的路径
7. **Memorant 状态**：启用/降级、已沉淀记忆数
8. **下一步**：根据当前阶段给出建议操作

格式清晰简洁。如果 manifest 不存在，提示运行 `/devflow init`。
