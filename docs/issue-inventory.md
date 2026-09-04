# DevFlow 问题清单

- 日期：2026-09-04
- 范围：整仓契约与实现，不是单 PR
- 核验：2026-09-04 第四轮——对齐愿景：SKILL/README in-place、distill 后回 delivery、hook 认 payload cwd
- 刻意不改：M3 Guard fail-open；M9 测例保护仅 `development`
- 发布身份：version **1.0.1**，author **starme**

## 核验结论

除 M3、M9 外，清单条目已闭合。

| ID | 核验 | 证据 |
|----|------|------|
| C1 | 完成 | `load_context`：workspace 先 `project.yaml`，phase 先 `task.yaml` |
| C2 | 完成 | `core/templates/context.json` 有 `repo_root`、`workspace` |
| C3 | 完成 | SKILL：pin cwd，禁止 `agent-*` + `collect`；Agent 文案已去「自动回收」 |
| C4 | 完成 | `create_task` 写 `context.json`，后来者复制 `project.yaml` / `redlines.yaml` / `rules/` |
| C5 | 完成 | 自动阶段一直 block；忽略 `stop_hook_active`；理由是干到 Gate，不是 `/devflow next` |
| H1 | 完成 | hook / `next.md` / SKILL 用 `delivery`；`docs/architecture.md` 第四节/五节/六节已改 |
| H2 | 完成 | SKILL 阶段 9：总体 PASS → DELIVERY |
| H3 | 完成 | README / workflow 写 `.devflow/tasks/`。ADR-0003 Superseded，ADR-0004 / ADR-0002 Accepted（DELIVERY 只归档一次） |
| H4 | 完成 | `prepare_worktree` 的 `config_items` 含 `project.yaml` |
| H5 | 完成 | `architect-agent.md` 写 `.devflow/architecture.md` |
| H6 | 完成 | `.agents/plugins/marketplace.json` path 为 `.`，根目录有 `.codex-plugin/`，含 `core/` |
| H7 | 完成 | SKILL CLASSIFY 写 `task.yaml`；Codex AGENTS/README 读 `project.yaml` + `task.yaml` |
| H8 | 完成 | SKILL 阶段 11：只在 PR 已合并后清理 |
| H9 | 完成 | `find_plugin_root` / `_find_core_dir` 按版本号 + mtime 取最新 |
| M1 | 完成 | `find_manifest` 只读，不调用 `migrate_legacy_project` |
| M2 | 完成 | `>` / `tee` / `sed -i` / `cp` / `mv` / `install`；`python -c` 抽引号路径；`git apply`/`patch` 读 `+++` 目标。不上完整 shell 解析 |
| M3 | 刻意保留 | fail-open |
| M4 | 完成 | `start.md`：确认通过后才 push；不自动 merge |
| M5 | 完成 | `docs/architecture.md` 开头有系统总览 |
| M6 | 完成 | Mermaid：DELIVERY → 确认 → DISTILL → DONE；fix 接到 TEST |
| M7 | 完成 | `DELIVERY_ARTIFACT_FILES` 含三份实现报告 |
| M8 | 完成 | SessionStart / UserPrompt / PreCompact / 不迁移 / `project.yaml` workspace 均有测 |
| M9 | 刻意保留 | 仅 `development` 护测例 |
| M10 | 完成 | `devflow-hook.sh` 默认 5.0s |
| M11 | 完成 | `main_root` = `.devflow-worktrees` 的 parent / `<repo.name>` |
| L1 | 完成 | 版本 1.0.1；Claude / Codex / marketplace owner 均为 starme |
| L2 | 完成 | `install.sh` 有 Codex + core 说明 |
| L3 | 完成 | `run_event` 已用于生命周期测；SessionStart 可读 `kind` |

---

## 已确认口径

后续判定「是不是问题」以愿景和这组口径为准。口径变更时，条目归属要重算。

**产品愿景（2026-09-04 校准）**

1. 人只在关键点拍板；中间全自动把一个需求做完并开出 PR。
2. 任意 git 仓库都能编，包括业务应用、Agent Plugin、Skill、MCP、纯文档。
3. 过程物料是交付时的追溯产物：做过哪些任务、方案是什么、完成度如何、测试报告和验收结果。
4. 开发默认在主工作区做当前那一个需求；只有再进来一个会抢工作区的正式任务时，才给后来者建隔离 worktree。只读线上排查不走 DevFlow 隔离。

