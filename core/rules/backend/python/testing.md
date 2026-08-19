---
description: Python 测试规范
paths: ["**/test_*.py", "**/tests/**/*.py", "**/*_test.py"]
alwaysApply: false
---

# Python 测试规范

适用于所有 Python 模块。框架专属测试（FastAPI 的 `TestClient`、Django 的 `TestCase`）见项目级框架规范。

---

## 1. 测试要求

* 新功能必须包含对应单元测试
* 核心业务逻辑覆盖率目标 ≥ 80%
* bug fix 必须附带复现该 bug 的测试用例
* 禁止在单元测试中连接生产数据库
* **先写测试，再写实现（TDD）**：测试必须先运行并失败，再写实现使其通过

---

## 2. 分层策略

| 层 | 测试对象 | 外部依赖 |
|----|---------|---------|
| 业务逻辑层（Service） | 核心业务规则（主要测试层） | Mock 依赖 |
| 数据访问层（Repository） | 数据库操作 | 测试数据库（真实 DB） |
| HTTP 层（Handler/View） | 请求/响应绑定 | Mock 业务层 |
| 集成测试 | 跨层完整流程 | 测试容器/内存数据库 |

重点测业务逻辑层，覆盖率 ≥ 80%。

---

## 3. 测试工具链

* 框架：`pytest`（禁止用 `unittest` 除非历史包袱）
* Mock：`pytest-mock`（封装 `unittest.mock`）+ `pytest-asyncio`（async 测试）
* 断言：直接用 `assert`，禁止用 `unittest` 的 `self.assertEqual`
- HTTP 层：FastAPI 用 `httpx.AsyncClient` / `TestClient`；Flask/Django 用各自 `test_client`
- 覆盖率：`pytest-cov`，目标 ≥ 80%

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.coverage.run]
source = ["src"]
branch = true

[tool.coverage.report]
fail_under = 80
```

---

## 4. 标准测试结构（sync）

依赖通过构造函数注入，测试时传入 Mock：

```python
from pytest_mock import MockerFixture
from my_project.service.user_service import UserService

def test_get_user_returns_user(mocker: MockerFixture) -> None:
    mock_repo = mocker.MagicMock()
    mock_repo.find_by_id.return_value = {"id": 1, "name": "Alice"}

    svc = UserService(mock_repo)
    user = svc.get_user(1)

    assert user.name == "Alice"
    mock_repo.find_by_id.assert_called_once_with(1)
```

---

## 5. 标准测试结构（async）

async 测试函数由 `pytest-asyncio` 驱动，`asyncio_mode = "auto"` 时无需装饰器：

```python
import pytest
from httpx import AsyncClient
from my_project.app import create_app

@pytest.mark.asyncio
async def test_login_returns_token() -> None:
    app = create_app()
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post("/user/login", json={"username": "alice", "password": "123456"})

    assert resp.status_code == 200
    assert "token" in resp.json()
```

---

## 6. 数据访问层测试

用真实数据库（禁止 Mock DB），推荐 `testcontainers`：

```python
import pytest
from testcontainers.postgres import PostgresContainer
from sqlalchemy import create_engine

@pytest.fixture(scope="session")
def db_engine():
    with PostgresContainer("postgres:16") as pg:
        engine = create_engine(pg.get_connection_url())
        yield engine

def test_user_repository_find_by_id(db_engine) -> None:
    repo = UserRepository(db_engine)
    user_id = repo.create(name="test")
    try:
        user = repo.find_by_id(user_id)
        assert user.name == "test"
    finally:
        repo.delete(user_id)
```

---

## 7. HTTP 层测试

只验 HTTP 层（状态码、响应结构），不测业务规则：

```python
def test_create_user_returns_201(mocker: MockerFixture) -> None:
    mock_svc = mocker.MagicMock()
    mock_svc.create_user.return_value = {"user_id": 1, "name": "Alice"}

    app = create_app(service=mock_svc)
    client = app.test_client()

    resp = client.post("/user/create", json={"name": "Alice", "age": 30})

    assert resp.status_code == 201
    assert resp.json()["userId"] == 1
```

---

## 8. 命名规范

* 测试文件：`test_<module>.py`
* 测试函数：`test_<func>_<scenario>`，描述被测场景：`test_create_user_duplicate_email` 优于 `test_create_user_2`
* 测试目录与源码目录镜像：`src/my_project/service/user_service.py` → `tests/service/test_user_service.py`

---

## 9. 参数化测试（优先使用）

替代手写循环，pytest 原生支持，失败时能定位具体用例：

```python
import pytest

@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("user@example.com", True),
        ("userexample.com", False),
        ("", False),
    ],
    ids=["standard", "missing_at", "empty"],
)
def test_validate_email(email: str, expected: bool) -> None:
    assert validate_email(email) is expected
```

---

## 10. Mock 规范

* 依赖外部系统（DB/HTTP/缓存）的单元测试必须 Mock
* 用 `mocker.patch` / `mocker.MagicMock`，禁止手写桩类充斥测试代码
* Mock 放 fixture，可复用
* 断言调用次数与参数：`mock.assert_called_once_with(...)`

```python
def test_send_welcome_email(mocker: MockerFixture) -> None:
    mock_mailer = mocker.patch("my_project.service.user_service.Mailer")
    svc = UserService(mocker.MagicMock(), mock_mailer.return_value)

    svc.register("alice@example.com")

    mock_mailer.return_value.send_welcome.assert_called_once_with("alice@example.com")
```

---

## 11. 集成测试

* 使用独立测试数据库，禁止污染开发/生产数据
* 推荐 `testcontainers` 启动临时容器（Postgres / Redis / RabbitMQ）
* 集成测试用 marker 隔离，默认不运行：

```python
# pyproject.toml
[tool.pytest.ini_options]
markers = ["integration: marks integration tests (deselect with '-m \"not integration\"')"]
```

```bash
pytest -m "not integration"   # 单元测试
pytest -m integration          # 集成测试
```

---

## 12. 测试隔离

* 每个用例独立运行，不依赖其他测试状态或执行顺序
* 用 fixture 的 `yield` 清理副作用；数据库测试用事务回滚
* 禁止测试间共享可变全局状态，必须用 fixture 重建
* 时间相关逻辑必须可注入（依赖 `datetime.now` 时用 `freezegun` 或注入时钟），禁止 `sleep` 等待

---

## 13. 本地执行（提交前必须通过）

```bash
ruff check tests/
pytest                       # 默认不含集成测试
pytest -m integration         # 单独跑集成
pytest --cov=src --cov-report=term-missing
```

---

## 14. CI 配置（GitHub Actions）

文件路径：`.github/workflows/python-ci.yml`

```yaml
name: Python CI
on:
  pull_request:
  push:
    branches: ["main"]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install uv
        run: pip install uv
      - name: Install deps
        run: uv sync --frozen
      - name: Lint
        run: |
          ruff check .
          ruff format --check .
      - name: Type check
        run: mypy src/
      - name: Test
        run: pytest --cov=src --cov-report=xml
      - uses: codecov/codecov-action@v4
```

---

## 15. 禁止行为

* ❌ 业务逻辑层测试连接真实数据库
* ❌ 手写桩类代替 Mock 库
* ❌ HTTP 层测试包含业务逻辑断言
* ❌ 测试用例之间共享可变状态、依赖执行顺序
* ❌ 用 `unittest.TestCase` + `self.assertEqual`（用 `pytest` + `assert`）
* ❌ `time.sleep()` 等待异步操作（Mock 时间或用 `pytest-asyncio` 显式 await）
* ❌ 裸 `print` 调试残留（用 `pytest -s` 或 logging）
