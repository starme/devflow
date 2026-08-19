---
description: PHP 安全规范
paths: ["**/*.php"]
alwaysApply: false
---

# PHP 安全规范

适用于所有 PHP 后端服务。通用安全底线（硬编码密钥、`.env` gitignore、日志脱敏、依赖漏洞、限流数值、CORS、HTTP 安全头、命令注入、反序列化、文件上传、路径穿越、模板注入）见 `~/.claude/rules/engineering.md`，本文件只讲 PHP 特有实现与补充。框架专属安全（Symfony Security / Laravel Sanctum 等）见项目级框架规范。

---

## 认证与授权

* 需登录接口通过中间件统一校验，禁止业务层自行解析 token
* JWT 必须校验签名算法、`exp`、`iss`，显式指定算法防降级攻击
* 鉴权失败 401，权限不足 403，**不透露具体失败原因**
* 登录后必须 `session_regenerate_id(true)` 防会话固定

```php
$token = $this->jwtParser->parse($rawToken);
if (!$this->jwtValidator->validate($token)) {
    throw new UnauthorizedException();
}
```

---

## 输入校验

通用原则见 engineering.md。PHP 用框架校验器（Symfony Validator / Laravel Validate）：

```php
#[Assert\NotBlank]
#[Assert\Length(max: 50)]
public string $name;

#[Assert\Range(min: 1, max: 150)]
public int $age;
```

---

## SQL 注入

通用原则见 engineering.md（禁拼接、参数化、动态列名白名单）。PHP 实现：

```php
// ✅ PDO 绑定
$stmt = $pdo->prepare('SELECT * FROM users WHERE email = :email');
$stmt->execute(['email' => $email]);

// ❌
$pdo->query("SELECT * FROM users WHERE email = '$email'");
```

动态 ORDER BY / 表名白名单：

```php
$allowed = ['name', 'created_at', 'email'];
if (!in_array($orderBy, $allowed, true)) {
    throw new InvalidArgumentException("Invalid order column: {$orderBy}");
}
$stmt = $pdo->prepare("SELECT * FROM users ORDER BY {$orderBy}");
```

---

## 命令注入

通用原则见 engineering.md。PHP 特有：禁止 `system`/`exec`/`shell_exec`/`passthru`/反引号 传入用户输入；优先用扩展库替代起子进程：

```php
// ❌ shell 拼接 = 命令注入
system("convert {$filename} out.png");

// ✅ 用 Imagick 扩展
$imagick = new Imagick($filename);
$imagick->writeImage('out.png');
```

---

## 反序列化

通用原则见 engineering.md。PHP 特有：禁止 `unserialize()` 处理不可信数据（对象注入导致 RCE）；优先用 `json_decode`：

```php
// ❌ 不可信数据 unserialize 可实例化任意对象，触发 __wakeup/__destruct
$obj = unserialize($userInput);

// ✅
$data = json_decode($userInput, true, 512, JSON_THROW_ON_ERROR);
```

确需 unserialize 时用 `allowed_classes` 白名单：

```php
$obj = unserialize($data, ['allowed_classes' => [SafeClass::class]]);
```

---

## 模板注入（SSTI）与 XSS

通用原则见 engineering.md（变量通过上下文传入，引擎自动转义）。PHP 特有：

```php
// ❌ 字符串拼模板，绕过转义
echo "Hello " . $userInput;
$html = $twig->createTemplate("Hello {{ name }}")->render(['name' => $userInput]); // 动态编译模板 = SSTI

// ✅ 预定义模板，变量走上下文
echo $twig->render('hello.html.twig', ['name' => $userInput]);
```

原生 PHP 输出必须手动转义；Twig 默认自动转义，禁止 `|raw` 除非确认安全：

```php
echo htmlspecialchars($userInput, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
```

富文本用 HTMLPurifier，不手写白名单正则。

---

## 路径穿越

通用原则见 engineering.md（拼接后校验最终路径在允许目录内）。PHP 实现：

```php
$base = realpath($uploadDir);
$target = realpath($base . '/' . $userPath);
if ($target === false || !str_starts_with($target, $base . DIRECTORY_SEPARATOR)) {
    throw new PathTraversalException($userPath);
}
```

