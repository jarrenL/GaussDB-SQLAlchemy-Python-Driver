# Windows 测试指导手册

本文面向 Windows 测试人员，用于验证 `gaussdb-sqlalchemy-driver` 在 Windows 环境下能否安装、加载底层 GaussDB 客户端、连接真实 GaussDB 数据库，并完成 SQLAlchemy 基础能力、A/B 兼容语法探针和扩展集成场景验证。

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

### 1.3 GaussDB 客户端

底层 `gaussdb` Python DB-API 包需要加载 GaussDB/libpq 原生客户端库。Windows 上需提前安装 GaussDB 客户端，并将客户端 `bin` 目录加入 `PATH`。

注意：这里说的“客户端”不是 GaussDB 数据库服务端。数据库服务端可以部署在远程 Linux/云服务器上；Windows 本机只需要能加载客户端 DLL，并通过网络连接远程数据库 IP 和端口。

#### 1.3.1 客户端获取方式

根据 GaussDB 交付方式不同，客户端获取入口可能不同，优先级建议如下：

1. 华为云 GaussDB 控制台下载
   - 适用于华为云托管实例。
   - 登录华为云控制台，进入对应 GaussDB 实例。
   - 在“连接管理”“客户端下载”“驱动/工具下载”或类似入口下载 Windows 客户端。
   - 下载目标应为 Windows x86_64 客户端或 gsql 客户端工具包。

2. 向 DBA 或 GaussDB 运维人员索取
   - 适用于企业内网、私有化或离线交付环境。
   - 要求提供与服务端大版本匹配的 Windows 客户端工具包。
   - 需要包含 `gsql.exe`、`libpq.dll` 或 GaussDB 兼容客户端 DLL，以及依赖 DLL。

3. 从 GaussDB 安装介质或交付包中提取
   - 适用于已有完整 GaussDB 安装包的场景。
   - 不需要在 Windows 本机安装数据库服务端，只需提取 Windows 客户端工具目录。
   - 如果交付包只包含 Linux 客户端，需要向供应商或 DBA 单独获取 Windows 客户端。

4. 使用 openGauss/PostgreSQL 兼容客户端作为临时排查手段
   - 仅建议用于排查 `gsql`/`libpq` 链路是否可用。
   - 本项目最终验证仍应以 GaussDB 官方或项目交付的 Windows 客户端为准。

#### 1.3.2 客户端目录建议

建议将客户端解压到固定目录，例如：

```text
C:\GaussDB\client
```

常见目录结构类似：

```text
C:\GaussDB\client\bin\gsql.exe
C:\GaussDB\client\bin\libpq.dll
C:\GaussDB\client\bin\*.dll
```

也可能是：

```text
C:\GaussDB\client\bin
C:\GaussDB\client\lib
```

以实际交付包为准。关键是 `gsql.exe` 和相关 DLL 所在目录要能被 Windows 找到。

#### 1.3.3 配置 PATH

临时配置当前 PowerShell：

```powershell
$env:PATH="C:\GaussDB\client\bin;$env:PATH"
```

请将 `C:\GaussDB\client\bin` 替换为实际客户端 `bin` 路径。

如果依赖 DLL 放在 `lib` 目录，也一起加入：

```powershell
$env:PATH="C:\GaussDB\client\bin;C:\GaussDB\client\lib;$env:PATH"
```

永久配置可以在 Windows 图形界面中设置：

```text
系统属性 -> 高级 -> 环境变量 -> Path -> 新增客户端 bin 目录
```

配置完成后需要重新打开 PowerShell、命令行、IDE 或服务进程，否则新 `PATH` 不一定生效。

#### 1.3.4 验证客户端是否可用

先确认 Windows 能找到客户端命令：

```powershell
where gsql
gsql --version
```

再确认 DLL 能被搜索到：

```powershell
where libpq.dll
```

如果 `where libpq.dll` 找不到，但客户端包中存在类似 GaussDB 专用 DLL，请记录 DLL 文件名和所在目录，并确认该目录已经加入 `PATH`。

