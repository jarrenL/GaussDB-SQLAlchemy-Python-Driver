# Windows 测试指导手册

本文面向 Windows 测试人员，用于验证 `gaussdb-sqlalchemy-driver` 在 Windows 环境下能否安装、通过 JDBC 连接真实 GaussDB 数据库，并完成 SQLAlchemy 基础能力、A/B/M 兼容语法探针和扩展集成场景验证。

## 1. 前置条件

### 1.1 操作系统

- Windows 10、Windows 11 或 Windows Server。
- 当前登录用户可以安装 Python 包，并可以修改当前会话或系统 `PATH`。

### 1.2 Python 环境

建议使用 Python 3.9 到 3.13，推荐 Python 3.11。

检查命令：

```powershell
py --version
python --version
```

如果机器上安装了多个 Python 版本，建议显式使用：

```powershell
py -3.11 --version
```

### 1.3 Windows 连接路线

Windows 环境使用 JDBC 后端，避免依赖额外的数据库客户端 DLL。

推荐路线：

```text
Python -> SQLAlchemy -> gaussdb+jdbc 方言 -> JayDeBeApi/JPype -> GaussDB JDBC Driver -> GaussDB
```

该路线不需要额外安装数据库客户端 DLL，但需要：

- Java Runtime，建议 JDK/JRE 8 或 11 及以上。
- GaussDB JDBC Driver jar，例如 `gsjdbc4.jar`，以 DBA、华为云控制台或交付包提供为准。
- Python 包：`JayDeBeApi`、`JPype1`。

检查 Java：

```powershell
java -version
```

建议将 JDBC jar 放到固定目录，例如：

```text
C:\GaussDB\jdbc\gsjdbc4.jar
```

当前 Windows 测试只验证 JDBC 后端。

### 1.4 数据库账号和权限

测试账号至少需要具备以下权限：

- 连接目标数据库。
- 创建和删除临时表，测试表名前缀为 `gdbdrv_*`。
- 创建和删除临时视图。
- 创建和删除临时序列。
- 创建索引。
- 执行基础系统表查询。

如需验证分区表，还需要目标库支持脚本中的分区表 DDL，并且账号具有创建分区表权限。

### 1.5 测试文件

从开源仓库下载项目或下载 wheel 包：

- 项目地址：`https://github.com/jarrenL/GaussDB-Python-Driver`
- wheel 包：`dist/gaussdb_sqlalchemy_driver-0.1.0-py3-none-any.whl`
- 源码包：`dist/gaussdb_sqlalchemy_driver-0.1.0.tar.gz`

如果只做安装和连接验证，下载 wheel 包即可。如果要运行 `scripts/` 下的探针脚本，建议下载完整项目源码。

## 2. 安装步骤

### 2.1 创建虚拟环境

在项目目录或测试目录执行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

如果 PowerShell 禁止执行脚本，可临时放开当前进程策略：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 2.2 安装 wheel 包

```powershell
python -m pip install .\dist\gaussdb_sqlalchemy_driver-0.1.0-py3-none-any.whl
```

如果从源码目录安装：

```powershell
python -m pip install .
```

如果要运行 pytest 集成测试：

```powershell
python -m pip install -e ".[test]"
```

如果只安装 wheel，也需要补 JDBC 依赖：

```powershell
python -m pip install JayDeBeApi JPype1
```

## 3. 真实数据库地址配置

### 3.1 连接串格式

Windows 推荐使用 JDBC 后端连接串：

```text
gaussdb+jdbc://用户名:密码@数据库IP:端口/数据库名?jdbc_driver_path=JDBC驱动jar路径
```

示例：

```text
gaussdb+jdbc://test_user:test_password@192.168.1.10:8000/postgres?jdbc_driver_path=C:/GaussDB/jdbc/gsjdbc4.jar
```

默认 JDBC 驱动类名为：

```text
com.huawei.gaussdb.jdbc.Driver
```

当前华为 GaussDB JDBC jar 使用该驱动类名。如果实际 jar 使用其他驱动类名，可以通过 `jdbc_driver_class` 覆盖。

### 3.2 密码特殊字符处理

如果密码包含 `@`、`#`、`:`、`/`、`?`、`&` 等特殊字符，需要进行 URL 编码。

常见示例：

```text
@  -> %40
#  -> %23
:  -> %3A
/  -> %2F
?  -> %3F
&  -> %26
```

例如密码为：

