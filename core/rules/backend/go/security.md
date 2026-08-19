---
description: Go 安全规范
paths: ["**/*.go"]
alwaysApply: false
---

# Go 安全规范

适用于所有 Go 后端服务。通用安全底线（硬编码密钥、`.env` gitignore、日志脱敏、依赖漏洞、限流数值、CORS、HTTP 安全头、命令注入、反序列化、文件上传、路径穿越、模板注入）见 `~/.claude/rules/engineering.md`，本文件只讲 Go 特有实现与补充。框架专属安全（go-zero JWT/validator/model）见项目级框架规范。

---

## 认证与授权

* 需要登录的接口必须通过认证中间件保护，禁止在业务逻辑层自行解析 token
* 使用 JWT 时，必须验证签名算法、`exp`、`iss`，显式指定算法防降级，禁止接受 `alg=none`
* 鉴权失败统一返回 401，权限不足返回 403，**不透露具体失败原因**

```go
token, err := jwt.Parse(rawToken, func(t *jwt.Token) (interface{}, error) {
    if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
        return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
    }
    return []byte(settings.JWTSecret), nil
}, jwt.WithExpirationRequired(), jwt.WithIssuer(settings.JWTIssuer))
if err != nil || !token.Valid {
    return ErrUnauthorized
}
```

---

## 输入校验

通用原则见 engineering.md。Go 用框架校验器（go-zero `validate` tag、`go-playground/validator`）：

```go
type RegisterReq struct {
    Name  string `json:"name" validate:"required,min=1,max=50"`
    Email string `json:"email" validate:"required,email"`
    Age   int    `json:"age" validate:"gte=0,lte=150"`
    Role  string `json:"role" validate:"oneof=admin user"`
}
```

---

## SQL 占位符

通用原则见 engineering.md（禁拼接、参数化、动态列名白名单）。Go 实现：手写 SQL 时用 `?`（MySQL）或 `$1`（PostgreSQL）：

```go
// ✅
row := db.QueryRowContext(ctx, "SELECT * FROM users WHERE id = ?", id)

// ❌
db.QueryRow("SELECT * FROM users WHERE id = " + userId)
```

动态列名/表名白名单：

```go
var allowedSort = map[string]bool{"name": true, "created_at": true}
if !allowedSort[orderBy] {
    return fmt.Errorf("invalid order column: %s", orderBy)
}
query := fmt.Sprintf("SELECT * FROM users ORDER BY %s", orderBy)
```

---

## 命令注入

通用原则见 engineering.md。Go 特有：`exec.Command` 默认不走 shell，但仍禁止参数拼接：

```go
// ❌ 用户输入拼进参数
cmd := exec.Command("sh", "-c", "convert "+filename+" out.png")

// ✅ 参数列表传参，不经 shell
cmd := exec.Command("convert", filename, "out.png")
```

优先用库替代起子进程（图像处理用 `disintegration/imaging`，不用 `convert`）。

---

## 模板注入（SSTI）

通用原则见 engineering.md（变量通过上下文传入，引擎自动转义）。Go 特有：`html/template` 自动转义，`text/template` **不**转义，禁止用于 HTML：

```go
// ❌ 用户输入拼进模板字符串
tmpl := template.Must(template.New("t").Parse("Hello " + userInput))
tmpl.Execute(w, nil)

// ✅ 变量通过上下文传入，html/template 自动转义
tmpl := template.Must(template.New("t").Parse("Hello {{.Name}}"))
tmpl.Execute(w, struct{ Name string }{Name: userInput})
```

---

## 反序列化

通用原则见 engineering.md。Go 特有：禁止 `gob`/`yaml.Unmarshal` 解码到 `interface{}`（任意类型实例化或 panic）：

```go
// ❌ 解码到 interface{} 接受任意结构
var cfg interface{}
yaml.Unmarshal(userBytes, &cfg)

// ✅ 解码到具体结构体
var cfg Config
if err := yaml.Unmarshal(userBytes, &cfg); err != nil {
    return fmt.Errorf("parse config: %w", err)
}
```

---

## 密码

通用原则见 engineering.md（bcrypt cost≥12、rehash）。Go 实现：

