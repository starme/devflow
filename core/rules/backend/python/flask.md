---
description: Flask 项目级规范模板
paths: ["**/*.py"]
alwaysApply: false
---

# Flask 项目级规范模板

适用于 Flask 项目。语言级规范（命名、类型注解、错误处理、测试、安全）见 `~/.claude/rules/backend/python/` 与 `~/.claude/rules/engineering.md`，本模板只讲 Flask 特有约定。

---

## 项目结构

用应用工厂（application factory）模式，blueprint 按业务模块拆分：

```
project/
├── pyproject.toml
├── wsgi.py                  # 入口：from myproject import create_app
├── myproject/
│   ├── __init__.py          # create_app 工厂
│   ├── config.py            # 配置类
│   ├── extensions.py        # db/migrate/auth 等扩展实例
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── views.py         # blueprint
│   │   └── models.py
│   ├── users/
│   │   ├── __init__.py
│   │   ├── views.py         # blueprint
│   │   ├── models.py
│   │   └── services.py      # 业务逻辑层（核心）
│   ├── templates/
│   └── static/
└── tests/
```

* blueprint 内只做请求处理与调用 service，业务逻辑放 `services.py`
* 扩展（`db = SQLAlchemy()`）在 `extensions.py` 实例化，避免循环导入

---

## 应用工厂

官方推荐 `create_app()` 工厂，配置加载、扩展初始化、blueprint 注册都在此完成：

```python
from flask import Flask

def create_app(config_class="myproject.config.ProdConfig"):
    app = Flask(__name__)
    app.config.from_object(config_class)

    from myproject.extensions import db, migrate
    db.init_app(app)
    migrate.init_app(app, db)

    from myproject.users.views import users_bp
    from myproject.auth.views import auth_bp
    app.register_blueprint(users_bp, url_prefix="/api/v1")
    app.register_blueprint(auth_bp, url_prefix="/api/v1/auth")

    return app
```

工厂模式让多环境配置、测试、多实例成为可能。禁止模块顶层 `app = Flask(__name__)`。

---

## 配置

用配置类 + `from_object`，环境变量覆盖（通用原则见 engineering.md 安全底线）：

```python
import os

class BaseConfig:
    SECRET_KEY = os.environ["SECRET_KEY"]
    SQLALCHEMY_DATABASE_URI = os.environ["DATABASE_URL"]
    TESTING = False

class ProdConfig(BaseConfig):
    DEBUG = False

class DevConfig(BaseConfig):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///dev.db"
```

* 密钥用环境变量，禁止硬编码
* `instance/` 目录放本地机密配置（`from_pyfile`），`.gitignore`
* 生产 `DEBUG=False`，关闭调试器

---

## Blueprint

每个业务模块一个 blueprint，路由注册在 blueprint 上：

```python
from flask import Blueprint

users_bp = Blueprint("users", __name__)

@users_bp.post("/user/create")
def create_user():
    data = request.get_json()
    # 调 service，不写业务逻辑
    ...
```

URL 前缀在 `register_blueprint` 时统一加（`/api/v1`），见工厂示例。

---

## 请求/响应

* 用 Flask 2.0+ 路由装饰器（`@bp.post`/`@bp.get`）替代 `methods=[...]`
* 响应统一用 `jsonify` 或框架封装，避免手拼 dict + `Response`
* 入参校验用 Marshmallow 或 Pydantic（通用原则见 engineering.md 输入校验）

---

## 数据库

`Flask-SQLAlchemy` 为主。model 在各模块定义，扩展在 `extensions.py`：

```python
# extensions.py
from flask_sqlalchemy import SQLAlchemy
db = SQLAlchemy()

# users/models.py
from myproject.extensions import db

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
```

* 禁止 SQL 拼接，用 ORM 或参数化（通用原则见 engineering.md）
* 迁移用 `Flask-Migrate`（Alembic），迁移文件提交进 git
* 应用上下文：`db` 操作需在 app context 内（工厂模式下请求自动提供）

---

## 鉴权

* 用 `Flask-Login`（session）或 `Flask-JWT-Extended`（token）
* 装饰器统一保护路由，禁止业务函数内自行解析身份
* Session 场景必须 CSRF 保护（`Flask-WTF`），API（无 cookie）可豁免（详见 php/security.md 的 CSRF 原则，对 Flask 同理）

---

## 错误处理

注册错误处理器，统一错误响应格式（通用原则见 engineering.md 错误响应）：

```python
@app.errorhandler(BizError)
def handle_biz_error(e):
    return jsonify({"code": e.code, "message": e.message}), e.http_status

@app.errorhandler(404)
def handle_404(e):
    return jsonify({"code": 100001, "message": "资源不存在"}), 404
```

生产环境关闭 `DEBUG` 与 Werkzeug 调试器（`app.run(debug=False)`）。

---

## 测试

用 pytest + `app.test_client()`，工厂模式便于注入测试配置（详见语言级 testing.md）：

```python
import pytest
from myproject import create_app

@pytest.fixture()
def client():
    app = create_app("myproject.config.TestConfig")
    app.config["TESTING"] = True
    with app.test_client() as client:
        with app.app_context():
            from myproject.extensions import db
            db.create_all()
        yield client
        with app.app_context():
            db.drop_all()

def test_create_user(client):
    resp = client.post("/api/v1/user/create", json={"name": "Alice"})
    assert resp.status_code == 201
```

测试用独立数据库，禁止连开发/生产。

---

## 部署

* 生产用 WSGI 服务器（`gunicorn`/`waitress`），禁止 `app.run()` 上生产
* `gunicorn -w 4 -b :8000 "myproject:create_app()"`
* 反向代理（nginx）前置，由代理设 HTTPS、安全头（见 engineering.md HTTP 安全头）

---

## 禁止行为

* ❌ 模块顶层 `app = Flask()`、view 写业务逻辑
* ❌ settings 硬编码密钥、生产 `DEBUG=True`/`app.run`
* ❌ SQL 拼接、迁移不提交、测试连生产库
* ❌ 业务函数内自行解析 token/身份（用装饰器统一）