```text
password@123
```

连接串中应写为：

```text
password%40123
```

也可以用 Python 生成编码后的密码：

```powershell
python -c "from urllib.parse import quote_plus; print(quote_plus('password@123'))"
```

### 3.3 推荐方式：使用环境变量

不建议直接修改脚本源码中的数据库地址。推荐在 PowerShell 当前会话设置环境变量：

```powershell
$env:GAUSSDB_TEST_URL="gaussdb+jdbc://用户名:URL编码后的密码@数据库IP:端口/数据库名?jdbc_driver_path=JDBC驱动jar路径"
```

示例：

```powershell
$env:GAUSSDB_TEST_URL="gaussdb+jdbc://test_user:password%40123@192.168.1.10:8000/postgres?jdbc_driver_path=C:/GaussDB/jdbc/gsjdbc4.jar"
```

验证当前环境变量：

```powershell
echo $env:GAUSSDB_TEST_URL
```

### 3.4 临时方式：使用 --url 参数

三个脚本都支持 `--url` 参数：

```powershell
python .\scripts\check_windows_env.py --url "gaussdb+jdbc://用户名:URL编码后的密码@数据库IP:端口/数据库名?jdbc_driver_path=JDBC驱动jar路径"
python .\scripts\run_integration_probe.py --url "gaussdb+jdbc://用户名:URL编码后的密码@数据库IP:端口/数据库名?jdbc_driver_path=JDBC驱动jar路径"
python .\scripts\run_syntax_probe.py --url "gaussdb+jdbc://用户名:URL编码后的密码@数据库IP:端口/数据库名?jdbc_driver_path=JDBC驱动jar路径"
```

### 3.5 如果必须修改脚本

原则上不需要改脚本。若测试环境要求把地址写入脚本，请只修改 `main()` 中 `parser.add_argument("--url", default=...)` 的默认值，或在脚本开头增加环境变量赋值。

推荐改法：

```python
os.environ.setdefault(
    "GAUSSDB_TEST_URL",
    "gaussdb+jdbc://用户名:URL编码后的密码@数据库IP:端口/数据库名?jdbc_driver_path=JDBC驱动jar路径",
)
```

不要把真实账号密码提交到 Git 仓库，也不要截图外发包含密码的命令行。

## 4. 测试场景和执行内容

### 场景 1：Windows 环境检查

目的：

- 检查 Python 版本。
- 检查 `PATH`。
- 检查 `JayDeBeApi`、`JPype1`、`SQLAlchemy`、本项目方言包是否可导入。
- 检查 JDBC jar 路径是否存在。
- 可选检查真实数据库 `select 1`。

执行：

```powershell
python .\scripts\check_windows_env.py
python .\scripts\check_windows_env.py --url "$env:GAUSSDB_TEST_URL"
```

通过标准：

- `import jaydebeapi` 显示 `[ OK ]`。
- `import jpype` 显示 `[ OK ]`。
- `import sqlalchemy` 显示 `[ OK ]`。
- `import gaussdb_sqlalchemy` 显示 `[ OK ]`。
- JDBC driver jar 显示 `[ OK ]`。
- 传入真实库地址后，`live connection: select 1 -> 1`。

### 场景 2：SQLAlchemy 核心集成探针

目的：

- 验证主键、唯一约束、索引反射。
- 验证序列和 `nextval()` 默认值。
- 验证 Alembic Operations。
- 验证常用数据类型：`numeric`、`timestamp`、`date`、`boolean`、`text`、`bytea`。
- 验证 Alembic autogenerate 基础无差异检测。
- 验证复杂索引、表达式索引、视图反射。
- 验证分区表反射。

执行：

```powershell
python .\scripts\run_integration_probe.py --url "$env:GAUSSDB_TEST_URL"
```

通过标准：

输出包含类似内容：

```text
integration probe ok: pk_unique_index,sequence,alembic,data_types,alembic_autogenerate,advanced_reflection,partition_reflection
```

如果目标库不支持脚本中的分区表 DDL，可能输出：

```text
partition_reflection_skipped
```

这种情况表示分区表用例被跳过，需要记录目标库版本、兼容模式和错误信息，并由项目方确认是否需要适配该环境的分区语法。

### 场景 3：A/B/M 兼容语法探针

目的：

- 查看当前数据库兼容模式。
- 探测 PostgreSQL 风格基础语法。
- 探测 Oracle 风格常用语法。
- 探测 MySQL 风格常用语法。

