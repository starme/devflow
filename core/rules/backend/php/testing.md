---
description: PHP 测试规范
paths: ["**/*Test.php"]
alwaysApply: false
---

# PHP 测试规范

适用于所有 PHP 后端服务，测试框架 **PHPUnit 10+**。通用测试哲学（TDD、覆盖率 ≥ 80%、bug fix 附复现测试、单元测试禁连生产 DB）见 `~/.claude/rules/engineering.md`。

---

## 分层策略

| 层 | 测试对象 | 外部依赖 |
|----|---------|---------|
| Service/Domain | 核心业务逻辑（主要测试层） | Mock Repository/外部服务 |
| Repository | 数据库操作 | 测试数据库（真实 DB） |
| Controller | HTTP 请求/响应绑定 | Mock Service |
| Integration | 跨层完整流程 | 测试容器/内存数据库 |

重点测 Service 层，覆盖率 ≥ 80%。

---

## 命名

```php
// 测试类：被测类 + Test
class UserServiceTest extends TestCase {}

// 测试方法：test{方法名}_{场景描述}
public function testGetUserById_ReturnsUser(): void {}
public function testCreateUser_ThrowsWhenEmailDuplicated(): void {}
```

---

## 标准单元测试结构（Arrange/Act/Assert）

```php
class UserServiceTest extends TestCase
{
    private UserService $service;
    private UserRepository&MockObject $repository;

    protected function setUp(): void
    {
        $this->repository = $this->createMock(UserRepository::class);
        $this->service    = new UserService($this->repository);
    }

    public function testGetUserById_ReturnsUser(): void
    {
        // Arrange
        $this->repository->expects($this->once())
            ->method('findById')->with(1)
            ->willReturn(new User(id: 1, name: 'Alice', email: 'alice@example.com'));

        // Act
        $result = $this->service->getUserById(1);

        // Assert
        $this->assertSame(1, $result->id);
    }
}
```

---

## 数据提供者（表驱动）

优先用 `#[DataProvider]` 覆盖边界值，避免重复测试方法：

```php
public static function provideInvalidEmails(): array
{
    return [
        'no @'      => ['userexample.com', 'missing @ sign'],
        'no domain' => ['user@', 'missing domain'],
        'empty'     => ['', 'empty string'],
    ];
}

#[DataProvider('provideInvalidEmails')]
public function testIsValidEmail_RejectsInvalidEmails(string $email, string $reason): void
{
    $this->assertFalse(EmailValidator::isValid($email), $reason);
}
```

---

## Mock 规范

用 PHPUnit 内置 Mock，不引入额外库（复杂交互可用 Mockery）：

```php
// 验证调用次数
$this->repository->expects($this->once())
    ->method('save')->with($this->isInstanceOf(User::class));

// 模拟异常
$this->repository->method('findById')
    ->willThrowException(new DatabaseException('Connection lost'));

// 连续调用返回不同值
$this->repository->method('findById')
    ->willReturnOnConsecutiveCalls(new User(1, 'Alice'), null);
```

禁止手写 Fake 实现代替 Mock（维护成本高）。

---

## Repository 测试（集成）

用真实数据库，禁止 Mock DB：

```php
protected function setUp(): void
{
    $this->pdo = new PDO('sqlite::memory:');
    $this->pdo->exec(file_get_contents(__DIR__ . '/../../schema.sql'));
    $this->repository = new UserRepository($this->pdo);
}

protected function tearDown(): void
{
    $this->pdo->exec('DELETE FROM users');
}
```

---

## 测试隔离

* 每个用例独立运行，不依赖其他测试状态
* 用 `setUp()`/`tearDown()` 初始化和清理
* 集成测试用事务回滚，不污染测试间状态

```php
protected function setUp(): void
{
    parent::setUp();
    $this->pdo->beginTransaction();
}

protected function tearDown(): void
{
    $this->pdo->rollBack();
    parent::tearDown();
}
```

---

## 断言

```php
$this->assertSame(1, $result->id);           // 值+类型
$this->assertEquals('Alice', $result->name); // 仅值
$this->expectException(UserNotFoundException::class);
$this->expectExceptionMessage('User not found');
```

---

## CI 配置（GitHub Actions）

```yaml
name: PHP CI
on:
  pull_request:
  push:
    branches: ["main"]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: shivammathur/setup-php@v2
        with:
          php-version: "8.1"
          coverage: xdebug
      - run: composer install --no-interaction --prefer-dist
      - run: composer audit
      - run: vendor/bin/php-cs-fixer fix --dry-run --diff
      - run: vendor/bin/phpstan analyse
      - run: vendor/bin/phpunit --coverage-clover coverage/clover.xml
      - name: Check coverage
        run: |
          COVERAGE=$(php -r "
            \$xml = simplexml_load_file('coverage/clover.xml');
            \$m = \$xml->project->metrics;
            echo round((int)\$m['coveredstatements'] / (int)\$m['statements'] * 100);
          ")
          echo "Coverage: ${COVERAGE}%"
          [ "$COVERAGE" -ge 80 ] || (echo "Coverage below 80%" && exit 1)
```

---

## 本地执行

```bash
vendor/bin/phpunit                          # 全部测试
vendor/bin/phpunit --testsuite Unit         # 仅单元测试
vendor/bin/phpunit --coverage-text          # 显示覆盖率
```

---

## 禁止行为

* ❌ 单元测试连真实数据库
* ❌ 测试用例间共享可变状态
* ❌ 手写 Mock 实现
* ❌ 测试方法不声明返回类型 `void`
* ❌ 一个测试方法断言多个不相关行为
* ❌ `sleep()` 等待异步操作（Mock 时间依赖）
