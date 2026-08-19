---
description: Go 测试规范
paths: ["**/*_test.go"]
alwaysApply: false
---

# Go 测试规范

适用于所有 Go 模块。框架专属测试（如 go-zero 的 logic/model/handler 分层测试）见项目级框架规范。

---

## 1. 测试要求

* 新功能必须包含对应单元测试
* 核心业务逻辑覆盖率目标 ≥ 80%
* bug fix 必须附带复现该 bug 的测试用例
* 禁止在单元测试中连接生产数据库
* **先写测试，再写实现（TDD）**：测试必须先运行并失败，再写实现使其通过

---

## 2. 分层策略

| 层 | 测试对象 | 外部依赖 |
|----|---------|---------|
| 业务逻辑层（Service/Logic） | 核心业务规则（主要测试层） | Mock 依赖接口 |
| 数据访问层（Repository/Model） | 数据库操作 | 测试数据库（真实 DB） |
| HTTP 层（Handler） | 请求/响应绑定 | Mock 业务层 |
| 集成测试 | 跨层完整流程 | 测试容器/内存数据库 |

重点测业务逻辑层，覆盖率 ≥ 80%。

---

## 3. 标准测试结构

依赖通过构造函数注入，测试时传入 Mock：

```go
func TestUserService_GetUser(t *testing.T) {
    ctrl := gomock.NewController(t)
    defer ctrl.Finish()

    mockRepo := mocks.NewMockUserRepository(ctrl)
    mockRepo.EXPECT().
        FindByID(gomock.Any(), int64(1)).
        Return(&User{ID: 1, Name: "Alice"}, nil)

    svc := NewUserService(mockRepo)
    user, err := svc.GetUser(context.Background(), 1)

    require.NoError(t, err)
    assert.Equal(t, "Alice", user.Name)
}
```

---

## 4. 数据访问层测试

用真实数据库（禁止 Mock DB），推荐 `testcontainers-go`：

```go
func TestUserRepository_FindByID(t *testing.T) {
    db := setupTestDB(t)  // 启动测试容器
    repo := NewUserRepository(db)
    result, err := db.Exec("INSERT INTO users (name) VALUES (?)", "test")
    require.NoError(t, err)
    id, _ := result.LastInsertId()
    t.Cleanup(func() { db.Exec("DELETE FROM users WHERE id = ?", id) })

    user, err := repo.FindByID(context.Background(), id)
    require.NoError(t, err)
    assert.Equal(t, "test", user.Name)
}
```

---

## 5. HTTP 层测试

用 `net/http/httptest`，只验 HTTP 层，不测业务规则：

```go
func TestLoginHandler(t *testing.T) {
    body := `{"username":"alice","password":"123456"}`
    req := httptest.NewRequest(http.MethodPost, "/user/login", strings.NewReader(body))
    req.Header.Set("Content-Type", "application/json")
    w := httptest.NewRecorder()

    handler := NewLoginHandler(svcCtx)
    handler(w, req)

    assert.Equal(t, http.StatusOK, w.Code)
}
```

---

## 6. 命名规范

```go
// 单元测试
func TestFuncName(t *testing.T) {}

// 子测试（场景描述）
func TestFuncName_ScenarioDesc(t *testing.T) {}
```

---

## 7. 表驱动测试（优先使用）

```go
func TestValidateEmail(t *testing.T) {
    tests := []struct {
        name  string
        email string
        want  bool
    }{
        {name: "standard", email: "user@example.com", want: true},
        {name: "no @", email: "userexample.com", want: false},
        {name: "empty", email: "", want: false},
    }
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            assert.Equal(t, tt.want, ValidateEmail(tt.email))
        })
    }
}
```

---

## 8. 断言

用 `github.com/stretchr/testify`：

```go
assert.Equal(t, expected, actual)     // 失败继续
assert.NoError(t, err)
require.NotNil(t, obj)                // 失败即停止后续断言
```

禁止用 `if got != want { t.Fatal(...) }` 代替断言库。

---

## 9. Mock 规范

* 依赖外部系统（DB/HTTP/缓存）的单元测试必须 Mock
* 用 `github.com/golang/mock/mockgen` 生成 Mock，不手写 Mock 实现
* Mock 文件放项目根 `mocks/` 目录

```bash
mockgen -source=repository/user_repository.go -destination=mocks/mock_user_repository.go -package=mocks
```

---

## 10. 集成测试

* 使用独立测试数据库，禁止污染开发/生产数据
* 推荐 `testcontainers-go` 启动临时容器
* 集成测试文件以 `_integration_test.go` 结尾，通过 build tag 隔离：

```go
//go:build integration
```

---

## 11. 测试隔离

* 每个用例独立运行，不依赖其他测试状态
* 用 `t.Cleanup` 清理副作用
* 数据库测试用事务回滚或 `t.Cleanup` 清理

---

## 12. 本地执行（提交前必须通过）

```bash
go test ./...
go test -race ./...   # 检测竞态条件
```

---

## 13. CI 配置（GitHub Actions）

文件路径：`.github/workflows/go-ci.yml`

```yaml
name: Go CI
on:
  pull_request:
  push:
    branches: ["main"]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with:
          go-version: "1.22"
      - uses: actions/cache@v4
        with:
          path: |
            ~/.cache/go-build
            ~/go/pkg/mod
          key: ${{ runner.os }}-go-${{ hashFiles('**/go.sum') }}
      - run: go mod tidy
      - name: Lint
        run: |
          go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest
          golangci-lint run
      - name: Test
        run: go test -race ./...
```

---

## 14. golangci-lint 配置

文件路径：`.golangci.yml`

```yaml
run:
  timeout: 5m
  tests: true

linters:
  enable:
    - govet
    - errcheck
    - staticcheck
    - ineffassign
    - unused
    - gosimple
    - gocyclo
    - gofmt
    - goimports
    - revive
    - bodyclose

linters-settings:
  gocyclo:
    min-complexity: 15
```

---

## 15. 禁止行为

* ❌ 业务逻辑层测试连接真实数据库
* ❌ 手写 Mock 实现（用 mockgen 生成）
* ❌ handler 层测试包含业务逻辑断言
* ❌ 测试用例之间共享可变状态
* ❌ 用 `if got != want { t.Fatal(...) }` 代替断言库
* ❌ `sleep()` 等待异步操作（Mock 时间依赖）
