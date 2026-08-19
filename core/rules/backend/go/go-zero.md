---
description: go-zero 框架专属规范（项目级模板）
paths: ["**/*.go", "**/*.api"]
alwaysApply: false
---

# go-zero 开发规范

复制到项目 `.claude/rules/` 使用。与用户级 `code-style.md`/`security.md`/`testing.md`/`api.md` 配合，本文件只讲 go-zero 独有内容。

---

## 基本原则

* 用 `goctl` 生成代码骨架，禁止手写 handler/router 等生成产物
* 禁止伪造或模拟 goctl / mcp-zero 命令输出
* 所有代码必须通过 `golangci-lint run`
* 禁止绕过 lint / test

---

## 项目分层（强制）

```
handler/    仅 HTTP 请求/响应、参数绑定，调用 logic
logic/      业务逻辑，唯一允许有分支判断和业务规则的层
svc/        ServiceContext，依赖注入，组装依赖
model/      数据库访问，goctl 生成，禁止写业务逻辑
```

禁止：
* handler 直接调用 model
* logic 返回 HTTP 状态码
* model 层包含业务判断
* 跨层调用（handler → model 跳过 logic）

---

## goctl 生成

```bash
# API 服务
goctl api go -api xxx.api -dir . -style gozero

# Model
goctl model mysql ddl -src xxx.sql -dir ./model -c

# RPC
goctl rpc protoc xxx.proto --go_out=. --go-grpc_out=. --zrpc_out=.
```

* 生成后的 handler/router 文件禁止手动修改
* 业务代码只写在 logic 层
* 重新生成不覆盖 logic（goctl 默认行为，注意保留）

---

## ServiceContext

所有外部依赖（DB/Redis/RPC client/config）统一在 `svc/servicecontext.go` 初始化：

```go
type ServiceContext struct {
    Config      config.Config
    UserModel   model.UserModel
    RedisClient *redis.Redis
}

func NewServiceContext(c config.Config) *ServiceContext {
    return &ServiceContext{
        Config:    c,
        UserModel: model.NewUserModel(sqlx.NewMysql(c.DB.DataSource), c.CacheRedis),
    }
}
```

禁止在 logic 层自行初始化数据库连接或外部客户端。

---

## 优先用 go-zero 内置能力

| 需求 | 使用 |
|------|------|
| 数据库 + 缓存 | model cache（goctl 生成，`-c` 参数） |
| 接口限流 | `limit/period` 或 `limit/token` |
| 熔断 | `core/breaker` |
| 日志 | `core/logx` |
| 配置 | `core/conf` |
| JWT 鉴权 | `.api` 文件 `jwt` 字段 |
| 超时控制 | `rest` server timeout 配置 |

禁止自行实现上述已有功能。

---

## .api 文件规范（go-zero DSL）

### 生成模式（强制两步）

* Step 1：输出 action 列表，**禁止**生成 `.api` 文件
* Step 2：确认后生成完整 `.api`

### 文件结构

```
@server (
    group: {module}
    jwt: Auth            // 需鉴权的接口
)
service {module}-api {
    @handler XxxHandler
    post /{module}/{action} (XxxReq) returns (XxxResp)
}
```

* service 命名：`{module}-api`
* 按模块拆分 `.api` 文件，不堆在一个文件
* 鉴权接口和公开接口分开用 `@server` 块声明

### 类型与字段

* 请求：`XxxReq`，响应：`XxxResp`，一一对应禁止复用
* Handler 与 action 名一致（首字母大写）：action `login` → `LoginHandler`
* json tag 统一 camelCase
* 非必填字段用 `optional` tag：`json:"nickname,optional"`

```go
type CreateOrderReq {
    UserId    int64  `json:"userId"`
    ProductId int64  `json:"productId"`
    Remark    string `json:"remark,optional"`
}
```

### 响应

所有响应通过 `httpx.OkJsonCtx` 返回，业务数据放在 `XxxResp` 中（Resp 不包装 code/message，框架统一处理）：

```go
type GetUserResp {
    UserId   int64  `json:"userId"`
    Nickname string `json:"nickname"`
}
```

错误由 `errorx` 统一处理，响应格式：`{ "code": 100001, "message": "记录不存在" }`

---

## 错误处理（errorx）

统一在 `common/errorx` 包定义业务错误码：

```go
var (
    ErrNotFound  = errorx.NewCodeError(100001, "记录不存在")
    ErrForbidden = errorx.NewCodeError(100002, "无权限")
    ErrParam     = errorx.NewCodeError(100003, "参数错误")
)

// logic 层使用
if user == nil {
    return nil, errorx.ErrNotFound
}
```

禁止直接返回数据库错误给 handler。

---

## 认证（JWT）

在 `.api` 文件 `@server` 的 `jwt` 字段声明受保护接口，**禁止公开接口和鉴权接口混在同一 `@server` 块**：

```
// ✅ 公开接口
@server (
    group: user
)
service user-api {
    post /user/login (LoginReq) returns (LoginResp)
}

// ✅ 需鉴权接口单独声明
@server (
    jwt:   Auth
    group: user
)
service user-api {
    post /user/profile (ProfileReq) returns (ProfileResp)
}
```

---

## 输入校验

用 validator tag 在 `.api` 类型中声明，go-zero 在 handler 层自动触发，无需 logic 层重复校验：

