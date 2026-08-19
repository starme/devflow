---
description: Django 项目级规范模板
paths: ["**/*.py"]
alwaysApply: false
---

# Django 项目级规范模板

适用于 Django 项目。语言级规范（命名、类型注解、错误处理、测试、安全）见 `~/.claude/rules/backend/python/` 与 `~/.claude/rules/engineering.md`，本模板只讲 Django 特有约定。

---

## 项目结构

官方「project + apps」结构。config 包（settings/urls/wsgi/asgi）与业务 app 分离，每个 app 自治可复用：

```
project/
├── manage.py
├── pyproject.toml
├── config/                  # 项目配置包（原 mysite/）
│   ├── __init__.py
│   ├── settings/
│   │   ├── base.py
│   │   ├── dev.py
│   │   └── prod.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── apps/
│   └── users/               # 业务 app（自治）
│       ├── __init__.py
│       ├── apps.py          # AppConfig
│       ├── models.py
│       ├── views.py
│       ├── urls.py
│       ├── serializers.py   # DRF
│       ├── services.py      # 业务逻辑层（核心，非框架原生）
│       ├── admin.py
│       ├── migrations/
│       └── tests/
└── templates/
```

* config 包只放配置，不放业务
* 每个 app 一个职责，`INSTALLED_APPS` 用 `apps.users.apps.UsersConfig` 引 AppConfig
* 业务逻辑放 `services.py`（框架不强制但约定），view 不写业务

---

## 配置

settings 按环境拆分（base/dev/prod），`DJANGO_SETTINGS_MODULE` 环境变量切换。密钥与环境变量见 engineering.md 安全底线：

```python
# config/settings/base.py
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = False
DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", ...}}

# config/settings/dev.py
from .base import *
DEBUG = True
```

禁止在 settings 写硬编码密钥；用 `python-dotenv` 或环境变量注入。

---

## Models

* 每个模型一个表，字段语义化命名（snake_case）
* 用 `Meta` 内联类设排序、约束（`unique_together`/`constraints`）
* 跨模型业务逻辑放 `services.py` 或 model 方法，禁止在 view 里查

```python
class User(models.Model):
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "users"
        constraints = [models.UniqueConstraint(fields=["email"], name="uniq_email")]
```

迁移必须随代码提交（`makemigrations` 产物），CI 校验无未生成迁移。

---

## Views 与 DRF

DRF（Django REST Framework）做 API。view 用 `ViewSet` 或 `APIView`，序列化用 `Serializer`：

```python
class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
```

* 序列化器做字段校验（通用原则见 engineering.md 输入校验）
* 权限用 `permission_classes` 声明，公开与鉴权 view 分开
* 路由在 app 的 `urls.py` 注册，config/urls.py 用 `include` 聚合

---

## ORM 查询

* 禁止 SQL 拼接，用 ORM 或 `raw()` 参数化（通用原则见 engineering.md）
* 跨外键查询用 `select_related`（一对一/外键）或 `prefetch_related`（多对多/反向外键）防 N+1
* 大查询用 `iterator()` 或分页，禁止 `all()` 全量加载

```python
# ✅ 防 N+1
User.objects.select_related("profile").prefetch_related("orders").all()
```

---

## 鉴权

* 用 Django auth + DRF `IsAuthenticated` / 自定义 permission
* Session 场景 Django 自动防 CSRF；JWT 用 `djangorestframework-simplejwt`
* 密码用 `make_password`（底层 PBKDF2，见 engineering.md 密码原则）

---

## 异步视图

Django 3.1+ 支持 async views，但 ORM 仍是同步。async view 中禁止直接调 ORM（会阻塞），用 `sync_to_async` 包裹或放后台任务：

```python
from asgiref.sync import sync_to_async

async def my_view(request):
    user = await sync_to_async(User.objects.get)(pk=request.user.pk)
```

新项目优先确认 ORM 异步支持现状，未必要全 async。

---

## 测试

Django 自带 `TestCase`（带事务回滚），但推荐用 pytest + `pytest-django` 统一风格（详见语言级 testing.md）：

```python
import pytest
from django.test import Client

@pytest.mark.django_db
def test_create_user():
    client = Client()
    resp = client.post("/api/v1/users/", {"email": "a@b.com"})
    assert resp.status_code == 201
```

`@pytest.mark.django_db` 提供测试数据库事务隔离。

---

## 部署

* 生产用 ASGI（`daphne`/`uvicorn`）跑 async，或 WSGI（`gunicorn`）
* `collectstatic` 静态文件收集
* `DEBUG=False` 必须设 `ALLOWED_HOSTS` 与 `STATIC_ROOT`
- 数据库迁移 `migrate` 在部署流程执行

---

## 禁止行为

* ❌ view 写业务逻辑、settings 硬编码密钥
* ❌ `all()` 全量加载、ORM 查询 N+1
* ❌ 迁移不提交、生产 `DEBUG=True`/未设 `ALLOWED_HOSTS`
* ❌ async view 直接调同步 ORM、未提交的 makemigrations