禁止用 `..` 拼接绕过 base 目录；`realpath` 解析软链接后再做前缀校验。

---

## CSRF

改变状态的请求（POST/PUT/PATCH/DELETE）校验 CSRF Token，常数时间比较防时序攻击：

```php
if (!hash_equals($_SESSION['csrf_token'], $requestToken)) {
    throw new CsrfException();
}
```

JWT/API Key 认证（无 Cookie）的 API 可豁免。这是 PHP（同步 Cookie 会话场景）特有的关注点。

---

## 密码

通用原则见 engineering.md（bcrypt cost≥12、rehash）。PHP 实现：

```php
// 存储
$hash = password_hash($plain, PASSWORD_BCRYPT, ['cost' => 12]);
// 验证
password_verify($plain, $storedHash);
// cost 变更后重新哈希
if (password_needs_rehash($storedHash, PASSWORD_BCRYPT, ['cost' => 12])) { ... }
```

需要 Argon2id 用 `PASSWORD_ARGON2ID`（PHP 7.3+）。

---

## 敏感数据

通用原则见 engineering.md。PHP 脱敏实现：

```php
// ❌
$this->logger->info('Login', ['password' => $request->password]);
// ✅
$this->logger->info('Login success', ['userId' => $user->id]);

// 手机号脱敏
substr($phone, 0, 3) . '****' . substr($phone, -4);
```

---

## 文件上传

通用原则见 engineering.md（MIME 探测、大小限制、随机名、目录隔离、路径校验）。PHP 实现：

```php
// 用 finfo 校验真实 MIME，不信任 Content-Type 头
$finfo = new finfo(FILEINFO_MIME_TYPE);
$mimeType = $finfo->file($uploadedFile->getTempName());
if (!in_array($mimeType, ['image/jpeg', 'image/png', 'image/webp'], true)) {
    throw new InvalidFileTypeException($mimeType);
}
// 限制大小 + 重命名为随机文件名，不用原始文件名
$filename = bin2hex(random_bytes(16)) . '.' . $extension;
```

---

## HTTP 安全头

通用原则见 engineering.md。PHP 注入实现：

```php
$response->headers->set('X-Content-Type-Options', 'nosniff');
$response->headers->set('X-Frame-Options', 'DENY');
$response->headers->set('Referrer-Policy', 'strict-origin-when-cross-origin');
$response->headers->set('Content-Security-Policy', "default-src 'self'; script-src 'self'");
```

---

## 配置与密钥

通用原则见 engineering.md（环境变量注入、`.env` gitignore、不打镜像层）。PHP 用 Symfony/Laravel 的 `.env` + 配置组件，禁止把密钥写进提交的配置文件：

```php
// config/services.php
return [
    'jwt_secret' => $_ENV['JWT_SECRET'],
    'db_url' => $_ENV['DATABASE_URL'],
];
```

---

## 依赖安全

通用原则见 engineering.md。PHP 用 `composer audit`，CI 强制运行，高危漏洞（CVSS ≥ 7.0）阻断构建；`composer.lock` 必须提交。

---

## 错误响应

通用原则见 engineering.md（堆栈只进日志，客户端收统一错误码）。PHP 实现：

```php
// ✅
return new JsonResponse(['code' => 500, 'message' => '服务内部错误'], 500);
// ❌
return new JsonResponse(['error' => $exception->getTraceAsString()], 500);
```

`APP_DEBUG=false`（生产）时框架错误处理器必须屏蔽调试信息。

---

## 禁止行为

* ❌ SQL 拼接、原始输出用户输入到 HTML、字符串拼模板（SSTI）
* ❌ `unserialize()` 反序列化不可信数据（无 `allowed_classes` 白名单）
* ❌ `system`/`exec`/`shell_exec`/`passthru` 传入用户输入
* ❌ MD5/SHA1 存密码、硬编码密钥
* ❌ 日志输出敏感字段、信任原始文件名/Content-Type、未校验路径穿越
* ❌ 生产环境暴露错误堆栈、`APP_DEBUG=true` 上生产
* ❌ `eval()` 传入用户输入
* ❌ `@` 错误抑制符掩盖安全问题
