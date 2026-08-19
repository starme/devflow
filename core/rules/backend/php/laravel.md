---
description: Laravel 框架专属规范（项目级模板）
paths: ["**/*.php"]
alwaysApply: false
---

# Laravel 开发规范

复制到项目 `.claude/rules/` 使用。与用户级 `code-style.md`/`security.md`/`testing.md`/`api.md` 配合，本文件只讲 Laravel 独有内容。

Laravel **11.x**，PHP **8.2+**。

---

## 路由

API 路由放 `routes/api.php`，Web 路由放 `routes/web.php`。用 `Route::apiResource` 代替手动注册 CRUD，按模块分组挂中间件：

```php
Route::prefix('v1')->middleware(['api', 'auth:sanctum'])->group(function () {
    Route::apiResource('users', UserController::class);
    // 非标准操作用子路由
    Route::post('users/{user}/activate', [UserController::class, 'activate']);
});

// 公开接口
Route::prefix('v1')->group(function () {
    Route::post('auth/login', [AuthController::class, 'login']);
});
```

禁止在 `routes/web.php` 定义 API 接口。

---

## Controller

只负责 HTTP 层：接收请求、调 Service、返回响应。用路由模型绑定，禁止手动查询：

```php
final class UserController extends Controller
{
    public function __construct(
        private readonly UserService $userService,
    ) {}

    public function store(CreateUserRequest $request): UserResource {
        $user = $this->userService->create($request->validated());
        return (new UserResource($user))->response()->setStatusCode(201);
    }

    public function show(User $user): UserResource {  // 路由模型绑定
        return new UserResource($user);
    }

    public function destroy(User $user): Response {
        $this->userService->delete($user);
        return response()->noContent();
    }
}
```

* 单个 Controller 方法 ≤ 10 行
* 禁止 Controller 直接 `DB::` 或 Eloquent 查询

---

## Form Request（输入校验）

校验通过 Form Request，不在 Controller：

```php
final class CreateUserRequest extends FormRequest
{
    public function rules(): array {
        return [
            'name'     => ['required', 'string', 'max:50'],
            'email'    => ['required', 'email', 'unique:users,email'],
            'password' => ['required', 'string', 'min:8', 'max:72'],
        ];
    }
}
```

---

## API Resource（响应格式）

禁止直接返回 Model 实例，用 Resource 统一格式化：

```php
final class UserResource extends JsonResource
{
    public function toArray(Request $request): array {
        return [
            'id'        => $this->id,
            'name'      => $this->name,
            'email'     => $this->email,
            'status'    => $this->status,
            'createdAt' => $this->created_at->toRfc3339String(),
        ];
    }
}
```

---

## Eloquent 模型

```php
final class User extends Model
{
    use HasFactory, SoftDeletes;

    protected $fillable = ['name', 'email', 'status'];   // 禁用 $guarded = []
    protected $hidden   = ['password', 'remember_token'];
    protected $casts    = ['email_verified_at' => 'datetime', 'status' => UserStatus::class];

    public function orders(): HasMany {
        return $this->hasMany(Order::class);
    }

    // 查询 Scope 复用条件
    public function scopeActive(Builder $query): Builder {
        return $query->where('status', UserStatus::Active);
    }
}
```

* 必须声明 `$fillable`，**禁止 `$guarded = []`**
* 敏感字段加 `$hidden`
* 用 `$casts` 自动转换，不在业务代码手动转
* 模型只定义属性/关联/Scope，**不写业务逻辑**

---

## Service 层

业务逻辑集中 Service，依赖注入 Repository 接口：

```php
final class UserService
{
    public function __construct(
        private readonly UserRepositoryInterface $userRepository,
        private readonly LoggerInterface $logger,
    ) {}

    public function create(array $data): User {
        $data['password'] = Hash::make($data['password']);
        $user = $this->userRepository->create($data);
        event(new UserCreated($user));
        $this->logger->info('User created', ['userId' => $user->id]);
        return $user;
    }
}
```