| 主题 | 决定 |
|------|------|
| 自动阶段 | 干到下一个 Gate（PRD 评审 / 架构评审 / 验收 / 交付确认）。中间不用「继续」，也不用打 `/devflow next` |
| 适用范围 | 任意 git 仓库；`backend` / `frontend` 是可选 track，不是默认必跑 |
| 归档 | 交付阶段产出，落在 `.devflow/tasks/`，用来追溯任务 / 方案 / 完成度 / 测试 / 验收。不是开发中途的主线动作 |
| 隔离 | 默认 in-place：单需求在主工作区的功能分支上做。第二个会改文件的正式任务（如做到一半的 `/devflow fix`）给后来者建 worktree，先到的不搬家。只读对照主分支用临时 git worktree 或 `git show`，不开 DevFlow 任务。`create_task()` 已按此实现 |
| GATE_DELIVERY | 不是独立 `current_phase`，只是 DELIVERY 内的确认点 |
| 清理 | PR 合并后用 `/devflow next` 进入 DONE，才删本地隔离区 / 本地分支并切回 `base_ref` |
| 宿主 | Claude Code 是产品主宿主；Cursor 只是开发本插件的 IDE |
| Codex | 安装后也要能跑 `init` / `start` / `status` / `next` 以及 `delivery.py`、`artifact_publish.py` 等 core 脚本 |

## 已移出清单

| 原先条目 | 移出原因 |
|----------|----------|
| Cursor 无适配层 | Cursor 不是产品宿主 |
| `start.md` / `fix.md` 未把 GATE_DELIVERY 写成独立阶段 | 它本来就不是独立 phase |

---

## 历史条目（原文保留）

以下 Critical / High / Medium / Low 是 2026-09-04 盘点原文，**不是当前未修复清单**。当前状态见文首核验表。

---

## Critical

### C1. `load_context` 只读 `manifest.yaml`

- 位置：`core/hooks/devflow_guard_common.py`（`load_context`、`_parse_manifest_workspace`、`_parse_manifest_phase`）
- 观察：`/devflow init` 只写 `project.yaml`；`create_task()` 只把 `project.yaml` 拷进 task worktree。guard 仍硬编码 `.devflow/manifest.yaml` 补 workspace 和 phase。
- 影响：新 task 上 `infer_track` 为空，`is_within_boundary` fail-open。目录边界和开发期测例保护可能完全不生效。

### C2. `context.json` 模板缺 `repo_root` 与 `workspace`

- 位置：`core/templates/context.json`；对照 ADR-0004、`core/orchestrator/SKILL.md`、`adapters/README.md`
- 观察：模板只有 `project_root`。双根发布和 guard 的 workspace 回退没有权威字段。
- 影响：Manager 按模板生成 context 时，`artifact_publish` 的 `--root` / `--repo-root` 对不上，guard 也补不齐 workspace。

### C3. SKILL 仍按 `agent-*` + `collect` 编排

- 位置：`core/orchestrator/SKILL.md`（产物回收）；`agents/*.md`（写相对路径、等 Manager 回收）
- 观察：口径是共享外部 task worktree，且派发 pin cwd。SKILL 仍要求每次 Task 后 `worktree_sync.py collect` 扫描 `.claude/worktrees/agent-*`，并显式跳过 `.devflow-worktrees`。
- 影响：专职 Agent 被写进隔离 worktree，产物不在 task 权威目录。

### C4. `create_task()` 未准备 rules / redlines / `context.json`

- 位置：`core/orchestrator/worktree_manager.py`；对照 `commands/start.md`
- 观察：`start.md` 要求复制 `project.yaml`、rules、redlines 并写 `context.json`。实现只 `mkdir`、复制 `project.yaml`、写 `task.yaml`。
- 影响：新 task worktree 缺红线与运行时上下文。

### C5. 自动阶段无法干到 Gate（物料保存上线后的回归）

- 位置：`hooks/devflow_hook.py` 的 `handle_stop`；`commands/start.md`、`commands/next.md`、`core/orchestrator/SKILL.md`
- 观察：
  1. 原需求是自动阶段一直跑到 Gate。
  2. 隔离 task + 产物发布（PR #7/#8，「规划过程物料保存」）把 `current_phase` 从 `manifest.yaml` 挪到 `task.yaml`。当时 hook 只认 `manifest.yaml` / `project.yaml`。worktree 里有 `project.yaml`、没有 phase，得到 `unknown`，不进 `auto_phases`，模型一停就被放行。
  3. `ae2eb05` 让 hook 能读 `task.yaml`，但续跑合同写成：拦一次，理由是「去跑 `/devflow next`」，第二次 `stop_hook_active` 放行。提交说明的目标也是 prompting `/devflow next`，不是干到 Gate。
  4. 拦截理由只进模型上下文，用户对话里看不见，表现为「说完下一批计划就停」。
