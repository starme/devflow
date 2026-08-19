---
description: Python 代码风格规范
paths: ["**/*.py"]
alwaysApply: false
---

# Python 代码风格规范

适用于所有 Python 代码，与 Web 框架（FastAPI / Flask / Django）和 IO 模型（async / sync）无关。框架专属约定（路由声明、依赖注入、ORM 用法）见项目级框架规范。

---

## 1. Python 版本与项目结构

* 目标版本 Python 3.10+，可用 `match/case`、类型联合 `X | Y`、参数化泛型 `list[int]`
* 用 `pyproject.toml` 管理项目元数据与依赖，禁止用 `requirements.txt` 散管生产依赖
* 虚拟环境与依赖锁：`uv` / `poetry` / `pip-tools` 任选其一，**禁止把 `venv/` `.venv/` 提交进 git**
* 包布局遵循 `src/` 布局，避免开发态误导入未安装的包：

```
my_project/
├── pyproject.toml
├── src/my_project/
│   ├── __init__.py
│   ├── api/
│   ├── service/
│   ├── repository/
│   └── config.py
└── tests/
```

---

## 2. 命名规范

* 变量/函数/方法：`snake_case`
* 类/异常：`PascalCase`
* 常量：`SCREAMING_SNAKE_CASE`
* 私有：前缀 `_`；**禁止**双下划线 `__` 名称改写（除非确有命名冲突需求）
* 模块名：全小写，单词，无下划线优先；禁止无意义命名（`a`、`tmp`、`data`、`info`、`utils` 作为唯一名称）
* 布尔变量/函数用 `is_`/`has_`/`can_`/`should_` 前缀

```python
# ❌
def calc(x, y):
    d = x * 86400
    return d

# ✅
SECONDS_PER_DAY = 86400

def to_seconds(days: int) -> int:
    return days * SECONDS_PER_DAY
```

---

## 3. 类型注解（强制）

> **严于权威**：PEP 484 与 Google Style Guide 3.19 不强制全部注解、允许 `Any` 作逃生舱；本项目要求全量注解并禁裸 `Any`，以换取 mypy strict 的可维护性。权衡是注解成本更高。

* 所有函数签名必须标注参数与返回类型
* **例外**：`self` / `cls` 首参无需注解；`__init__` 无需标注返回类型（`None` 是唯一合法值，显式标注冗余）
* 公共类属性标注类型
* 用 `from __future__ import annotations` 推迟注解求值，避免循环导入与前向引用问题
* 容器用泛型：`list[int]`、`dict[str, User]`，不用裸 `list` / `dict`
* 可空用 `X | None`（3.10+），不用 `Optional[X]`
* 禁止裸 `Any`；确需类型逃生舱用 `TypeVar` 或在注释说明原因

```python
from __future__ import annotations

def get_user_by_id(user_id: int) -> User | None:
    ...

class UserService:
    def __init__(self, repo: UserRepository):  # self 不注解，无返回类型
        self._repo = repo

    @classmethod
    def from_config(cls, config: Config) -> cls:  # cls 不注解，返回用 Self
        ...
```

---

## 4. 函数与控制流

> **严于权威**：Google Style Guide 3.18 不设硬限、仅建议"超过 40 行思考是否拆分"；本项目设 50 行硬限，超即拆。可接受偶尔超长但需注释说明理由。

* 单一职责：一个函数用一句话能描述
* 单函数 ≤ 50 行，超过即拆分
* 嵌套不超过 3 层，优先 early return 减少缩进
* 函数参数 > 3 个时用 `dataclass` / `TypedDict` / `Pydantic` 模型传参
* 禁止可变默认参数（经典坑）：

```python
# ❌ 默认值在函数定义时求值，多次调用共享同一对象
def append_item(item, target: list[int] = []):
    target.append(item)
    return target

# ✅
def append_item(item, target: list[int] | None = None) -> list[int]:
    target = target if target is not None else []
    target.append(item)
    return target
```

* Lambda 只用于即时使用（如 `sorted(items, key=lambda x: x.age)`），禁止赋值给变量——赋值场景一律用 `def`（Google 2.10：lambda 赋值无法赋名、无法复用、栈追踪不友好）：

```python
# ❌ 赋值给变量
get_name = lambda user: user.name

# ✅ 用 def，有名字、可复用、栈追踪清晰
def get_name(user: User) -> str:
    return user.name
```

---

## 5. 错误处理

* 禁止裸 `except:` 或 `except Exception:` 吞掉所有异常（除非在最外层兜底并记录日志后重新抛出或转业务错误）
* 捕获具体异常类型，异常信息必须含上下文
* 不要用异常控制正常业务流程
* 自定义业务异常继承自统一基类，区分用户错误（4xx）与系统错误（5xx）

