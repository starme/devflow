# 后端项目规则
#
# 此文件由 /devflow init 生成，你可以自由修改。
# 后端研发 Agent 在执行任务前会读取此文件。
#
# 插件内置的后端默认规则（按你 init 时检测到的语言/框架自动加载）：
#   - devflow/rules/backend/{lang}/code-style.md
#   - devflow/rules/backend/{lang}/api.md
#   - devflow/rules/backend/{lang}/testing.md
#   - devflow/rules/backend/{lang}/security.md
#   - devflow/rules/engineering.md
#
# 你只需要在下面写项目特定的后端约定（补充或覆盖默认规则）。

## 后端技术栈
- 语言：{{BACKEND_LANG}}
- 框架：{{BACKEND_FRAMEWORK}}
- 数据库：{{DATABASE}}

## 测试命令
<!-- 告诉 Agent 怎么跑测试，例如：
- 单元测试：go test ./...
- 集成测试：go test -tags=integration ./...
- Lint：golangci-lint run
如果不填，Agent 会自动探测。
-->

## 项目特定约定
<!--
示例：
- 使用 testify 断言，不用标准 testing 包的 if 判断
- 错误统一用 pkg/errors 包装
- 数据库迁移文件放在 migrations/ 目录
- 不使用 ORM，手写 SQL
-->

## 覆盖默认规则
<!--
如果你不同意内置某条规则，在这里明确声明，例如：
- 覆盖：内置规则要求函数不超过 50 行，但本项目允许 handler 最长 80 行
-->
