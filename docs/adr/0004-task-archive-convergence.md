# ADR-0004：任务交付物归档收敛（Task Archive Convergence）

## 状态

已接受（Accepted）——2026-09-04。归档目标 `.devflow/tasks/` 与双根参数已落地。

修订（2026-09-04）：决策第 3 条「各 Gate 里程碑增量发布」被产品口径取代——过程物料**只在 DELIVERY 归档一次**，GATE_PRD / GATE_ARCH / TESTING / ACCEPTANCE 不再 publish。其余决策不变。

## 背景

ADR-0003 将正式 task 产物发布到主工作区的 `docs/tasks/<task-id>/` 命名空间。实际使用暴露出该轨道是**断的**：产物由 `artifact_publish.py` 写到 `docs/tasks/` 后从未被 git 提交，随 worktree 清理散落在工作区无人管；同时归档目标与 task 运行态（`<project_root>/.devflow/`）分处两处，而仓库 `.gitignore` 又整体忽略 `.devflow/`，「产物该去哪、哪条会被提交」两条线互相打架。本任务把归档治理收敛为**单轨、可追溯、不覆盖、独立于 worktree/PR 存亡**的机制。

## 决策

1. **单轨收敛**：正式 task 产物归档目标从 `docs/tasks/<task-id>/` 改为 `.devflow/tasks/<task-id>/`。`docs/tasks/` 轨下线，不再新建；`.devflow/tasks/` 天然 out-of-repo 或 gitignored，机制不做 git 强控（是否入 git 由各仓库 `.gitignore` 自主决定）。

2. **双形态归档根口径（context.json 两字段分离，无启发式）**：`project_root`（= `.devflow/` 所在目录）是**归档根权威源**，`repo_root`（= git 仓库根）是 **worktree 定位权威源**。二者从 `context.json` 的两个独立字段分别推导，不引入存在性探测启发式：
   - `archive_root = project_root/.devflow/tasks`
   - `worktree = repo_root.parent/.devflow-worktrees/<repo_root.name>/<task-id>`
   - 形态 A（`project_root == repo_root`，普通用户项目）归档落在 repo 内；形态 B（`project_root == repo_root.parent`，插件自托管）归档落在 repo 外。两者统一。
   - `artifact_publish` CLI 以 `--root`（= `project_root`）与 `--repo-root`（= `repo_root`）两个参数显式传入；`worktree_manager`/`worktree_sync` 口径不变。

3. **里程碑增量发布 + DELIVERY 补漏**：发布由 Manager 在 GATE_PRD / GATE_ARCH / TESTING / ACCEPTANCE 各里程碑通过后显式触发，DELIVERY 阶段复用同一命令汇总补漏。幂等三态（create/skip/conflict），按内容哈希判定，**拒绝 last-writer-wins**（目标内容不同即 conflict、不覆盖）。缺失产物跳过不强行发布。

4. **实现报告归档**：任务实现报告不是固定清单，由 scope.yaml 的 artifact contract **动态声明**；声明时收敛到固定名 `task-report.md` 以便脚本定位，纳入 `PUBLISHABLE_ARTIFACTS` 与 guard hook `_DEVFLOW_ARTIFACT_FILES` 白名单。

5. **存量迁移**：legacy 引用（`.devflow/agent-plugin-compatibility-prd.md`）迁移 + 留指针文件 + 同步 manifest（`phases.prd_writing.prd_path` / `artifacts.prd` / `phases.architecture.architecture_doc_path`）；历史平铺产物（`PRD-DevFlow.md`、`review-report.md`、`docs/architecture.md`、`docs/delivery-report.md`）按 `legacy-<语义>` 命名迁移，**不伪造 task_id**（伪 id 误导追溯，且违背「task_id 必须由真实 task 唯一生成」契约）。

6. **发布判定零 git 强控**：`.devflow/` 天然 out-of-repo 或 gitignored，归档是否提交由各仓库 `.gitignore` 自主决定，机制不强制、不干扰；兼容「归档被 git 跟踪时单独成 commit」目标（PRD 决策 1/4）。

## 理由

- **断轨修根**：归档落到 `.devflow/tasks/` 后与 task 运行态同处同一权威源（`project_root`），消除「两条线打架」；out-of-repo 或 gitignored 使产物不混入代码交付 commit（与 DELIVERY commit 白名单无冲突）。
- **两个正交权威源显式分离**：归档根（project_root）与 worktree 定位（repo_root）本就是两个独立事实，单一 `--root` 多义参数在形态 B 下会写坏归档位置；从 context.json 两字段显式传入避免了存在性探测在边界/异常态误判。
- **显式增量发布可审计**：里程碑触发 + Manager Bash 执行 + PreToolUse hook 审计，幂等三态保证可重试不破坏，拒绝静默覆盖。
- **声明式实现报告**：不为无稳定内容契约的产物硬造固定清单，同时又给「需要归档的实现报告」一个确定收敛名，兼顾灵活与可定位。
- **引用保护**：迁移留指针 + 同步 manifest，避免挂起引用断链；语义命名不造 id，维持追溯真实性。

## 否决的替代方案

- **保留 `docs/tasks/` 与 `.devflow/tasks/` 双轨并存**：断轨不修，且「产物去哪」仍有歧义，违背「单轨收敛」目标。
- **存在性探测推断形态（检测 `.devflow/` 在 repo 内还是外）**：形态 A/B 判断本身无可靠信号——形态 B 仓库可能因手工补 `repo_root/.devflow/project.yaml` 而「存在」，形态 A 仓库可能因 `.devflow` 被临时删除而「不存在」，探测在边界/异常态误判，且无法解释过渡态。
- **单一 `--root` 多义参数（不拆 project_root/repo_root）**：形态 A 二者相同可混淆，形态 B 二者分离必须拆开，单一参数无法同时表达归档根与 worktree 定位两个正交语义。
- **伪造历史产物 task_id**：误导追溯（「这个 task 并不存在」），语义命名 `legacy-*` 足够区分且不覆盖。
- **把实现报告纳入固定产物清单（不声明即发布）**：为无消费者、无稳定内容契约的产物预设文件名，与声明式契约冲突。

## 对比 ADR-0003 的继承与变更

ADR-0003 的如下原则**全部继承**：分离关注点（collect 与 publish 分开）、目录级命名空间、PRD 语义化命名（`prd-<slug>.md`）、幂等 + 拒绝覆盖的三态冲突策略、task.yaml 双路径引用（worktree + published）、只读探测与写落盘分离、安全复制白名单。

**唯一致变**：目标路径轨从 `docs/tasks/` 收敛到 `.devflow/tasks/`；并由此引入双根参数（`project_root` 归档 / `repo_root` worktree 定位）与里程碑增量发布时序。

## 适用条件

- 所有 `work_type`（feature / bugfix / chore）在各里程碑产生产物时都归档到 `.devflow/tasks/<task-id>/`；feature 的 PRD 仅在 PRD_WRITING 产生。
- 双根参数取自 task worktree 的 `context.json`（`project_root` / `repo_root` 两字段），调用方必须显式传入，不依赖目录存在性推断。
- legacy manifest 项目同样适用：正式 task 通过 `task.yaml` 识别，历史平铺产物由一次性迁移脚本归入 `legacy-*` 语义目录。