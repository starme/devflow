---
description: FastAPI 项目级规范模板
paths: ["**/*.py"]
alwaysApply: false
---

# FastAPI 项目级规范模板

适用于 FastAPI 项目。语言级规范（命名、类型注解、错误处理、测试、安全）见 `~/.claude/rules/backend/python/` 与 `~/.claude/rules/engineering.md`，本模板只讲 FastAPI 特有约定。

---

## 项目结构

官方推荐「bigger applications」结构，按业务模块拆 `routers/`：

```
project/
├── pyproject.toml
├── app/
│   ├── __init__.py
│   ├── main.py              # create_app + include_router
│   ├── core/
│   │   ├── config.py        # Settings (pydantic-settings)
│   │   ├── security.py      # JWT/密码
│   │   └── deps.py          # 公共依赖
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py          # 跨模块依赖（DB session、当前用户）
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py    # 聚合子路由
│   │       └── endpoints/
│   │           ├── users.py
│   │           └── orders.py
│   ├── models/              # SQLAlchemy ORM
│   ├── schemas/             # Pydantic 请求/响应模型
│   ├── services/           # 业务逻辑层（核心）
│   ├── crud/               # 数据访问层
│   └── internal/           # 内部/管理端接口
└── tests/
```

* 路由只做参数绑定与调用 service，禁止在 endpoint 写业务逻辑
* `services/` 是核心测试层，依赖通过构造函数注入便于 Mock

---

## 应用实例与生命周期

用工厂函数创建 app，`lifespan` 管理启动/关闭（DB 连接池、Redis、后台任务）：

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：初始化连接池
    yield
    # 关闭：释放资源

def create_app() -> FastAPI:
    app = FastAPI(title="...", lifespan=lifespan)
    app.include_router(api_router, prefix="/api/v1")
    return app

app = create_app()
```

禁止 `@app.on_event("startup")`（已废弃，用 `lifespan`）。

---

## 配置

用 `pydantic-settings` 集中管理，启动校验（通用原则见 engineering.md 安全底线·配置与密钥）：

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_")
    database_url: str
    jwt_secret: str
    debug: bool = False

settings = Settings()
```

通过依赖注入访问，禁止在模块顶层直接 import settings 进业务逻辑。

---

## 依赖注入（FastAPI 核心）

* 依赖用 `Depends` 声明，FastAPI 自动解析与缓存（同一请求内同依赖只执行一次）
* 公共依赖（DB session、当前用户、分页参数）放 `api/deps.py`
* 依赖可嵌套，复用而非复制

```python
from fastapi import Depends

def get_db_session() -> AsyncSession: ...
def get_current_user(token: str = Depends(oauth2_scheme), db = Depends(get_db_session)) -> User: ...

@router.get("/user/{id}")
def get_user(id: int, user: User = Depends(get_current_user)):
    ...
```

---

## 异步与同步

* 路由默认 `async def`；IO 必须用异步库（`asyncpg`/`SQLAlchemy async`/`httpx`/`aiofiles`）
* 同步阻塞调用放 `run_in_threadpool`，禁止在 `async def` 中直接调用
* CPU 密集任务放后台（`BackgroundTasks` 或外部队列），不阻塞事件循环

---

## 请求/响应模型

用 Pydantic v2（详见语言级 api.md）。响应用 `response_model` 声明，FastAPI 自动过滤未声明字段：

```python
@router.post("/user/create", response_model=UserResp, status_code=201)
def create_user(req: CreateUserReq, db = Depends(get_db_session)):
    ...
```

---

## 鉴权

用 `OAuth2PasswordBearer` + 依赖注入统一校验（通用原则见 engineering.md + python/security.md）：

```python
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    # 校验 JWT，返回用户或抛 401
    ...
```

公开接口与鉴权接口分路由声明，禁止混用。

---

## 错误处理

业务异常继承统一基类，全局异常处理器捕获后按错误信封返回（详见语言级 api.md）：

```python
@app.exception_handler(BizError)
async def biz_error_handler(request, exc: BizError):
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code, "message": exc.message},
    )
```

生产环境关闭 `debug=True`。

---

## 测试

用 `httpx.AsyncClient`（详见语言级 testing.md）。`TestClient` 用于同步测试，`AsyncClient` 用于 async：

```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_create_user(client: AsyncClient):
    resp = await client.post("/api/v1/user/create", json={"name": "Alice"})
    assert resp.status_code == 201
```

---

## 禁止行为

* ❌ endpoint 写业务逻辑、`@app.on_event` 废弃 API
* ❌ async 中调用阻塞 IO、模块顶层直接用 settings
* ❌ 不声明 `response_model` 导致响应字段泄露
* ❌ 公开与鉴权接口混用路由、生产开 debug
