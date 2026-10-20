# ADR-0005: 编排层校准——从多 Agent 编排退到意图锚定与验证守门

- 状态：已采纳（2026-10-20）
- 关联：ADR-0002（交付生命周期）、ADR-0003（产物发布）、ADR-0004（归档收敛）

## 背景

DevFlow v1.x 的价值假设是"模型需要被管"：5 个专职 Agent 分工、14 阶段状态机、
Stop hook 强制续跑、scope.yaml 中间契约、失败路由 3 轮循环。随着模型能力提升，
这些机制补偿的弱点（上下文预算不足、中途弃疗、跨角色传参出错）已基本消失，
而维护成本开始超过防住的错误——Stop hook 误拦（2026-09 事故）是第一个实证。

同时被证伪的还有反向假设："主线程 Q&A 足以锚定产品意图"。实际观察：简单描述
的需求经过反复追问后会偏离原始诉求，且不产生清晰的产品文档。意图捕获是当前
最弱、最该加重的环节。

## 决策

校准原则：**编排按模型能力裁剪，意图与验证按信任保留。**

### 退役（能力补偿型）

| 退役项 | 替代 |
|---|---|
| product / architect / backend-dev / frontend-dev / tester 五个 Agent | 主线程直接执行；Agent 定义移入 `legacy/agents/` |
| scope.yaml 中间契约 + track 派发 | 方案卡（card.md）的"影响范围"一节；模板移入 `legacy/templates/` |
| Stop hook 强制续跑（`decision: block`） | 删除 Stop 事件注册；模型自然连续工作 |
| 失败路由 3 轮循环（suggested_agent 归因） | 主线程自己修，修完重验 |
| context.json 运行时上下文 | task.yaml 自足；模板移入 `legacy/templates/` |
| bugfix/chore 阶段裁剪规则表 | 统一方案卡的瘦版（fix 天然走 lite 路径） |
| task.yaml 的 workflow.selected_tracks / project_snapshot 段 | 方案卡承载 |

`worktree_sync.py` 原地标注 deprecated（有测试引用，物理移除待逐项确认）。

### 保留（授权与记忆型，不动）

- redline-guard（PreToolUse 硬拦截）与 audit-log：安全边界，与流程正交
- delivery.py 三合一交付 + PR 永不自动 merge
- artifact_publish.py 归档（白名单新增 card.md / verification-report.md，legacy 名保留供旧任务）
- Memorant 召回/蒸馏（按 Agent 的权限矩阵退役，主线程统一调用）
- worktree_manager（create_task / 后来者隔离 / 多仓库端点；兼作超大任务的手动分段逃生舱）

### 加重（意图与验证型，新投入）

1. **需求锚定协议**（qa 阶段，强制）：
   - 原话逐字冻结进 PRD 第 1 节，永不改写；第一轮复述核心诉求并获确认
   - 填空式提问（只补核心诉求的缺口），禁止加法式提问；模型想补充的只能以
     `[推断]` 条目存在，显式确认前不得进入需求
   - 每轮 Q&A 更新并展示 running summary；GATE-1 展示"超出原话的条目清单"
     （漂移聚焦审查），而非 PRD 全文
2. **PRD 硬约束**：≤1.5 页；每条需求标注来源（原话 / Q&A·R\<N\> / 推断·已确认）；
   GATE-1 前待确认项清零；非目标必填
3. **可执行验收标准**：方案卡验收表分 cmd / ai / manual 三类，每条映射 R#，
   在 GATE-2 被人批准后冻结——"怎么算做完"从主观验收转为证据链
4. **devflow-verifier**：唯一幸存 Agent（从 tester 改造）。只测不改、无证据不得
   PASS；以干净上下文独立验证，不吃实现者的合理化锚定

### 新状态机

`task.current_phase` 收敛为 6 值（字段名保留以兼容既有解析器）：
`qa → prd_review → plan_review → working → deliver_confirm → done`
（fix/chore 跳过 prd_review）。只用于提示注入，**hook 永不拦截**。

人工触点 5 → 4：Q&A、GATE-1（PRD 漂移聚焦审查）、GATE-2（方案 + 验收标准）、
GATE-3（交付三合一，附验证报告与 manual 项；原"验收签字"并入）。

追溯链：**原话 → R# → 验收标准 A# → verifier 证据**——用证据链替代流程完整性。

## 后果

- 编排规范文本 ~1730 行 → 800 行内；每需求 subagent 上下文重建 5 次 → 1 次
- Stop hook 误报类别归零（block 逻辑整体删除，而非修补）
- plugin.json 版本升至 2.0.0（破坏性：Agent 名、phase 值、scope.yaml 契约变更）
- 旧 `.devflow/manifest.yaml` 项目：hook 只读兼容提示；旧任务建议人工收尾
- 超大任务（30+ 文件）的主线程上下文压力：worktree_manager 保留作手动分段逃生舱
- codex adapter 未随本轮调整（router 模拟 Task 调度的简化是后续任务）
- 不删除任何文件：五份 Agent 定义与 scope/context 模板移入 `legacy/`，
  物理删除待逐项确认

## 验证

本 ADR 的落地任务（orchestration-recalibration-f39c2e）即新流程的第一个 dogfood：
其 PRD 与方案卡按 v2 模板撰写，GATE-1 / GATE-2 于 2026-10-20 对话中获用户批准，
验收标准即"后果"一节的量化指标。
