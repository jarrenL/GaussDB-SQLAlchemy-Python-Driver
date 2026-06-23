# GaussDB SQLAlchemy Python 驱动

这是一个面向华为 GaussDB 轻量化集中式 505.1 的 Python SQLAlchemy 方言项目，当前客户目标兼容模式为 A 兼容、B 兼容和 M 兼容。

项目采用 JDBC 后端：Python 通过 JayDeBeApi/JPype 调用 GaussDB JDBC Driver，再接入 SQLAlchemy 的 ORM、连接池、事务、SQL 编译和反射能力。该方案面向 Windows 免数据库客户端 DLL 的交付场景。

## 功能特性

- 支持 SQLAlchemy 2.x
- 支持 `gaussdb://...` 连接串
- 支持 `gaussdb+jdbc://...` 连接串
- 底层使用 JayDeBeApi、JPype1 和 GaussDB JDBC Driver
- Windows 不需要额外安装数据库客户端 DLL
- 面向 GaussDB 轻量化集中式 505.1 的 A 兼容、B 兼容和 M 兼容场景
- 默认关闭 HSTORE 等 PostgreSQL 扩展假设，适合轻量化集中式部署

## 安装

### Windows

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install gaussdb_sqlalchemy_driver-0.1.0-py3-none-any.whl
```

还需要准备：

- Java Runtime，建议 JDK/JRE 8 或 11 及以上
- GaussDB JDBC Driver jar，例如 `gsjdbc4.jar`

### Linux 或 macOS

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install gaussdb_sqlalchemy_driver-0.1.0-py3-none-any.whl
```

## SQLAlchemy 使用示例

```python
from sqlalchemy import create_engine, text

engine = create_engine(
    "gaussdb+jdbc://user:password@127.0.0.1:8000/postgres"
    "?jdbc_driver_path=C:/GaussDB/jdbc/gsjdbc4.jar",
    pool_pre_ping=True,
)

with engine.begin() as conn:
    print(conn.execute(text("select 1")).scalar_one())
```

默认 JDBC 驱动类名为：

```text
com.huawei.gaussdb.jdbc.Driver
```

当前华为 GaussDB JDBC jar 使用该驱动类名。如果实际 jar 使用其他驱动类名，可以显式指定：

```text
gaussdb+jdbc://user:password@127.0.0.1:8000/postgres?jdbc_driver_class=com.huawei.gaussdb.jdbc.Driver&jdbc_driver_path=C:/GaussDB/jdbc/gaussdbjdbc-506.0.0.b058-jdk7.jar
```

也可以完全覆盖 JDBC URL：

```text
gaussdb+jdbc://user:password@placeholder/postgres?jdbc_url=jdbc:gaussdb://127.0.0.1:8000/postgres&jdbc_driver_path=C:/GaussDB/jdbc/gaussdbjdbc-506.0.0.b058-jdk7.jar
```

## 连接串格式

推荐格式：

```text
gaussdb+jdbc://用户名:密码@主机:端口/数据库名?jdbc_driver_path=JDBC驱动jar路径
```

短格式 `gaussdb://...` 也会使用 JDBC 方言：

```text
gaussdb://用户名:密码@主机:端口/数据库名?jdbc_driver_path=JDBC驱动jar路径
```

