# 前端项目规则
#
# 此文件由 /devflow init 生成，你可以自由修改。
# 前端研发 Agent 在执行任务前会读取此文件。
#
# 插件内置的前端默认规则（按你 init 时检测到的框架自动加载）：
#   - devflow/rules/frontend/{framework}/*.md
#   - devflow/rules/engineering.md
#
# 你只需要在下面写项目特定的前端约定（补充或覆盖默认规则）。

## 前端技术栈
- 框架：{{FRONTEND_FRAMEWORK}}

## 测试命令
<!--
- 单元/组件测试：npm run test
- Lint：npm run lint
- Type check：npm run typecheck
- Build：npm run build
如果不填，Agent 会自动从 package.json 探测。
-->

## 项目特定约定
<!--
示例：
- 组件放在 src/features/ 下按功能分组
- 状态管理用 Zustand，不用 Redux
- API 调用统一通过 src/api/ 层
- 样式用 Tailwind，不写 CSS 文件
- 提交前必须通过 biome check
-->

## 覆盖默认规则
<!--
如果你不同意内置某条规则，在这里明确声明。
-->
