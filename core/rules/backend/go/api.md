---
description: Go API 设计规范（RPC 风格）
paths: ["**/*.go", "**/*.api"]
alwaysApply: false
---

# Go API 设计规范

适用于 Go 后端服务的 HTTP API。RPC 风格，与具体框架无关。框架实现细节（如 go-zero `.api` DSL）见项目级框架规范。

---

## 生成模式（强制两步）

* **Step 1**：列出所有 action（路径 + 方法 + 简述），**不生成**代码
* **Step 2**：确认后生成完整接口定义、DTO、Controller 骨架

禁止跳步或一次性生成全部代码。

---

## 路径与方法命名

### 路径结构（RPC 风格）

* 路径表达"调用哪个模块的哪个函数"，不是资源定位
* 结构：`/{module}/{action}` 或 `/{module}/{id}`
* **模块名用单数**：`user`、`order`、`product`（复数是 RESTful 约定，RPC 不用）
* 全小写 + kebab-case，模块名和 action 都适用：`/user-profile/create`、`/order/cancel-batch`
* action 用动词表达行为：`create`/`update`/`delete`/`query`/`ban`/`cancel`
* 单一职责：一个 action 只做一件事

### HTTP 方法（按读/写语义，不统一 POST）

| 场景 | 方法 | 参数位置 |
|------|------|---------|
| 读（简单参数，能放 URL） | GET | query string |
| 读（复杂/大参数，长 JSON、嵌套结构） | POST + body | body |
| 写（增/改/删） | POST + body | body |

GET 可缓存、幂等、语义清晰；POST 改变状态。GET 参数走 query string（HTTP 规范上 GET 不该有 body，网关/代理会丢弃）。

### action 省略规则

**GET 请求省略"读"类 action**——GET 方法本身已表达读取，路径直接定位资源：

```
GET  /user              # 列表（省略 list/get）
GET  /user/{id}         # 单个（省略 get，用路径参数定位）
POST /user/query        # 复杂查询（参数大用 POST，保留 query）
```

**POST 请求保留动作名**——POST 是传输方式，操作语义必须由 action 表达：

```
POST /user/create       # 创建
POST /user/update       # 更新
POST /user/delete       # 删除
POST /user/ban          # 非 CRUD 动作（不可省略）
```

非 CRUD 动作（封禁、取消、重置密码等）无论方法都保留 action 名。

### 请求/响应类型

* 请求：`XxxReq`，响应：`XxxResp`（或 DTO 命名按框架惯例）
* 一一对应，禁止复用请求/响应类型
* Handler/Controller 与 action 名对应

### JSON 字段

* 统一 **camelCase**：`userId`、`createdAt`（与 URL 的 kebab-case 独立约定）
* 字段名必须语义化，禁止 `data`、`info`、`result` 等模糊命名
* 必须定义完整字段，禁止省略

---

## 统一响应信封

成功响应直接放业务数据（不强制包装 code/message，由框架/中间件统一处理）：

```json
{
    "userId": 1,
    "nickname": "Alice",
    "avatar": "https://..."
}
```

错误响应统一格式：

```json
{
    "code": 100001,
    "message": "记录不存在"
}
```

* 业务错误码集中定义在 `errorx`（或等效的错误码常量类）
* 生产环境响应**禁止**暴露异常堆栈、数据库错误、内部路径
* 鉴权失败 401，权限不足 403，**不透露具体失败原因**

---

## 状态码

| 场景 | 码 |
|------|-----|
| 查询/更新成功 | 200 |
| 创建成功 | 201 |
| 删除/无响应体 | 204 |
| 参数错误 | 400 |
| 未登录/Token 无效 | 401 |
| 无权限 | 403 |
| 资源不存在 | 404 |
| 资源冲突 | 409 |
| 校验失败 | 422 |
| 限流 | 429 |
| 内部错误 | 500 |

---

## 分页

所有列表接口必须支持分页：

```json
// 请求（GET query 或 POST body）
{ "page": 1, "pageSize": 20 }

// 响应
{ "list": [ ... ], "total": 100 }
```

`pageSize` 默认 20、最大 100。

---

## 版本管理

* 版本号放 URL 前缀：`/api/v1/`、`/api/v2/`
* 破坏性变更（删字段、改类型）必须升版本号
* 非破坏性变更（加字段、加接口）可在当前版本追加
* 旧版本下线前提前通知，至少维护 6 个月

---

## 一致性

* 时间字段统一 RFC 3339：`2026-05-09T10:00:00+08:00`，禁止时间戳整数
* 金额用整数（分），禁止浮点数
* 布尔用 `true`/`false`，不用 `1`/`0`
* 空值返回 `null`，不省略字段、不用空字符串代替

---

## 认证声明

接口文档中必须显式标注认证要求（OpenAPI 注解或框架路由声明），公开接口与鉴权接口分开声明，禁止混在同一分组。

---

## 禁止行为

* ❌ 一次性生成接口定义（必须两步确认）
* ❌ 统一 POST（读操作必须用 GET，除非参数过大）
* ❌ GET 请求改变服务端状态
* ❌ 模块名用复数（RPC 用单数）
* ❌ 路径用 camelCase 或 snake_case（用 kebab-case）
* ❌ GET 请求带 body
* ❌ 模糊字段命名（data、info、result）
* ❌ 一个接口承担多个职责
* ❌ 公开接口和鉴权接口混在同一分组
* ❌ 金额用浮点数、时间用时间戳整数
* ❌ 生产环境响应暴露异常堆栈