- 影响：自动阶段被切成「单次轻推 + 等人喊继续」。临场修 bug 只要仓库里还是自动阶段，也会套这套逻辑。
- 体感对话：模型读几个文件 → 宣布下一步 → 停；用户说「继续干活」→ 再读一个 → 再停。不是报错。

---

## High

### H1. 多处把 `gate_delivery` 当成独立 phase

- 位置：`hooks/devflow_hook.py` 的 `gate_phases`；`commands/next.md` 恢复表；`core/orchestrator/SKILL.md` 中断恢复
- 观察：口径是 `current_phase` 保持 `delivery`。hook / next / SKILL 仍列出 `gate_delivery`。
- 影响：Stop / UserPrompt 按不会出现的 phase 名判断；恢复表等人一个不存在的阶段。

### H2. SKILL 验收段跳过 DELIVERY

- 位置：`core/orchestrator/SKILL.md` 阶段 9 vs 阶段 9.5
- 观察：阶段 9 写「总体 PASS → 进入 Distill」；阶段 9.5 才定义 DELIVERY。
- 影响：验收通过后可能直接蒸馏，不走 commit / push / PR。

### H3. 归档文档仍写 `docs/tasks/`，ADR-0004 仍标 Proposed

- 位置：`README.md`、`README.zh-CN.md`、`docs/workflow.md`、`docs/adr/0003-task-artifact-publishing.md`、`docs/adr/0004-task-archive-convergence.md`
- 观察：代码和 `test_artifact_publish.py` 已断言归档只在 `.devflow/tasks/`，不再创建 `docs/tasks/`。
- 影响：用户和 Manager 按文档找归档会落空。

### H4. `prepare_worktree` 复制 `manifest.yaml`，不复制 `project.yaml`

- 位置：`core/orchestrator/worktree_sync.py` 的 `config_items`
- 观察：复制清单是 `manifest.yaml`、`redlines.yaml`、`rules`、`contracts`。pin-cwd 模型下这条路径本身也是残留。
- 影响：即便仍被调用，新项目也缺 `project.yaml`。

### H5. 架构文档落点不一致

- 位置：`agents/architect-agent.md` vs `core/orchestrator/delivery.py`、`core/hooks/devflow_guard_common.py` 白名单
- 观察：架构 Agent 写 `docs/architecture.md`；发布和交付认 `.devflow/architecture.md`。
- 影响：GATE_ARCH 发布和 DELIVERY 提交可能找不到架构文档。

### H6. Codex 包不含 core 脚本

- 位置：`.agents/plugins/marketplace.json` → `plugins/devflow/`
- 观察：该目录无 `core/`、`commands/`、`hooks/`。口径是 Codex 也要能跑命令和脚本。
- 影响：只装 Codex 入口时，init/start 与 delivery/publish 不可用。

### H7. SKILL CLASSIFY 与 Codex 文档仍以 `manifest.yaml` 为状态源

- 位置：`core/orchestrator/SKILL.md` 阶段 1；`adapters/codex/AGENTS.md`、`adapters/codex/README.md`
- 观察：新布局的权威源是 `project.yaml` + `task.yaml`。
- 影响：新任务状态被写回共享 manifest，或 Codex 读不到 `task.yaml`。

### H8. SKILL 把清理写在 PR 创建之后立刻做

- 位置：`core/orchestrator/SKILL.md` 阶段 11 DONE
- 观察：口径是 PR 合并后 `/devflow next` 才清理。`delivery.yaml` 却已有 cleanup 字段。
- 影响：未合并就删本地 worktree / branch。

### H9. 插件根 glob 无版本排序

- 位置：`hooks/devflow_hook.py` 的 `find_plugin_root`；`core/hooks/devflow_guard_common.py` 的 `_find_core_dir`
- 观察：遍历 `~/.claude/plugins/cache/*/devflow/*`，返回第一个目录命中。
- 影响：多版本缓存时可能加载旧插件。

---

## Medium

### M1. `find_manifest` 每次命中 legacy 都跑迁移

- 位置：`hooks/devflow_hook.py` 的 `find_manifest`
- 观察：SessionStart / Stop / UserPrompt / PreCompact 都会走；`MigrationConflict` 被外层 `except` 吞掉。
- 影响：生命周期 hook 带写副作用；与默认 1 秒超时叠加时静默 fail-open。

### M2. Bash 写路径检测覆盖面窄

- 位置：`core/hooks/devflow_guard_common.py` 的 `_extract_shell_write_targets`
- 观察：只匹配 `>` / `tee` / `sed -i`。无 `cp`、`mv`、`python -c`、`git apply`。
- 影响：Bash 可绕过 forbidden / protected / boundary。

### M3. Guard 大面积 fail-open