```python
# ❌
try:
    do_something()
except Exception:
    pass

# ✅
try:
    result = parse_token(raw_token)
except JWTDecodeError as exc:
    raise InvalidTokenError(f"token 解析失败: {exc}") from exc
```

`raise ... from exc` 保留原始异常链，禁止裸 `raise` 丢失上下文。

---

## 6. 数据模型

* 入参校验/序列化用 `Pydantic v2`（框架无关，FastAPI 原生支持；其他框架可独立使用）
* 内部领域模型用 `dataclass`（`slots=True` 节省内存并禁止动态属性）
* 禁止用字典到处传递结构化数据，必须有类型定义

```python
from dataclasses import dataclass
from pydantic import BaseModel, Field

@dataclass(slots=True)
class User:
    id: int
    name: str

class CreateUserReq(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    age: int = Field(ge=0, le=150)
```

---

## 7. 日志

* 用 `logging` 标准库或框架提供的结构化 logger，禁止 `print` 充当日志
* 日志字段必须语义化，用 `%s` 占位符延迟格式化（避免日志级别不够时仍付出格式化开销）

```python
import logging

logger = logging.getLogger(__name__)

# ✅
logger.info("user login success", extra={"user_id": user_id})

# ❌
logger.info(f"user login success: {user_id}")
print(f"login: {user_id}")
```

---

## 8. 并发（async / sync 双模式）

### async 模式

* async 函数中禁止调用阻塞 IO，必须用异步等价库：`httpx` 替代 `requests`、`asyncpg` 替代 `psycopg`、`aiofiles` 替代 `open()`
* 阻塞调用必须放到 `asyncio.to_thread()` / 线程池
* 协程任务通过 `asyncio.TaskGroup` 管理（3.11+），禁止裸 `asyncio.create_task` 不持有引用（会被 GC 回收）
* 禁止 `asyncio.run()` 在已有事件循环中嵌套调用

```python
import asyncio

async def fetch_users(user_ids: list[int]) -> list[User]:
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(get_user(uid)) for uid in user_ids]
    return [t.result() for t in tasks]
```

### sync 模式

* 耗时 IO 用线程池 `concurrent.futures.ThreadPoolExecutor`，不要在请求处理线程直接阻塞
* 共享可变状态必须加锁（`threading.Lock`），优先用队列/通道传递数据

### 通用

* async 与 sync 混用时通过明确边界隔离：入口层（路由）统一 async 或统一 sync，禁止同一调用链中穿插阻塞调用
* 全局可变状态（缓存、连接池）用模块级单例，初始化放应用启动钩子，禁止请求时重复创建

---

## 9. 依赖管理

* 优先标准库；引入第三方库需在 PR 说明原因
* 锁文件（`uv.lock` / `poetry.lock`）必须提交，保证可复现构建
* 区分生产依赖与开发依赖（`[project.dependencies]` vs `[project.optional-dependencies]`）
* 禁止从 `main` 分支或未锁定版本安装：`pip install package`（无版本）只在探索时用

---

## 10. 注释与文档字符串

* 注释解释 **WHY**（为什么这样做），不解释 WHAT（代码已说明）
* 禁止注释掉的代码直接提交（用 git 管理版本）
* 公共模块/类/函数用 docstring：Google 风格或 reST 风格择一并保持一致
* 复杂算法、非显然业务规则必须加注释

```python
def split_batch(items: list[int], batch_size: int) -> list[list[int]]:
    """Split items into fixed-size batches.

    Why:下游 API 单次最多接收 batch_size 条，超限会被截断且无报错，
    故在客户端主动分批。
    """
    ...
```

---

## 11. 格式化与静态检查（强制）

提交前必须通过：

```bash
ruff format .            # 格式化（替代 black）
ruff check . --fix       # lint + 自动修复
mypy src/                # 类型检查
```

违反 ruff / mypy 的代码禁止合并。CI 强制运行以上三条。

### 基础 `pyproject.toml` 配置

```toml
[tool.ruff]
target-version = "py310"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "C4", "SIM", "RUF"]
ignore = ["E501"]  # 行长交由 formatter 处理

[tool.mypy]
python_version = "3.10"
strict = true
warn_return_any = true
disallow_untyped_defs = true
```

---

## 12. 禁止行为

* ❌ 可变默认参数
* ❌ 裸 `except:` / `except Exception: pass` 吞异常
* ❌ 函数签名无类型注解
* ❌ async 中调用阻塞 IO（`requests`、同步 `open()`、`time.sleep`）
* ❌ 用 `print` 输出日志
* ❌ 用字典传递结构化领域数据而无类型定义
* ❌ 单函数超过 50 行、嵌套超过 3 层
* ❌ 引入未锁定版本的依赖