---

## Repository 模式

Service 依赖接口，实现绑定在 ServiceProvider：

```php
interface UserRepositoryInterface {
    public function findById(int $id): ?User;
    public function paginate(int $perPage, array $filters): LengthAwarePaginator;
}

final class EloquentUserRepository implements UserRepositoryInterface {
    public function paginate(int $perPage, array $filters): LengthAwarePaginator {
        return User::query()
            ->when(isset($filters['status']), fn ($q) => $q->where('status', $filters['status']))
            ->latest()->paginate($perPage);
    }
}

// ServiceProvider
$this->app->bind(UserRepositoryInterface::class, EloquentUserRepository::class);
```

---

## 迁移

```php
return new class extends Migration {
    public function up(): void {
        Schema::create('users', function (Blueprint $table) {
            $table->id();
            $table->string('name', 50);
            $table->string('email', 100)->unique();
            $table->string('status', 20)->default('inactive');
            $table->timestamps();
            $table->softDeletes();
            $table->index('status');
        });
    }
    public function down(): void {
        Schema::dropIfExists('users');
    }
};
```

* 必须 `down()`，生产**禁止改已执行迁移**（新建迁移）
* 字段指定长度，不用 `string()` 默认长度
* 外键显式定义

---

## 队列

耗时操作入队列。Job 类声明重试参数：

```php
final class SendWelcomeEmail implements ShouldQueue
{
    use Dispatchable, InteractsWithQueue, Queueable, SerializesModels;

    public int $tries   = 3;
    public int $timeout = 30;
    public int $backoff = 60;

    public function __construct(private readonly User $user) {}

    public function handle(MailService $mailService): void {
        $mailService->sendWelcome($this->user);
    }

    public function failed(\Throwable $e): void {
        Log::error('Failed to send welcome email', ['userId' => $this->user->id, 'exception' => $e->getMessage()]);
    }
}

SendWelcomeEmail::dispatch($user);
SendWelcomeEmail::dispatch($user)->delay(now()->addMinutes(5));
```

---

## 事件

```php
final class UserCreated {
    public function __construct(public readonly User $user) {}
}

// EventServiceProvider
protected $listen = [
    UserCreated::class => [
        SendWelcomeEmailListener::class,
        CreateUserProfileListener::class,
    ],
];
```

---

## 测试（Laravel 补充）

用 `RefreshDatabase` + Factory：

```php
class CreateUserTest extends TestCase
{
    use RefreshDatabase;

    public function test_user_can_be_created(): void {
        $response = $this->postJson('/api/v1/users', [
            'name' => 'Alice', 'email' => 'alice@example.com', 'password' => 'Password123!',
        ]);

        $response->assertStatus(201)
            ->assertJsonStructure(['data' => ['id', 'name', 'email', 'createdAt']]);
        $this->assertDatabaseHas('users', ['email' => 'alice@example.com']);
    }

    public function test_duplicate_email_returns_422(): void {
        User::factory()->create(['email' => 'alice@example.com']);
        $this->postJson('/api/v1/users', ['name' => 'Alice', 'email' => 'alice@example.com', 'password' => 'Password123!'])
            ->assertStatus(422)->assertJsonValidationErrors(['email']);
    }
}

User::factory()->count(10)->create(['status' => 'active']);
User::factory()->banned()->create();  // Factory State
```

---

## 禁止行为

* ❌ Controller 直接 `DB::` 或 Eloquent 查询
* ❌ 模型写业务逻辑（发邮件、调外部 API）
* ❌ `$guarded = []`（用 `$fillable`）
* ❌ 直接返回 Model 实例（用 API Resource）
* ❌ 同步请求执行耗时操作（入队列）
* ❌ `routes/web.php` 定义 API 接口
* ❌ 修改已执行迁移文件
* ❌ 循环中 N+1 查询（用 `with()` 预加载）
