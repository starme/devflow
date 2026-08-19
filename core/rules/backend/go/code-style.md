---
description: Go 代码风格规范
paths: ["**/*.go"]
alwaysApply: false
---

# Go 代码风格规范

适用于所有 Go 代码，与框架无关。

---

## 1. 命名规范

* 变量/参数：camelCase
* 导出标识符：PascalCase
* 包名：全小写，单词，无下划线
* 禁止无意义命名（a、b、tmp、data、info）
* 常量：全大写 + 下划线（SCREAMING_SNAKE）或 PascalCase（语义型）

---

## 2. 函数/方法结构

* 单个函数 ≤ 50 行
* 单一职责原则
* 禁止嵌套超过 3 层
* 优先 early return，减少 else

```go
// ✅ 推荐
if err != nil {
    return nil, err
}
// 继续主流程

// ❌ 禁止
if err == nil {
    // 主流程嵌套在这里
}
```

---

## 3. 错误处理

```go
// ✅ 标准模式
if err != nil {
    return nil, fmt.Errorf("描述操作: %w", err)
}
```

禁止：
* 忽略 error（`_ = someFunc()`）
* 用 panic 代替错误处理（初始化阶段除外）
* 裸 `return err`，不加上下文

---

## 4. 注释规范

* 所有导出函数/类型必须有 GoDoc 注释
* 注释以标识符名开头：`// FuncName does xxx`
* 禁止注释重复代码内容（注释说 why，代码说 what）

---

## 5. 日志

* 使用结构化日志（`log/slog` 或框架提供的结构化 logger）
* 禁止 `fmt.Println` / `fmt.Printf` 输出日志
* 日志字段必须语义化，禁止裸字符串拼接

```go
// ✅
logger.Info("user login", "userId", userId)

// ❌
fmt.Println("user login: " + userId)
```

---

## 6. 并发

* goroutine 必须通过 context 控制生命周期
* 禁止 goroutine 泄漏
* 共享数据必须加锁或通过 channel 传递
* 使用 `sync.WaitGroup` 等待 goroutine 完成

---

## 7. 依赖管理

* 优先使用标准库
* 禁止引入无必要第三方库
* 新增依赖需在 PR 中说明原因

---

## 8. 格式化（强制）

所有代码提交前必须通过：

```bash
gofmt -w .
goimports -w .
golangci-lint run
```

违反 gofmt / goimports 的代码禁止合并。

---

## 9. 禁止行为

* ❌ 无意义变量命名
* ❌ 忽略 error 返回值
* ❌ 使用 fmt.Println 输出日志
* ❌ panic 用于业务错误处理
* ❌ 超过 3 层 if 嵌套
* ❌ 单函数超过 50 行