```go
import "golang.org/x/crypto/bcrypt"

// 存储
hashed, err := bcrypt.GenerateFromPassword([]byte(password), 12)

// 验证
err := bcrypt.CompareHashAndPassword(hashed, []byte(password))

// cost 变更后重新哈希
if bcrypt.Cost(hashed) < 12 {
    newHashed, _ := bcrypt.GenerateFromPassword([]byte(password), 12)
    _ = newHashed
}
```

需要 Argon2id 用 `golang.org/x/crypto/argon2`。

---

## 敏感数据

通用原则见 engineering.md。Go 结构化日志脱敏：

```go
// ✅
logger.Info("user login", "userId", userId)
// ❌
logger.Info("user login", "password", req.Password)
```

手机号脱敏：

```go
func MaskPhone(phone string) string {
    if len(phone) < 7 {
        return "***"
    }
    return phone[:3] + "****" + phone[len(phone)-4:]
}
```

---

## 文件上传

通用原则见 engineering.md（MIME 探测、大小限制、随机名、目录隔离、路径校验）。Go 实现：

```go
buf := make([]byte, 512)
n, _ := file.Read(buf)
mimeType := http.DetectContentType(buf[:n])
allowed := map[string]bool{"image/jpeg": true, "image/png": true, "image/webp": true}
if !allowed[mimeType] {
    return ErrInvalidFileType
}

// 限制大小 + 重命名为随机文件名，不用原始文件名
ext := strings.Split(mimeType, "/")[1]
filename := hex.EncodeToString(generateRandom(16)) + "." + ext
```

---

## 路径穿越

通用原则见 engineering.md（拼接后校验最终路径在允许目录内）。Go 实现：

```go
func SafeJoin(base, userPath string) (string, error) {
    target, err := filepath.Abs(filepath.Join(base, userPath))
    if err != nil {
        return "", err
    }
    absBase, _ := filepath.Abs(base)
    if !strings.HasPrefix(target, absBase+string(filepath.Separator)) {
        return "", ErrPathTraversal
    }
    return target, nil
}
```

---

## HTTP 安全头

通用原则见 engineering.md。Go 注入实现：

```go
w.Header().Set("X-Content-Type-Options", "nosniff")
w.Header().Set("X-Frame-Options", "DENY")
w.Header().Set("Referrer-Policy", "strict-origin-when-cross-origin")
w.Header().Set("Content-Security-Policy", "default-src 'self'; script-src 'self'")
```

---

## 配置与密钥

通用原则见 engineering.md（环境变量注入、`.env` gitignore、不打镜像层）。Go 配置结构体集中定义，启动校验必填项：

```go
type Config struct {
    JWTSecret string `json:",env=JWT_SECRET"`
    DBSource  string `json:",env=DB_SOURCE"`
    RedisHost string `json:",env=REDIS_HOST"`
}
```

---

## 依赖安全

通用原则见 engineering.md。Go 用 `govulncheck`，CI 强制运行，高危漏洞（CVSS ≥ 7.0）阻断构建；`go.sum` 必须提交。

---

## 错误响应

通用原则见 engineering.md（堆栈只进日志，客户端收统一错误码）。Go 实现：

```go
// ❌
return fmt.Sprintf(`{"error": "%s"}`, err.Error())

// ✅
logx.Errorf("internal error: %v", err)
return httperror.New(http.StatusInternalServerError, 500, "服务内部错误")
```

生产环境关闭详细错误输出。

---

## 禁止行为

* ❌ SQL 字符串拼接（用占位符）
* ❌ 接口无认证直接访问用户数据、JWT 验证接受 `alg=none`
* ❌ `exec.Command` 拼接用户输入、`text/template` 渲染 HTML
* ❌ `gob`/`yaml.Unmarshal` 解码到 `interface{}` 反序列化不可信数据
* ❌ MD5/SHA1 存密码、硬编码密钥
* ❌ 日志输出敏感字段、信任原始文件名/Content-Type、未校验路径穿越
* ❌ 生产环境 `Access-Control-Allow-Origin: *`、暴露错误堆栈
* ❌ 把密钥打进容器镜像层