- 位置：`core/hooks/redline-guard.py`；`is_within_boundary`
- 观察：任意异常 allow；边界判断异常返回 True；找不到 `.devflow` 则完全透明。
- 影响：与 C1 叠加后，新布局解析失败等于没防护。这是既有设计取舍，不是新引入的，但后果变大了。

### M4. `start.md` 同时要求 push 又禁止自动 push

- 位置：`commands/start.md`（收尾三合一 vs 「注意」里的不自动 push）
- 观察：同一命令文件给出相反约束。
- 影响：Manager 不知道交付时该不该 push。

### M5. `docs/architecture.md` 实际是交付方案

- 位置：`docs/architecture.md`；`README.md` 链到「Architecture notes」
- 观察：正文是 Delivery Lifecycle 技术方案，不是系统架构总览。
- 影响：按 README 找不到架构说明。

### M6. `workflow.md` Mermaid 与正文不一致

- 位置：`docs/workflow.md`
- 观察：图是 `DELIVERY → Gate → DONE`，蒸馏画在 DONE 之后；fix 子图没有交付。正文是 `DELIVERY → GATE_DELIVERY → DISTILL → DONE`。
- 影响：读者看到的阶段顺序与状态机正文不同。

### M7. `DELIVERY_ARTIFACT_FILES` 缺实现报告

- 位置：`core/orchestrator/delivery.py` vs `core/hooks/devflow_guard_common.py` 的 `_DEVFLOW_ARTIFACT_FILES`
- 观察：guard 有 `task-report.md` / `backend-task-report.md` / `frontend-task-report.md`；delivery 白名单没有。
- 影响：实现报告可能被排除在交付提交之外。

### M8. 新布局与生命周期 hook 测试缺口

- 位置：`core/tests/test_devflow_hook.py`、`core/tests/test_redline_guard.py`
- 观察：有 Stop（legacy + task.yaml）；无 SessionStart / UserPrompt / PreCompact。guard fixture 全用 manifest，无 `project.yaml` workspace。工作区未提交 diff 里有未使用的 `run_event`。
- 影响：C1 / C3 / C5 / H1 不会被现有单测拦住。

### M9. 测例保护只在 `development` 阶段生效

- 位置：`core/hooks/redline-guard.py`
- 观察：仅 `phase == "development"` 时拦截改已有测试。
- 影响：失败路由或 phase 未改回时，保护不生效。

### M10. lifecycle hook 默认 1 秒，PreToolUse 5 秒

- 位置：`hooks/devflow-hook.sh` 的 `DEVFLOW_HOOK_TIMEOUT_SECONDS`；`.claude-plugin/plugin.json`
- 观察：迁移或慢盘时容易超时。
- 影响：超时走 fail-open，C5 的续跑和红线都会静默消失。

### M11. `detect_worktree` 对 task worktree 的 `main_root` 不是 git 根

- 位置：`core/hooks/devflow_guard_common.py` 的 `detect_worktree`
- 观察：沿父目录找到 `.devflow-worktrees` 后，`main_root` 取其 parent，不是 `repo_root`。
- 影响：路径映射在嵌套或形态 B（插件自托管）下难推理。

---

## Low

### L1. 版本、作者、产品描述不一致

- 位置：`.claude-plugin/plugin.json`、`plugins/devflow/.codex-plugin/plugin.json`、`adapters/codex/adapter.toml`
- 观察：Claude 侧 author `tal`、描述仍写全栈应用；Codex 侧 author `starme`、自适应描述；`adapter.toml` version `0.1`。
- 影响：对外身份分裂。

### L2. `install.sh` 只写 Claude 安装

- 位置：`install.sh`
- 观察：无 Codex marketplace，也无「Codex 也要有 core」的说明。
- 影响：Codex 用户按脚本装不齐能力。

### L3. 当前分支 hook 改动未完成

- 位置：工作区未提交的 `hooks/devflow_hook.py`、`core/tests/test_devflow_hook.py`
- 观察：分支 `fix/stop-hook-task-yaml-memorant` 已提交 ae2eb05；未提交部分增加了 `read_work_type`，测试里增加了未使用的 `run_event`。
- 影响：SessionStart 的 `kind` 已可读，对应测试未落地。这是 WIP，不是仓内已合并缺陷。

---

## 统计

| 严重度 | 条数 | ID |
|--------|------|-----|
| 已闭合 | 26 | C1–C5、H1–H9、M1–M2、M4–M8、M10–M11、L1–L3 |
| 刻意保留 | 2 | M3 fail-open；M9 仅 development 护测例 |
| 已移出 | 2 | Cursor 适配；GATE_DELIVERY 独立 phase |
