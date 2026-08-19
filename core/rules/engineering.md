---
description: 工程原则（通用，常驻）
alwaysApply: true
---

# 工程原则

跨语言、跨框架的通用工程底线，会话常驻。语言专属规范（Go/PHP 等）按文件类型加载，补充该语言特有规则与语法示例。

---

## 命名

* 用完整、有意义的词，禁止无意义缩写（`a`、`tmp`、`data`、`info`）
* 命名表达意图：`getUserById` 优于 `get`；`isEmailValid` 优于 `check`
* 布尔变量/函数用 `is`/`has`/`can`/`should` 前缀
* 常量语义化命名，禁止魔法数字/字符串

```
// ❌
const x = 86400
if (s > x) { ... }
// ✅
const SECONDS_PER_DAY = 86400
if (sessionAge > SECONDS_PER_DAY) { ... }
```

---

## 函数与控制流

* 单一职责：一个函数只做一件事，可用一句话描述
* 优先 early return，减少嵌套；禁止嵌套超过 3 层
* 函数参数 > 3 个时用对象/结构体传参

---

## 注释

* 注释解释 **WHY**（为什么这样做），不解释 WHAT（代码已经说了）
* 禁止注释掉的代码直接提交（用 git 管理版本）
* 复杂算法/非显然业务规则必须加注释

---

## 错误处理

* 禁止静默忽略错误（空 catch、丢弃返回值）
* 错误信息必须含上下文：**在哪里** 出了 **什么问题**
* 不要用异常控制正常业务流程

---

## 安全底线

> 以下为语言无关的公共安全原则，任何后端语言（Go/PHP/Python 等）均适用。语言特有的实现方式（库选择、API 用法、语言专属陷阱）见 `~/.claude/rules/backend/<lang>/security.md`。

### 通用原则

* 禁止硬编码密钥/密码/token/API key，通过环境变量或配置中心注入；`.env` 必须 `.gitignore`，提供 `.env.example` 供参考；禁止把密钥打进容器镜像层，用运行时注入
* 所有外部输入（HTTP/文件/MQ）在入口层校验，业务层不信任；字符串限最大长度，数值限范围，枚举校验白名单
* SQL 禁止字符串拼接，必须参数化查询或 ORM 绑定；动态列名/表名/ORDER BY 必须白名单校验（绑定参数不能用于标识符）
* 密码用 bcrypt（cost ≥ 12）或 Argon2id 存储，禁止明文/MD5/SHA1；cost 变更后需重新哈希
* 日志禁止输出密码、token、完整身份证号、银行卡号、完整手机号
* 生产环境错误响应不暴露堆栈、数据库错误、内部路径；堆栈只进日志，客户端只收统一错误码 + 通用消息
* 定期检查依赖漏洞（`govulncheck`/`npm audit`/`composer audit`/`pip-audit`），CI 强制运行，高危漏洞（CVSS ≥ 7.0）阻断构建；锁文件必须提交

### 高风险接口限流

登录/注册/发验证码/重置密码等接口必须限流，分布式环境必须用共享存储计数（不能靠单进程内存）：

| 接口 | 限制 |
|------|------|
| 登录 | 10 次/分钟/IP |
| 发验证码 | 1 次/分钟/手机号 |
| 注册 | 5 次/小时/IP |

### 命令注入

禁止把用户输入传入系统命令执行；优先用语言原生库替代起子进程（图像处理用图像库，不用 `convert`）。确需子进程时必须用参数列表传参，禁止 shell 拼接。

### 反序列化

禁止对不可信数据使用不安全的反序列化（PHP `unserialize`、Python `pickle`/`yaml.load`、Go `gob` 解码到 `interface{}`），存在 RCE 风险。优先用 JSON 解码到具体结构体，或 YAML 的安全加载方式。

### 文件上传

* 用文件头探测真实 MIME（不信任 `Content-Type` 头），白名单校验类型
* 限制文件大小
* 重命名为随机文件名，禁止使用原始文件名/扩展名
* 上传目录禁止放 Web 根可直接访问
* 拼接存储路径时必须校验最终路径在允许目录内，防路径穿越

### 模板注入（SSTI）

渲染 HTML 时禁止用字符串拼接构造模板；变量必须通过模板上下文传入，由模板引擎自动转义（PHP Twig 默认转义禁 `|raw`、Go `html/template`、Python Jinja2 `autoescape=True`）。

### CORS

生产环境禁止 `Access-Control-Allow-Origin: *`；通过中间件配置允许的域名白名单。允许凭据时 `AllowOrigin` 不能为 `*`，必须回显具体 Origin。

### HTTP 安全头

生产环境通过中间件统一注入：

* `X-Content-Type-Options: nosniff`
* `X-Frame-Options: DENY`
* `Referrer-Policy: strict-origin-when-cross-origin`
* `Content-Security-Policy: default-src 'self'; script-src 'self'`

---

## 测试哲学

* **TDD**：先写测试并确认失败，再写实现使其通过；禁止同时生成代码和测试
* 新增业务逻辑必须含单元测试；bug fix 必须附能复现该 bug 的失败测试
* 核心业务逻辑覆盖率 ≥ 80%
* 优先表驱动测试覆盖边界（正常值/边界值/异常值）
* 测试函数名描述被测场景：`TestCreateUser_DuplicateEmail` 优于 `TestCreateUser2`
* 单元测试禁连生产数据库，必须能独立运行；集成测试用独立 DB 或容器
* 不测试实现细节，测试行为和输出

---

## 可读性

* 代码写给人读，其次才是机器执行
* 提交前问：陌生人三个月后还能快速理解这段代码吗？