执行：

```powershell
python .\scripts\run_syntax_probe.py --url "$env:GAUSSDB_TEST_URL"
```

关注输出：

```text
PASS    compatibility column probe    [('数据库名', 'A')]
```

或：

```text
PASS    compatibility column probe    [('数据库名', 'B')]
```

或：

```text
PASS    compatibility column probe    [('数据库名', 'M')]
```

A 兼容库预期：

- PostgreSQL 基础语法通常通过。
- Oracle 风格基础语法可能通过。
- MySQL 风格的反引号、`ifnull()`、`auto_increment` 可能失败。

B 兼容库预期：

- PostgreSQL 基础语法通常通过。
- 部分 MySQL 风格语法，如反引号、`ifnull()`、`auto_increment`，应通过。
- `current_timestamp()` 形式可能失败，建议使用不带括号的 `current_timestamp` 或 SQLAlchemy 的 `func.current_timestamp()`。

M 兼容库预期：

- MySQL 风格语法通常通过，包括反引号、`ifnull()`、`current_timestamp()`、`auto_increment`。
- Oracle 风格 `nvl`、`sysdate`、`rownum` 可能失败。
- PostgreSQL `serial`、`nextval()` 列默认值、`BYTEA`、`TIMESTAMP WITHOUT TIME ZONE` 可能失败；当前方言已对 SQLAlchemy 常用建表和类型做兼容分支。
- 表达式索引需使用 GaussDB M 可接受的双括号形式；当前方言已将 SQLAlchemy 表达式索引编译为该形式。

### 场景 4：pytest 集成测试

目的：

- 使用 pytest 跑完整测试集。
- 未配置真实库时，真实库集成测试会跳过。
- 配置 `GAUSSDB_TEST_URL` 后，会连接真实库执行集成测试。

执行：

```powershell
python -m pip install -e ".[test]"
pytest -rs
```

只跑真实库集成测试：

```powershell
pytest -m integration -rs
```

如果要一次性验证 A/B/M 三种兼容库，可以分别设置：

```powershell
$env:GAUSSDB_TEST_URL_A="gaussdb+jdbc://用户名:URL编码后的密码@数据库IP:端口/A兼容数据库名?jdbc_driver_path=C:/GaussDB/jdbc/gaussdbjdbc.jar"
$env:GAUSSDB_TEST_URL_B="gaussdb+jdbc://用户名:URL编码后的密码@数据库IP:端口/B兼容数据库名?jdbc_driver_path=C:/GaussDB/jdbc/gaussdbjdbc.jar"
$env:GAUSSDB_TEST_URL_M="gaussdb+jdbc://用户名:URL编码后的密码@数据库IP:端口/M兼容数据库名?jdbc_driver_path=C:/GaussDB/jdbc/gaussdbjdbc.jar"
pytest .\tests\test_compatibility_scenarios.py -m integration -rs
```

也可以使用逗号分隔的 `GAUSSDB_TEST_URLS` 一次传入多个真实库连接串。

通过标准：

- 本地单元测试全部通过。
- 如果配置了 `GAUSSDB_TEST_URL`，真实库集成测试应通过。
- 如果未配置 `GAUSSDB_TEST_URL`，会看到类似 `GAUSSDB_TEST_URL is not configured` 的 skipped 记录。

## 5. A 兼容、B 兼容和 M 兼容测试建议

建议至少准备三个目标库：

- A 兼容库。
- B 兼容库。
- M 兼容库。

分别设置连接串并运行：

```powershell
$env:GAUSSDB_TEST_URL="gaussdb+jdbc://用户名:URL编码后的密码@数据库IP:端口/A兼容数据库名?jdbc_driver_path=C:/GaussDB/jdbc/gsjdbc4.jar"
python .\scripts\check_windows_env.py --url "$env:GAUSSDB_TEST_URL"
python .\scripts\run_integration_probe.py --url "$env:GAUSSDB_TEST_URL"
python .\scripts\run_syntax_probe.py --url "$env:GAUSSDB_TEST_URL"

$env:GAUSSDB_TEST_URL="gaussdb+jdbc://用户名:URL编码后的密码@数据库IP:端口/B兼容数据库名?jdbc_driver_path=C:/GaussDB/jdbc/gsjdbc4.jar"
python .\scripts\check_windows_env.py --url "$env:GAUSSDB_TEST_URL"
python .\scripts\run_integration_probe.py --url "$env:GAUSSDB_TEST_URL"
python .\scripts\run_syntax_probe.py --url "$env:GAUSSDB_TEST_URL"
```

