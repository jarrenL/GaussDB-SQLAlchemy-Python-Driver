# GaussDB SQLAlchemy Python 驱动

这是一个面向华为 GaussDB 轻量化集中式 505.1 的轻量 Python 驱动项目，支持 Windows 和 Linux，并提供 SQLAlchemy 2.x 方言。当前客户目标兼容模式为 A 兼容和 B 兼容。

本项目不重新实现数据库通信协议，而是复用华为官方 `gaussdb` Python DB-API 包作为底层连接能力，再通过 SQLAlchemy 方言接入 ORM、连接池、事务、SQL 编译和反射等能力。

## 功能特性

- 支持 SQLAlchemy 2.x
- 支持 `gaussdb://...` 连接串
- 支持 `gaussdb+gaussdb://...` 连接串
- 底层使用华为 `gaussdb>=1.0.4` DB-API 包
- 面向 GaussDB 轻量化集中式 505.1 的 A 兼容和 B 兼容场景
- 默认关闭 HSTORE 等 PostgreSQL 扩展假设，适合轻量化集中式部署
- 支持 Windows 安装和运行

## 安装

### Windows

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install gaussdb_sqlalchemy_driver-0.1.0-py3-none-any.whl
```

如果是从源码目录安装：

```powershell
python -m pip install .
```

### Linux 或 macOS

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install gaussdb_sqlalchemy_driver-0.1.0-py3-none-any.whl
```

## GaussDB 客户端依赖

`gaussdb` 包在运行时需要加载 GaussDB/libpq 客户端实现。

在 Windows 上，请先安装华为 GaussDB 客户端包，并将客户端 `bin` 目录加入 `PATH`，然后再启动 Python、Web 服务或应用程序。

如果导入时报错 `no pq wrapper available`，通常说明 Python 已经能找到 `gaussdb` 包，但还没有找到可用的 GaussDB 原生客户端库。

可以使用环境检查脚本确认 Python 包和真实连接是否可用：

```powershell
python scripts\check_windows_env.py
python scripts\check_windows_env.py --url "gaussdb+gaussdb://user:password@host:port/postgres"
```

## SQLAlchemy 使用示例

```python
from sqlalchemy import create_engine, text

engine = create_engine(
    "gaussdb+gaussdb://user:password@127.0.0.1:8000/postgres",
    pool_pre_ping=True,
)

with engine.begin() as conn:
    value = conn.execute(text("select 1")).scalar_one()
    print(value)
```

也可以使用短连接串：

```python
from sqlalchemy import create_engine

engine = create_engine(
    "gaussdb://user:password@127.0.0.1:8000/postgres"
)
```

## DB-API 使用示例

```python
import gaussdb_sqlalchemy.dbapi as gaussdb_driver

with gaussdb_driver.connect(
    host="127.0.0.1",
    port=8000,
    dbname="postgres",
    user="user",
    password="password",
) as conn:
    with conn.cursor() as cur:
        cur.execute("select 1")
        print(cur.fetchone())
```

## 连接串格式

推荐格式：

```text
gaussdb+gaussdb://用户名:密码@主机:端口/数据库名
```

示例：

```text
gaussdb+gaussdb://gaussdb_user:password@192.168.1.10:8000/postgres
```

常用参数可以放在查询字符串中：

```text
gaussdb+gaussdb://user:password@127.0.0.1:8000/postgres?sslmode=verify-full&application_name=myapp
```

方言默认会向底层 `gaussdb` 驱动传入 `client_encoding=UTF8`，避免部分 GaussDB 环境默认 `SQL_ASCII` 时文本字段以 `bytes` 返回。如果确实需要其他编码，可以在连接串中显式覆盖：

```text
gaussdb+gaussdb://user:password@127.0.0.1:8000/postgres?client_encoding=LATIN1
```

## 开发和测试

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
pytest
```

如果要连接真实 GaussDB 环境执行集成测试，可以设置：

```bash
export GAUSSDB_TEST_URL='gaussdb+gaussdb://user:password@host:port/postgres'
pytest -m integration
```

集成测试覆盖 SQLAlchemy Core、事务回滚、批量插入、ORM CRUD、元数据反射和连接池基础复用。

没有安装 pytest 的数据库主机也可以运行轻量探针：

```bash
GAUSSDB_TEST_URL='gaussdb+gaussdb://user:password@host:port/postgres' \
python scripts/run_integration_probe.py
```

探针覆盖主键、唯一约束、普通索引反射、序列默认值和 Alembic Operations。

如果要快速判断当前库对 PostgreSQL、Oracle 风格、MySQL 风格 SQL 的接受情况，可以运行：

```bash
GAUSSDB_TEST_URL='gaussdb+gaussdb://user:password@host:port/postgres' \
python scripts/run_syntax_probe.py
```

## Alembic 支持

测试依赖中包含 Alembic。本项目会在 Alembic 可用时注册 `gaussdb` DDL 实现，复用 Alembic PostgreSQL 基础实现，当前已验证：

- `Operations.create_table()`
- `Operations.add_column()`
- `Operations.drop_table()`

Alembic autogenerate 还需要更多真实场景回归。

## 打包

```bash
python -m pip install build
python -m build
```

打包后文件会生成在 `dist/` 目录：

```text
dist/gaussdb_sqlalchemy_driver-0.1.0-py3-none-any.whl
dist/gaussdb_sqlalchemy_driver-0.1.0.tar.gz
```

## 适配范围

当前版本面向 GaussDB 轻量化集中式 505.1 的 A 兼容和 B 兼容基础 SQLAlchemy 接入场景，适合应用侧先完成连接、查询、事务、连接池和 ORM 基础能力适配。

已在 GaussDB Kernel 507.0.0 环境验证：

- A 兼容库：`datcompatibility = A`
- B 兼容库：`datcompatibility = B`
- B 兼容库可执行部分 MySQL 风格语法，例如反引号、`ifnull()`、`auto_increment`
- 当前包仍基于 GaussDB Python DB-API 和 SQLAlchemy 方言适配，不是 MySQL 原生协议驱动

后续可以继续补充：

- SQLAlchemy 方言兼容性测试套件
- GaussDB 特有 SQL、数据类型和系统表反射适配
- Windows 离线安装包和部署脚本

## 开源协议

本项目采用 Apache License 2.0 开源协议发布，详见 [LICENSE](LICENSE)。
