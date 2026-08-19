---
description: PHP API 接口设计规范（通用）
paths: ["**/*.php"]
alwaysApply: false
---

# PHP API 接口设计规范

适用于所有 PHP RESTful API 服务。与 `security.md` 配合，本文件只讲 API 设计；输入校验安全细节见 security.md，Controller 框架写法见项目级框架规范。

---

## 生成模式（强制两步）

* **Step 1**：列出所有 action（路径 + 方法 + 简述），**不生成**代码
* **Step 2**：确认后生成完整接口定义、DTO、Controller 骨架

禁止跳步或一次性生成全部代码。

---

## URL 设计

RESTful：路径表达资源，方法表达操作。

```
GET    /api/v1/users           # 列表
GET    /api/v1/users/{id}      # 详情
POST   /api/v1/users           # 创建
PUT    /api/v1/users/{id}      # 全量更新
PATCH  /api/v1/users/{id}      # 部分更新
DELETE /api/v1/users/{id}      # 删除
```

* 路径小写 + 连字符（kebab-case）：`/api/v1/user-profiles`
* 资源用复数名词
* 嵌套最多两层：`/users/{id}/addresses`，超过则拆独立资源
* 版本号放路径前缀：`/api/v1/`
* 动作型操作用动词子路径：`POST /api/v1/users/{id}/activate`

---

## HTTP 方法语义

| 方法 | 语义 | 幂等 | 请求体 |
|------|------|------|--------|
| GET | 查询，不改状态 | ✅ | 无 |
| POST | 创建/触发操作 | ❌ | JSON |
| PUT | 全量替换 | ✅ | JSON |
| PATCH | 部分更新 | ✅ | JSON |
| DELETE | 删除 | ✅ | 无 |

禁止 GET 改变服务端状态。

---

## 统一响应信封

```json
{
    "code": 0,
    "message": "success",
    "data": { ... },
    "requestId": "550e8400-e29b-41d4-a716-446655440000"
}
```

| 字段 | 说明 |
|------|------|
| `code` | 业务状态码，0 表示成功 |
| `message` | 描述信息 |
| `data` | 业务数据（object/array/null） |
| `requestId` | 请求追踪 ID |

列表响应：

```json
{
    "code": 0,
    "data": {
        "list": [ { "id": 1, "name": "Alice" } ],
        "total": 100,
        "page": 1,
        "pageSize": 20
    }
}
```

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

## 错误响应与业务码

```json
{
    "code": 400001,
    "message": "请求参数错误",
    "errors": [
        { "field": "email", "message": "邮箱格式不正确" }
    ],
    "requestId": "..."
}
```

业务错误码集中定义：

```php
final class ErrorCode
{
    // 通用 1xxxxx
    public const INVALID_PARAMS  = 400001;
    public const UNAUTHORIZED    = 401001;
    public const NOT_FOUND       = 404001;
    public const CONFLICT        = 409001;
    public const INTERNAL_ERROR  = 500001;
    // 业务模块 2xxxxx
    public const USER_EMAIL_DUPLICATED = 200001;
}
```

生产环境响应禁止暴露异常堆栈、数据库错误、内部路径（见 security.md）。

---

## 分页

所有列表接口必须支持分页，`pageSize` 默认 20、最大 100：

```php
final class PaginationRequest
{
    public function __construct(
        #[Assert\Range(min: 1)]
        public readonly int $page = 1,
        #[Assert\Range(min: 1, max: 100)]
        public readonly int $pageSize = 20,
    ) {}
}
```

---

## DTO 命名

* 请求 DTO：`{动作}{资源}Request` —— `CreateUserRequest`、`UpdateUserRequest`
* 响应 DTO：`{资源}Response` —— `UserResponse`
* 响应有 `fromModel()` 工厂方法做模型→DTO 转换

---

## 版本管理

* 版本号放 URL：`/api/v1/`、`/api/v2/`
* 破坏性变更（删字段、改类型）必须升版本号
* 非破坏性变更（加字段、加接口）可在当前版本追加
* 旧版本下线前提前通知，至少维护 6 个月

---

## OpenAPI 注解

每个接口必须有完整注解，含 `security` 声明认证要求：

```php
#[OA\Post(
    path: '/api/v1/users',
    summary: '创建用户',
    security: [['bearerAuth' => []]],
    requestBody: new OA\RequestBody(required: true, content: new OA\JsonContent(ref: CreateUserRequest::class)),
    responses: [
        new OA\Response(response: 201, description: '创建成功', content: new OA\JsonContent(ref: UserResponse::class)),
        new OA\Response(response: 409, description: '邮箱已存在'),
    ]
)]
public function create(CreateUserRequest $request): JsonResponse { ... }
```

---

## 一致性

* JSON 字段统一 **camelCase**
* 时间字段统一 RFC 3339：`2026-05-09T10:00:00+08:00`，禁止时间戳整数
* 金额用整数（分），禁止浮点数
* 布尔用 `true`/`false`，不用 `1`/`0`
* 空值返回 `null`，不省略字段、不用空字符串代替

---

## 禁止行为

* ❌ 一次性生成接口定义（必须两步确认）
* ❌ GET 修改数据
* ❌ 路径用动词表示 CRUD（`/getUser`、`/deleteUser`）
* ❌ 嵌套资源超过两层
* ❌ Controller 包含业务逻辑或直接操作数据库
* ❌ 金额用浮点数、时间用时间戳整数
* ❌ 生产环境响应暴露异常堆栈
