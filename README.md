# GaussDB SQLAlchemy Python 驱动

面向华为 GaussDB 集中式数据库的 Python SQLAlchemy 方言驱动。通过 pyodbc 调用 GaussDB ODBC Driver，接入 SQLAlchemy 的 ORM、连接池、事务、SQL 编译和反射能力。支持 A 兼容（Oracle 风格）、B 兼容（MySQL 风格）和 M 兼容（MySQL 风格）三种模式。

不需要 Java 环境，不需要 libpq，只需安装 GaussDB ODBC 驱动和 pyodbc 即可。

## 前置条件

- Python 3.8 及以上
- GaussDB ODBC 驱动（从华为云下载，安装后在系统 ODBC 管理器中可见）
- pyodbc（pip 自动安装）

### 各平台 ODBC 驱动安装

**Windows：**
1. 从华为云下载 GaussDB ODBC 驱动安装包
2. 运行安装程序，驱动自动注册到系统 ODBC 管理器
3. 无需额外配置，直接 pip install 即可使用

**Linux：**
1. 下载 GaussDB ODBC 驱动包并解压
2. 安装 unixODBC：`yum install unixODBC` 或 `apt install unixodbc`
3. 配置 /etc/odbcinst.ini 注册驱动
4. 确保 .so 文件路径在 LD_LIBRARY_PATH 中

**macOS：**
1. 安装 unixODBC：`brew install unixodbc`
2. 下载并配置 GaussDB ODBC 驱动

## 安装

```bash
pip install gaussdb_sqlalchemy_python_driver-0.2.0-py3-none-any.whl
```

安装后自动拉取 SQLAlchemy 和 pyodbc。

## 快速开始

```python
from sqlalchemy import create_engine, text

engine = create_engine(
    "gaussdb+odbc://sqlbuilder1:huawei%40123@121.37.186.131:19995/postgres"
    "?driver=GaussDB+ODBC+Driver&sslmode=disable",
    pool_pre_ping=True,
)

with engine.connect() as conn:
    print(conn.execute(text("select 1")).scalar_one())
```

密码中如包含 `@` 等特殊字符，需要 URL 编码。例如 `password@123` 应写为 `password%40123`。

## 连接串格式

```text
gaussdb+odbc://用户名:密码@主机:端口/数据库名?driver=GaussDB+ODBC+Driver&sslmode=disable
```

也支持短格式：

```text
gaussdb://用户名:密码@主机:端口/数据库名?driver=GaussDB+ODBC+Driver&sslmode=disable
```

如果已在系统 ODBC 管理器中配置了 DSN，可以使用 DSN 模式：

```text
gaussdb+odbc://用户名:密码@/数据库名?dsn=MyGaussDB
```

可选参数：
- `driver` — 指定 ODBC 驱动名称，默认 `GaussDB ODBC Driver`
- `dsn` — 使用系统已配置的 ODBC 数据源名称
- `sslmode` — SSL 模式（disable/require/verify-ca/verify-full）
- 其他查询参数会自动转发为 ODBC 连接属性

## ORM 用法

```python
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import Session, declarative_base
from datetime import datetime

engine = create_engine(
    "gaussdb+odbc://sqlbuilder1:huawei%40123@121.37.186.131:19995/testm"
    "?driver=GaussDB+ODBC+Driver&sslmode=disable",
    pool_pre_ping=True,
)

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String(50))
    created = Column(DateTime)

Base.metadata.create_all(engine)

with Session(engine) as session:
    session.add(User(name="张三", created=datetime.now()))
    session.commit()
    users = session.query(User).all()
    for u in users:
        print(u.id, u.name, u.created)
```

## 兼容模式支持

驱动自动检测数据库的兼容模式（A/B/M）并适配 SQL 方言差异：

| 特性 | A 兼容 (Oracle) | B 兼容 (MySQL) | M 兼容 (MySQL) |
|------|----------------|----------------|----------------|
| 标识符引号 | 双引号 | 双引号/反引号 | 反引号 |
| 自增主键 | serial | serial/AUTO_INCREMENT | AUTO_INCREMENT |
| ORM INSERT 获取自增 ID | RETURNING | RETURNING | LAST_INSERT_ID() |
| 字符串拼接 | \|\| | \|\| | CONCAT() |
| TIMESTAMP 精度 | 默认无 | 默认无 | TIMESTAMP(6) |
| Oracle 语法 (DUAL/NVL/SYSDATE) | 支持 | 支持 | 不支持 |
| 隔离级别 | 全部支持 | 全部支持 | REPEATABLE READ（SERIALIZABLE 不支持） |

驱动还支持 Alembic 迁移工具，包括 batch_alter_table 和 autogenerate。

## 功能特性

- SQLAlchemy 2.x Core + ORM 完整支持
- 连接池、事务、保存点
- 表/列/索引/约束/视图/注释反射
- Alembic 迁移集成（batch mode + autogenerate）
- 全部标准 SQL 数据类型（Integer、String、Text、DateTime、Numeric、Boolean、LargeBinary 等）
- A/B/M 三种兼容模式自动检测和适配

## 已知限制

- **ON CONFLICT**：GaussDB 集中式不支持 PostgreSQL `ON CONFLICT` upsert 语法
- **M 兼容 LIKE**：默认大小写不敏感（MySQL 行为）；A/B 兼容为大小写敏感
- **M 兼容集合运算**：不支持 `INTERSECT` / `EXCEPT`
- **M 兼容临时表**：不支持 `CREATE TEMP TABLE`，需用 `CREATE TEMPORARY TABLE`
- **M 兼容 CAST**：不支持 `CAST(x AS VARCHAR)`，需用 `CAST(x AS CHAR)`
- **M 兼容 TIMESTAMP DEFAULT**：`TIMESTAMP(6) DEFAULT current_timestamp` 不被支持
- **M 兼容 TEXT**：最大 65535 字节
- **Decimal 精度**：超过 15 位有效数字的 Decimal 可能有精度损失
- **SERIALIZABLE 隔离级别**：GaussDB 集中式不支持，静默降级为 REPEATABLE READ

## 并发限制

通过 pyodbc 调用 ODBC 驱动。`threadsafety = 1`，模块可被多线程共享，但连接对象不应跨线程共享。建议每个线程从 SQLAlchemy engine 独立获取连接。

## 开发和测试

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e ".[test]"
pytest
```

连接真实 GaussDB 环境跑集成测试：

```bash
export GAUSSDB_TEST_URL_A='gaussdb+odbc://user:password@host:port/a_db?driver=GaussDB+ODBC+Driver&sslmode=disable'
export GAUSSDB_TEST_URL_B='gaussdb+odbc://user:password@host:port/b_db?driver=GaussDB+ODBC+Driver&sslmode=disable'
export GAUSSDB_TEST_URL_M='gaussdb+odbc://user:password@host:port/m_db?driver=GaussDB+ODBC+Driver&sslmode=disable'
pytest -m integration
```

## 打包

```bash
pip install build
python -m build
```

打包产物在 `dist/` 目录。

## 技术架构

```
Python 应用
    ↓
SQLAlchemy (ORM / Core)
    ↓
GaussDB SQLAlchemy Dialect (本驱动)
    ↓
pyodbc
    ↓
ODBC Driver Manager (Windows 自带 / Linux unixODBC)
    ↓
GaussDB ODBC Driver
    ↓
GaussDB 集中式
```

## 开源协议

Apache License 2.0
