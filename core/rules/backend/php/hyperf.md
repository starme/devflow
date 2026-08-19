---
description: Hyperf 框架专属规范（项目级模板）
paths: ["**/*.php"]
alwaysApply: false
---

# Hyperf 开发规范

复制到项目 `.claude/rules/` 使用。与用户级 `code-style.md`/`security.md`/`testing.md`/`api.md` 配合，本文件只讲 Hyperf 独有内容。

Hyperf **3.1+**，PHP **8.1+**，运行于 **Swoole 5.x** 或 **Swow**。

---

## 协程安全（核心约束）

Hyperf 基于协程，**所有代码必须协程安全**——这是与传统 PHP 最大区别。

请求级状态必须存协程上下文（`Context`），**禁止**存静态属性/全局变量（协程间共享会数据污染）：

```php
use Hyperf\Context\Context;

// ✅
class UserService {
    public function getCurrentUser(): ?User {
        return Context::get('current_user');
    }
    public function setCurrentUser(User $user): void {
        Context::set('current_user', $user);
    }
}

// ❌ 静态属性存请求状态
class UserService {
    private static User $currentUser;
}
```

---

## 注解路由与 DI

注解驱动，DI 容器管理依赖，**禁止手动 `new` 服务类**：

```php
#[Controller(prefix: '/api/v1/users')]
#[Middleware(AuthMiddleware::class)]
class UserController
{
    public function __construct(
        private readonly UserService $userService,
    ) {}

    #[GetMapping(path: '')]
    public function index(IndexUserRequest $request): array {
        return $this->userService->paginate($request->validated());
    }

    #[GetMapping(path: '{id:\d+}')]
    public function show(int $id): array {
        return $this->userService->getUserById($id);
    }
}
```

公开接口放独立 Controller，不混中间件。属性注入仅用于 Trait/特殊场景：

```php
#[Inject]
private UserService $userService;
```

---

## 请求验证（FormRequest）

```php
class CreateUserRequest extends FormRequest
{
    public function rules(): array {
        return [
            'name'     => 'required|string|max:50',
            'email'    => 'required|email|unique:users,email',
            'password' => 'required|string|min:8|max:72',
        ];
    }
}
```

---

## 数据库（连接池）

用 Hyperf ORM 或 DBAL，**禁止在协程中复用非协程安全的 DB 连接**（如原生 PDO）。连接池自动管理，无需手动释放：

```php
$users = User::query()->where('status', 'active')->paginate(20);

// 事务
use Hyperf\DbConnection\Db;
Db::transaction(function () use ($data) {
    $user  = User::create($data['user']);
    $order = Order::create(['user_id' => $user->id, ...$data['order']]);
    return [$user, $order];
});
```

---

## 缓存（注解）

```php
#[Cacheable(prefix: 'user', value: '#{id}', ttl: 3600)]
public function getUserById(int $id): array {
    return User::findOrFail($id)->toArray();
}

#[CacheEvict(prefix: 'user', value: '#{user.id}')]
public function updateUser(User $user, array $data): User {
    $user->update($data);
    return $user;
}
```

---

## 异步任务

Job 传 **ID 不传完整对象**（序列化问题）：

```php
class SendWelcomeEmailJob extends Job
{
    public int $maxAttempts = 3;

    public function __construct(
        private readonly int $userId,
    ) {}

    public function handle(): void {
        $user = User::findOrFail($this->userId);
        // 发邮件...
    }
}

$driver = $container->get(DriverFactory::class)->get('default');
$driver->push(new SendWelcomeEmailJob($user->id));
```

---

## 事件

```php
// 事件
class UserCreatedEvent {
    public function __construct(public readonly User $user) {}
}

// 监听器
#[Listener]
class SendWelcomeEmailListener implements ListenerInterface {
    public function listen(): array {
        return [UserCreatedEvent::class];
    }
    public function process(object $event): void { /* $event->user */ }
}

// 触发
$container->get(EventDispatcherInterface::class)->dispatch(new UserCreatedEvent($user));
```

---

## 协程并发

```php
use Hyperf\Coroutine\Parallel;

$parallel = new Parallel();
$parallel->add(fn () => $this->userRepository->findById($userId));
$parallel->add(fn () => $this->orderRepository->findByUserId($userId));
[$user, $orders] = $parallel->wait();
```

---

## AOP 切面

用于横切关注点（日志/权限/性能），避免业务代码重复：

```php
#[Aspect]
class LoggingAspect extends AbstractAspect
{
    public array $annotations = [Loggable::class];

    public function process(ProceedingJoinPoint $joinPoint): mixed {
        $start  = microtime(true);
        $result = $joinPoint->process();
        Log::info('Method executed', [
            'class'  => $joinPoint->className,
            'method' => $joinPoint->methodName,
            'costMs' => round((microtime(true) - $start) * 1000, 2),
        ]);
        return $result;
    }
}
```

---

## 异常处理

在 `ExceptionHandler` 统一处理，**不在 Controller try/catch**：

```php
class AppExceptionHandler extends ExceptionHandler
{
    public function handle(Throwable $e, ResponseInterface $response): ResponseInterface {
        if ($e instanceof ValidationException) {
            return $response->json(['code' => 422, 'message' => '参数校验失败', 'errors' => $e->errors()])
                ->withStatus(422);
        }
        if ($e instanceof NotFoundException) {
            return $response->json(['code' => 404, 'message' => $e->getMessage()])->withStatus(404);
        }
        $this->logger->error('Unhandled exception', ['exception' => $e]);
        return $response->json(['code' => 500, 'message' => '服务内部错误'])->withStatus(500);
    }

    public function isValid(Throwable $e): bool { return true; }
}
```

---

## 测试（Hyperf 补充）

```php
use Hyperf\Testing\TestCase;

class UserServiceTest extends TestCase
{
    protected function setUp(): void {
        parent::setUp();
        Context::destroy('current_user');  // 清理上下文防协程状态污染
    }

    public function testGetUserById(): void {
        $service = $this->getContainer()->get(UserService::class);  // DI 容器
        $user    = User::factory()->create();
        $this->assertSame($user->id, $service->getUserById($user->id)['id']);
    }
}
```

---

## 禁止行为

* ❌ 静态属性/全局变量存请求级状态（协程污染）
* ❌ 协程中用非协程安全扩展（原生 PDO 不走连接池）
* ❌ `sleep()` / `usleep()`（阻塞协程，用 `Coroutine::sleep()`）
* ❌ 手动 `new` 服务类
* ❌ 异步 Job 传完整对象（传 ID）
* ❌ 测试后不清理 Context