记录以下信息：

- Windows 版本。
- Python 版本。
- Java 版本。
- GaussDB JDBC Driver jar 路径。
- GaussDB 服务端版本。
- 数据库兼容模式：A 或 B。
- 三个脚本的完整输出。
- 是否出现 `partition_reflection_skipped`。

## 6. 常见问题

### 6.1 import jaydebeapi 或 import jpype 失败

处理：

- 确认已安装 `JayDeBeApi` 和 `JPype1`。
- 确认安装的是当前虚拟环境中的包。
- 执行 `python -m pip list` 查看。

### 6.2 找不到 JDBC driver jar

处理：

- 确认 `jdbc_driver_path` 指向真实存在的 jar 文件。
- Windows 路径建议使用 `/`，例如 `C:/GaussDB/jdbc/gsjdbc4.jar`。
- 如果路径包含空格，请将完整 URL 放在引号中。
- 确认该 jar 与目标 GaussDB 版本兼容。

### 6.3 密码包含 @ 导致连接串解析错误

处理：

- 将 `@` 写成 `%40`。
- 其他特殊字符也需要 URL 编码。

### 6.4 pytest 显示 skipped

如果提示：

```text
GAUSSDB_TEST_URL is not configured
```

说明没有配置真实数据库地址。设置环境变量后重新执行：

```powershell
$env:GAUSSDB_TEST_URL="gaussdb+jdbc://用户名:URL编码后的密码@数据库IP:端口/数据库名?jdbc_driver_path=C:/GaussDB/jdbc/gsjdbc4.jar"
pytest -m integration -rs
```

### 6.5 多线程并发连接失败

本项目通过 JayDeBeApi/JPype 在 Python 进程内调用 JVM。当前 DB-API `threadsafety = 1`，连接对象不应跨线程共享。

建议：

- 每个线程通过 SQLAlchemy engine 独立获取连接。
- 不要在多个线程之间传递同一个 connection 或 session。
- 应用启动阶段先做一次单线程连接预热，再进入高并发请求处理。

### 6.6 语法探针有 FAIL

`run_syntax_probe.py` 的目标是识别当前库支持哪些 SQL 风格。部分 FAIL 不一定是驱动问题，可能是 A/B 兼容模式差异。例如 A 兼容库不支持 MySQL 风格 `auto_increment` 属于预期差异。

### 6.7 ON CONFLICT 报错

GaussDB 集中式不支持 PostgreSQL `ON CONFLICT` upsert 语法。SQLAlchemy PostgreSQL 方言的 `insert(...).on_conflict_do_update()` 会生成 `ON CONFLICT` SQL，如果数据库返回语法或能力限制错误，属于 GaussDB 集中式限制，不是 Windows 环境或 JDBC 驱动安装问题。

### 6.8 M 兼容 LIKE、INTERSECT、EXCEPT 或临时表语法失败

以下现象属于 M 兼容模式的数据库行为差异，不是 Windows 环境问题：

- `LIKE` 默认大小写不敏感，测试断言不能按 A/B 兼容的大小写敏感结果编写。
- `INTERSECT` / `EXCEPT` 不支持，SQLAlchemy 的 `intersect()` / `except_()` 在 M 兼容库上会失败。
- raw SQL `CREATE TEMP TABLE` 不支持，应改为 `CREATE TEMPORARY TABLE`；SQLAlchemy Core 建临时表建议使用 `prefixes=["TEMPORARY"]`。

判断驱动核心能力时，以 `run_integration_probe.py` 和 pytest 集成测试结果为主。

## 7. 测试报告模板

```text
测试人员：
测试日期：
Windows 版本：
Python 版本：
Java 版本：
GaussDB JDBC Driver jar 路径：
GaussDB 服务端版本：
数据库兼容模式：A / B
连接串是否已脱敏：是 / 否

1. check_windows_env.py 结果：
通过 / 不通过
关键输出：

2. run_integration_probe.py 结果：
通过 / 不通过
是否出现 partition_reflection_skipped：
关键输出：

3. run_syntax_probe.py 结果：
通过 / 不通过
A/B 兼容差异：
关键输出：

4. pytest -m integration 结果：
通过 / 不通过 / 未执行
关键输出：

5. 问题记录：
```
