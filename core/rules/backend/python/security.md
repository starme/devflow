---
description: Python 安全规范
paths: ["**/*.py"]
alwaysApply: false
---

# Python 安全规范

适用于所有 Python 后端服务。通用安全底线（硬编码密钥、`.env` gitignore、日志脱敏、依赖漏洞、限流数值、CORS、HTTP 安全头、命令注入、反序列化、文件上传、路径穿越、模板注入）见 `~/.claude/rules/engineering.md`，本文件只讲 Python 特有实现与补充。框架专属安全（FastAPI 依赖注入 / Django 中间件）见项目级框架规范。

---

## 认证与授权

通用原则见 engineering.md。Python 实现：用成熟库（`pyjwt` / `python-jose`），禁止手写 JWT 实现：

```python
import jwt

def verify_token(raw_token: str) -> dict:
    try:
        return jwt.decode(
            raw_token,
            settings.jwt_secret,
            algorithms=["HS256"],   # 显式指定算法，禁止 algorithms=None
            options={"verify_exp": True, "verify_iss": True},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("token invalid") from exc
```

禁止 `algorithms=None`（算法降级攻击）。

---

## 输入校验

通用原则见 engineering.md。Python 用 Pydantic 模型：

```python
from pydantic import BaseModel, Field, EmailStr, conint
from typing import Literal

class RegisterReq(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    email: EmailStr
    age: conint(ge=0, le=150)
    role: Literal["admin", "user"]   # 枚举白名单
```

---

## SQL 注入

通用原则见 engineering.md（禁拼接、参数化、动态列名白名单）。Python 实现：

```python
# ✅ 参数化（psycopg / asyncpg）
cursor.execute("SELECT * FROM users WHERE email = %s", (email,))

# ✅ SQLAlchemy ORM
session.query(User).filter(User.email == email).first()

# ❌ f-string 拼接
cursor.execute(f"SELECT * FROM users WHERE email = '{email}'")
```

动态列名白名单：

```python
ALLOWED_SORT_COLUMNS = {"name", "created_at", "email"}

def safe_sort(column: str) -> str:
    if column not in ALLOWED_SORT_COLUMNS:
        raise ValueError(f"invalid sort column: {column}")
    return column

cursor.execute(f"SELECT * FROM users ORDER BY {safe_sort(order_by)}")
```

---

## 命令注入

通用原则见 engineering.md。Python 特有：禁止 `subprocess.run(shell=True)` 传入用户输入：

```python
# ❌ shell=True + 用户输入 = 命令注入
subprocess.run(f"convert {filename} out.png", shell=True)

# ✅ 参数列表传参，shell=False
subprocess.run(["convert", filename, "out.png"], check=True)
```

能用库解决的不要起子进程（图像处理用 Pillow，不要 `convert`）。

---

## 模板注入（SSTI）

通用原则见 engineering.md（变量通过上下文传入，引擎自动转义）。Python 实现：Jinja2 渲染 HTML 时 `autoescape=True` 必开：

```python
# ❌ 用户输入进入模板字符串
template = f"Hello {user_input}"
Environment().from_string(template).render()

# ✅ 变量通过上下文传入
template = Environment(autoescape=True).from_string("Hello {{ name }}")
template.render(name=user_input)
```

---

## 反序列化

通用原则见 engineering.md。Python 特有：禁止 `pickle.load` / `yaml.load` 处理不可信数据（RCE 风险）：

```python
# ❌
import pickle, yaml
data = pickle.loads(user_bytes)
config = yaml.load(user_text)        # 默认全标签，可执行任意对象

# ✅
config = yaml.safe_load(user_text)
data = json.loads(user_text)
```

---

## 密码

通用原则见 engineering.md（bcrypt cost≥12、rehash）。Python 实现：

```python
import bcrypt

# 存储
salt = bcrypt.gensalt(rounds=12)
hashed = bcrypt.hashpw(password.encode("utf-8"), salt)

# 验证（常数时间比较，bcrypt 内部已处理）
bcrypt.checkpw(password.encode("utf-8"), hashed)
```

需要 PBKDF2 时用 `hashlib.pbkdf2_hmac` 且 iterations ≥ 600000；需要 Argon2id 用 `argon2-cffi`。

---

## 敏感数据

通用原则见 engineering.md。Python 脱敏实现：

```python
# ❌ 日志含明文密码
logger.info("login attempt", extra={"password": request.password})

# ✅ 脱敏
def mask_phone(phone: str) -> str:
    return phone[:3] + "****" + phone[-4:] if len(phone) >= 7 else "***"

logger.info("login attempt", extra={"user_id": user_id, "phone": mask_phone(phone)})
```

---

## 文件上传

通用原则见 engineering.md（MIME 探测、大小限制、随机名、目录隔离、路径校验）。Python 实现：

```python
import magic   # python-magic
import secrets

# 用 libmagic 校验真实 MIME，不信任 Content-Type 头
mime = magic.from_buffer(uploaded_file.read(2048), mime=True)
if mime not in {"image/jpeg", "image/png", "image/webp"}:
    raise InvalidFileTypeError(mime)

# 限制大小 + 重命名为随机文件名，不用原始文件名
ext = mime.split("/")[-1]
filename = f"{secrets.token_hex(16)}.{ext}"
```

---

## 路径穿越

通用原则见 engineering.md（拼接后校验最终路径在允许目录内）。Python 实现：

```python
from pathlib import Path

def safe_join(base: Path, user_path: str) -> Path:
    target = (base / user_path).resolve()
    if not str(target).startswith(str(base.resolve())):
        raise PathTraversalError(user_path)
    return target
```

---

## HTTP 安全头

通用原则见 engineering.md。Python 注入实现：

```python
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'",
}
```

---

## 配置与密钥

通用原则见 engineering.md（环境变量注入、`.env` gitignore、不打镜像层）。Python 用 `pydantic-settings` 集中管理，启动时校验：

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    jwt_secret: str
    db_url: str
    redis_url: str
```

---

## 依赖安全

通用原则见 engineering.md。Python 用 `pip-audit`，CI 强制运行，高危漏洞（CVSS ≥ 7.0）阻断构建；锁文件（`uv.lock` / `poetry.lock`）必须提交：

```bash
pip-audit --strict
```

---

## 错误响应

通用原则见 engineering.md（堆栈只进日志，客户端收统一错误码）。Python 实现：

```python
# ❌
return {"error": str(exc), "trace": traceback.format_exc()}, 500

# ✅
logger.exception("internal error")        # 堆栈只进日志
return {"code": 500, "message": "服务内部错误"}, 500
```

`DEBUG=True` 仅开发环境；生产环境关闭调试工具栏与详细错误页。

---

## 禁止行为

* ❌ SQL 字符串拼接、`subprocess shell=True` + 用户输入、`pickle`/`yaml.load` 反序列化不可信数据
* ❌ MD5/SHA1 存密码、硬编码密钥、`algorithms=None` 解 JWT
* ❌ 日志输出敏感字段、信任原始文件名/Content-Type、未校验路径穿越
* ❌ 生产环境 `Access-Control-Allow-Origin: *`、暴露错误堆栈、`DEBUG=True` 上生产
* ❌ `os.system` / `eval` / `exec` 传入用户输入
* ❌ 把密钥打进容器镜像层