可以用 `gsql` 直接测试远程数据库连通性：

```powershell
gsql -h 数据库IP -p 端口 -d 数据库名 -U 用户名
```

示例：

```powershell
gsql -h 192.168.1.10 -p 8000 -d postgres -U test_user
```

如果 `gsql` 可以连接，但 Python 仍报 DLL 相关错误，通常是 Python 进程启动时没有继承正确的 `PATH`，请重新打开 PowerShell 并重新激活虚拟环境。

#### 1.3.5 Python 侧验证

安装本项目 wheel 后执行：

```powershell
python .\scripts\check_windows_env.py
```

如果传入真实库地址：

```powershell
python .\scripts\check_windows_env.py --url "$env:GAUSSDB_TEST_URL"
```

如果执行测试时报错：

```text
no pq wrapper available
```

通常表示 Python 包已经安装，但 Windows 没有找到 GaussDB/libpq 原生客户端库。优先检查客户端是否安装、`PATH` 是否生效、Python 进程是否重新打开。

如果报缺少 VC++ 运行库或某个 `*.dll` 找不到，请安装对应的 Microsoft Visual C++ Redistributable，或向 DBA/供应商确认客户端包是否缺少依赖 DLL。

### 1.4 数据库账号和权限

测试账号至少需要具备以下权限：

- 连接目标数据库。
- 创建和删除临时表，测试表名前缀为 `codex_*`。
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

## 3. 真实数据库地址配置

### 3.1 连接串格式

推荐使用 SQLAlchemy 连接串：

```text
gaussdb+gaussdb://用户名:密码@数据库IP:端口/数据库名
```

示例：

```text
gaussdb+gaussdb://test_user:test_password@192.168.1.10:8000/postgres
```

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
huawei@123
```

连接串中应写为：

```text
huawei%40123
```

也可以用 Python 生成编码后的密码：

```powershell
python -c "from urllib.parse import quote_plus; print(quote_plus('huawei@123'))"
```

### 3.3 推荐方式：使用环境变量

不建议直接修改脚本源码中的数据库地址。推荐在 PowerShell 当前会话设置环境变量：

```powershell
$env:GAUSSDB_TEST_URL="gaussdb+gaussdb://用户名:URL编码后的密码@数据库IP:端口/数据库名"
```

示例：

```powershell
$env:GAUSSDB_TEST_URL="gaussdb+gaussdb://test_user:huawei%40123@192.168.1.10:8000/postgres"
```

验证当前环境变量：

```powershell
echo $env:GAUSSDB_TEST_URL
```

### 3.4 临时方式：使用 --url 参数

三个脚本都支持 `--url` 参数：

```powershell
python .\scripts\check_windows_env.py --url "gaussdb+gaussdb://用户名:URL编码后的密码@数据库IP:端口/数据库名"
python .\scripts\run_integration_probe.py --url "gaussdb+gaussdb://用户名:URL编码后的密码@数据库IP:端口/数据库名"
python .\scripts\run_syntax_probe.py --url "gaussdb+gaussdb://用户名:URL编码后的密码@数据库IP:端口/数据库名"
```

### 3.5 如果必须修改脚本

原则上不需要改脚本。若测试环境要求把地址写入脚本，请只修改 `main()` 中 `parser.add_argument("--url", default=...)` 的默认值，或在脚本开头增加环境变量赋值。

推荐改法：

```python
os.environ.setdefault(
    "GAUSSDB_TEST_URL",
    "gaussdb+gaussdb://用户名:URL编码后的密码@数据库IP:端口/数据库名",
)
```

不要把真实账号密码提交到 Git 仓库，也不要截图外发包含密码的命令行。

## 4. 测试场景和执行内容

### 场景 1：Windows 环境检查

目的：

- 检查 Python 版本。
- 检查 `PATH`。
- 检查 `gaussdb`、`SQLAlchemy`、本项目方言包是否可导入。
- 可选检查真实数据库 `select 1` 和 `client_encoding`。

执行：

```powershell
python .\scripts\check_windows_env.py
python .\scripts\check_windows_env.py --url "$env:GAUSSDB_TEST_URL"
```

通过标准：

- `import gaussdb` 显示 `[ OK ]`。
- `import sqlalchemy` 显示 `[ OK ]`。
- `import gaussdb_sqlalchemy` 显示 `[ OK ]`。
- 传入真实库地址后，`live connection: select 1 -> 1`。
- `client_encoding` 建议为 `UTF8`。

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

### 场景 3：A/B 兼容语法探针

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

A 兼容库预期：

- PostgreSQL 基础语法通常通过。
- Oracle 风格基础语法可能通过。
- MySQL 风格的反引号、`ifnull()`、`auto_increment` 可能失败。

B 兼容库预期：

- PostgreSQL 基础语法通常通过。
- 部分 MySQL 风格语法，如反引号、`ifnull()`、`auto_increment`，应通过。
- `current_timestamp()` 形式可能失败，建议使用不带括号的 `current_timestamp` 或 SQLAlchemy 的 `func.current_timestamp()`。

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

通过标准：

- 本地单元测试全部通过。
- 如果配置了 `GAUSSDB_TEST_URL`，真实库集成测试应通过。
- 如果未配置 `GAUSSDB_TEST_URL`，会看到类似 `GAUSSDB_TEST_URL is not configured` 的 skipped 记录。

## 5. A 兼容和 B 兼容测试建议

建议至少准备两个目标库：

- A 兼容库。
- B 兼容库。

分别设置连接串并运行：

```powershell
$env:GAUSSDB_TEST_URL="gaussdb+gaussdb://用户名:密码@数据库IP:端口/A兼容数据库名"
python .\scripts\check_windows_env.py --url "$env:GAUSSDB_TEST_URL"
python .\scripts\run_integration_probe.py --url "$env:GAUSSDB_TEST_URL"
python .\scripts\run_syntax_probe.py --url "$env:GAUSSDB_TEST_URL"