密码中如包含 `@` 等特殊字符，需要 URL 编码。例如 `password@123` 应写为 `password%40123`。

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
export GAUSSDB_TEST_URL='gaussdb+jdbc://user:password@host:port/postgres?jdbc_driver_path=/path/to/gsjdbc4.jar'
pytest -m integration
```

如果要一次性验证 A/B/M 三种兼容库，可以分别设置：

```bash
export GAUSSDB_TEST_URL_A='gaussdb+jdbc://user:password@host:port/a_database?jdbc_driver_path=/path/to/gaussdbjdbc.jar'
export GAUSSDB_TEST_URL_B='gaussdb+jdbc://user:password@host:port/b_database?jdbc_driver_path=/path/to/gaussdbjdbc.jar'
export GAUSSDB_TEST_URL_M='gaussdb+jdbc://user:password@host:port/m_database?jdbc_driver_path=/path/to/gaussdbjdbc.jar'
pytest tests/test_compatibility_scenarios.py -m integration
```

也可以使用逗号分隔的 `GAUSSDB_TEST_URLS` 批量传入多个真实库连接串。

没有安装 pytest 的数据库主机也可以运行轻量探针：

```bash
GAUSSDB_TEST_URL='gaussdb+jdbc://user:password@host:port/postgres?jdbc_driver_path=/path/to/gsjdbc4.jar' \
python scripts/run_integration_probe.py
```

如果要快速判断当前库对 PostgreSQL、Oracle 风格、MySQL 风格 SQL 的接受情况，可以运行：

```bash
GAUSSDB_TEST_URL='gaussdb+jdbc://user:password@host:port/postgres?jdbc_driver_path=/path/to/gsjdbc4.jar' \
python scripts/run_syntax_probe.py
```

Windows 实机测试步骤、前置条件、测试场景和真实数据库地址配置方式见 [docs/Windows测试指导手册.md](docs/Windows测试指导手册.md)。

## 验证覆盖

集成测试覆盖：

- SQLAlchemy Core DDL、DML、查询
- 真实表生命周期：建表、表存在性检查、插入、查询、更新、删除和清理
- 事务回滚
- 批量插入
- ORM CRUD
- 元数据反射
- 常用数据类型
- 主键、唯一约束、普通索引反射
- 序列和默认值
- Alembic Operations
- Alembic autogenerate 基础无差异检测
- 复杂索引、表达式索引、视图反射和分区表反射
- 连接池基础复用
- A/B/M 兼容语法场景，包括 Oracle 风格、MySQL 风格、`serial`、`auto_increment`、`nextval` 和表达式索引

## 适配范围

当前版本面向 GaussDB 轻量化集中式 505.1 的 A 兼容、B 兼容和 M 兼容基础 SQLAlchemy 接入场景，适合应用侧先完成连接、查询、事务、连接池和 ORM 基础能力适配。

已在 GaussDB Kernel 507.0.0 环境验证过 A 兼容、B 兼容和 M 兼容基础能力。GaussDB 505.1、Windows 实机和客户真实库仍需按测试指导手册继续验证。

## 已知限制

- GaussDB 集中式不支持 PostgreSQL `ON CONFLICT` upsert 语法。SQLAlchemy PostgreSQL 方言的 `insert(...).on_conflict_do_update()` 会生成 `ON CONFLICT` SQL，当前版本仅声明该限制，不做自动改写。
- M 兼容下 `LIKE` 默认大小写不敏感，符合 MySQL 风格行为；A/B 兼容下 `LIKE` 为大小写敏感。跨兼容模式迁移时需要单独确认查询语义。
- M 兼容下不支持 `INTERSECT` / `EXCEPT` 集合运算；SQLAlchemy 的 `intersect()` / `except_()` 在 M 兼容库上会由数据库返回语法错误。
- M 兼容下 raw SQL `CREATE TEMP TABLE` 不支持，需使用 `CREATE TEMPORARY TABLE`；通过 SQLAlchemy 创建临时表时建议显式使用 `prefixes=["TEMPORARY"]`。

## 并发限制

本项目通过 JayDeBeApi/JPype 在 Python 进程内调用 JVM。`threadsafety = 1`，表示模块可被多线程共享，但连接对象不应跨线程共享。建议每个线程独立从 SQLAlchemy engine 获取连接，并避免在 JVM 首次启动阶段做高并发连接初始化。

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

## 开源协议

本项目采用 Apache License 2.0 开源协议发布，详见 [LICENSE](LICENSE)。
