---
description: PHP 代码风格规范（通用）
paths: ["**/*.php"]
alwaysApply: false
---

# PHP 代码风格规范

适用于所有 PHP 后端服务，PHP 最低版本 **8.1**。遵循 PSR-1/4/12。

安全相关见 `security.md`，测试见 `testing.md`，API 设计见 `api.md`。

---

## 文件头（强制顺序）

```php
<?php

declare(strict_types=1);

namespace App\Service;

use App\Repository\UserRepository;   // 本项目
use App\Exception\UserNotFoundException;
use RuntimeException;                 // 第三方/内置

class UserService {}
```

顺序：`declare` → `namespace` → `use`（本项目与第三方之间空行分隔，各组内字母序）。

* 纯 PHP 文件**不加** `?>` 结束标签
* 禁止短标签 `<?` / `<?=`（模板除外）
* `declare(strict_types=1)` 必须有

---

## PSR-12 要点

* 4 空格缩进，禁止 Tab；单行 ≤ 120 字符
* 类/方法开括号 `{` 独占一行
* 控制结构开括号**不**换行，关键字后有空格，**不省略大括号**（即使单行）

```php
// ✅
if ($condition) {
    doSomething();
} elseif ($other) {
    doOther();
}

// ❌ 省略大括号
if ($flag) return true;
```

* 多接口换行：

```php
class Foo extends Bar implements
    FooInterface,
    BarInterface
{
}
```

---

## 命名

| 元素 | 规范 | 示例 |
|------|------|------|
| 类/接口/Trait/Enum | PascalCase | `UserService` |
| 方法/函数/变量 | camelCase | `getUserById`, `$userId` |
| 常量 | SCREAMING_SNAKE_CASE | `MAX_RETRY_COUNT` |
| 文件名 | 与类名一致 | `UserService.php` |

* 布尔返回值用 `is`/`has`/`can` 前缀：`isActive()`、`hasPermission()`
* 禁止无意义命名：`$data`、`$info`、`$tmp`、`$a`

---

## 类型声明（强制）

所有方法的**参数和返回值**必须有类型声明：

```php
// ✅
public function findById(int $id): ?User {}
public function process(int|string $id): void {}

// ❌
public function findById($id) {}
```

善用现代类型特性：

```php
// PHP 8.1+ 枚举
enum Status: string {
    case Active = 'active';
    case Banned = 'banned';
}

// PHP 8.1+ 只读属性（DTO 用构造属性提升）
final class UserDto {
    public function __construct(
        public readonly int $id,
        public readonly string $name,
    ) {}
}

// match 优先于复杂 switch
$label = match($status) {
    Status::Active => '活跃',
    Status::Banned => '封禁',
};
```

---

## 构造函数注入

依赖通过构造函数注入，禁止在类内 `new` 外部依赖：

```php
// ✅
class OrderService {
    public function __construct(
        private readonly OrderRepository $orderRepository,
        private readonly LoggerInterface $logger,
    ) {}
}
```

---

## 禁止行为

* ❌ 短标签 `<?` / `<?=`（模板除外）
* ❌ 省略类型声明或 `declare(strict_types=1)`
* ❌ 省略控制结构大括号
* ❌ `new` 硬编码外部依赖
* ❌ `var_dump` / `print_r` / `@` 错误抑制符提交入库
* ❌ 全局变量（`global $db`）、静态方法滥用