```
type CreateUserReq {
    Name  string `json:"name"  validate:"required,max=50"`
    Email string `json:"email" validate:"required,email"`
    Age   int    `json:"age"   validate:"min=1,max=150"`
}
```

---

## SQL 与 Model

优先用 goctl 生成的 model 方法（内部已参数化查询），禁止在 logic 层直接操作数据库连接：

```go
// ✅ 用生成的方法
user, err := l.svcCtx.UserModel.FindOne(l.ctx, userId)

// ⚠️ 必须手写时用占位符
l.svcCtx.UserModel.FindByCustom(l.ctx, "SELECT * FROM user WHERE email = ?", email)

// ❌ 禁止
db.QueryRow("SELECT * FROM users WHERE id = " + userId)
```

---

## 敏感配置

通过 `etc/xxx.yaml` + 环境变量占位符注入，`conf.MustLoad` 自动读取 `${VAR}`：

```yaml
Auth:
  AccessSecret: ${JWT_SECRET}
  AccessExpire: 86400
DB:
  DataSource: ${DB_DSN}
```

```go
// ✅
logx.Infow("user login", logx.Field("userId", userId))
// ❌ 禁止
logx.Infow("user login", logx.Field("password", req.Password))
```

---

## 限流

用 go-zero 内置限流器，高风险接口单独配置：

```go
// 滑动窗口（适合登录等接口）
limiter := limit.NewPeriodLimit(periodSeconds, quota, redis, keyPrefix)
// 令牌桶（适合通用接口）
limiter := limit.NewTokenLimiter(rate, burst, redis, key)
```

---

## CORS

在 `main.go` 或 middleware 中注册，**生产环境禁止 `Access-Control-Allow-Origin: *`**，用域名白名单：

```go
server.Use(func(next http.HandlerFunc) http.HandlerFunc {
    return func(w http.ResponseWriter, r *http.Request) {
        origin := r.Header.Get("Origin")
        if isAllowedOrigin(origin) {
            w.Header().Set("Access-Control-Allow-Origin", origin)
        }
        next(w, r)
    }
})
```

---

## 分层测试（go-zero）

| 层 | 测试对象 | 外部依赖 |
|----|---------|---------|
| logic | 业务逻辑（主要测试层） | Mock model 接口 |
| model | 数据库操作 | 测试数据库（真实 DB） |
| handler | HTTP 入参/出参绑定 | Mock logic 接口 |
| svc | ServiceContext 装配 | 集成测试验证 |

重点测 logic 层，覆盖率 ≥ 80%。

### Logic 层测试

构造含 Mock model 的 `svcCtx`：

```go
func TestGetUserLogic_GetUser(t *testing.T) {
    ctrl := gomock.NewController(t)
    defer ctrl.Finish()

    mockModel := mocks.NewMockUserModel(ctrl)
    mockModel.EXPECT().FindOne(gomock.Any(), int64(1)).
        Return(&model.User{Id: 1, Nickname: "Alice"}, nil)

    svcCtx := &svc.ServiceContext{UserModel: mockModel}
    l := NewGetUserLogic(context.Background(), svcCtx)

    resp, err := l.GetUser(&types.GetUserReq{UserId: 1})
    require.NoError(t, err)
    assert.Equal(t, "Alice", resp.Nickname)
}
```

### Model 层测试

用真实数据库（禁止 Mock DB），推荐 `testcontainers-go`：

```go
func TestUserModel_FindOne(t *testing.T) {
    db := setupTestDB(t)
    m := model.NewUserModel(db, nil)
    result, err := db.Exec("INSERT INTO user (nickname) VALUES (?)", "test")
    require.NoError(t, err)
    id, _ := result.LastInsertId()
    t.Cleanup(func() { db.Exec("DELETE FROM user WHERE id = ?", id) })

    user, err := m.FindOne(context.Background(), id)
    require.NoError(t, err)
    assert.Equal(t, "test", user.Nickname)
}
```

### Handler 层测试

用 `net/http/httptest`，只验 HTTP 层，不测业务规则：

```go
func TestLoginHandler(t *testing.T) {
    body := `{"username":"alice","password":"123456"}`
    req := httptest.NewRequest(http.MethodPost, "/user/login", strings.NewReader(body))
    req.Header.Set("Content-Type", "application/json")
    w := httptest.NewRecorder()
    NewLoginHandler(svcCtx)(w, req)
    assert.Equal(t, http.StatusOK, w.Code)
}
```

### ServiceContext 测试辅助

在 `internal/svc/testhelper_test.go` 提供 `NewTestServiceContext`：

```go
func NewTestServiceContext(t *testing.T) *ServiceContext {
    t.Helper()
    return &ServiceContext{
        Config:    config.Config{},
        UserModel: mocks.NewMockUserModel(gomock.NewController(t)),
    }
}
```

goctl 生成的 model 含接口定义，直接用 mockgen 生成 Mock：

```bash
mockgen -source=model/usermodel.go -destination=mocks/mock_usermodel.go -package=mocks
```

---

## 禁止行为

* ❌ 手写 handler/router 等生成产物
* ❌ handler 直接调 model、logic 返回 HTTP 状态码、model 写业务逻辑
* ❌ 修改 goctl 生成的 handler/router 文件
* ❌ 自行实现 go-zero 已有的限流/熔断/缓存能力
* ❌ 公开接口和鉴权接口混在同一 `@server` 块
* ❌ logic 层直接操作数据库连接
* ❌ 直接返回数据库错误给 handler（用 errorx）