$env:GAUSSDB_TEST_URL="gaussdb+gaussdb://用户名:密码@数据库IP:端口/B兼容数据库名"
python .\scripts\check_windows_env.py --url "$env:GAUSSDB_TEST_URL"
python .\scripts\run_integration_probe.py --url "$env:GAUSSDB_TEST_URL"
python .\scripts\run_syntax_probe.py --url "$env:GAUSSDB_TEST_URL"
```

记录以下信息：

- Windows 版本。
- Python 版本。
- GaussDB 客户端版本或安装路径。
- GaussDB 服务端版本。
- 数据库兼容模式：A 或 B。
- 三个脚本的完整输出。
- 是否出现 `partition_reflection_skipped`。
- 是否出现 `no pq wrapper available`。

## 6. 常见问题

### 6.1 import gaussdb 失败

处理：

- 确认已安装 `gaussdb` Python 包。
- 确认安装的是当前虚拟环境中的包。
- 执行 `python -m pip list` 查看。

### 6.2 no pq wrapper available

处理：

- 安装 GaussDB 客户端。
- 将客户端 `bin` 目录加入 `PATH`。
- 关闭并重新打开 PowerShell。
- 重新激活虚拟环境后再执行测试。

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
$env:GAUSSDB_TEST_URL="gaussdb+gaussdb://用户名:URL编码后的密码@数据库IP:端口/数据库名"
pytest -m integration -rs
```

### 6.5 语法探针有 FAIL

`run_syntax_probe.py` 的目标是识别当前库支持哪些 SQL 风格。部分 FAIL 不一定是驱动问题，可能是 A/B 兼容模式差异。例如 A 兼容库不支持 MySQL 风格 `auto_increment` 属于预期差异。

判断驱动核心能力时，以 `run_integration_probe.py` 和 pytest 集成测试结果为主。

## 7. 测试报告模板

```text
测试人员：
测试日期：
Windows 版本：
Python 版本：
GaussDB 客户端路径：
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
