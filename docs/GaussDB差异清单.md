# GaussDB 与 PostgreSQL 兼容差异清单

本文记录项目在真实 GaussDB 环境验证时发现的 SQLAlchemy 方言差异。客户目标兼容模式为 A 兼容和 B 兼容。Windows 实机验证和 GaussDB 505.1 专项验证需另行补充。

面向交付的支持范围和不兼容项统一见 `docs/兼容性声明.md`。

## 已发现并处理

### 1. 版本字符串格式

GaussDB 返回格式示例：

```text
gaussdb (GaussDB Kernel 507.0.0 build ...)
```

SQLAlchemy PostgreSQL 方言默认只识别 `PostgreSQL x.y.z` 或 `EnterpriseDB x.y.z`。

处理方式：

- 解析并保留真实内核版本到 `dialect.gaussdb_server_version_info`
- `dialect.server_version_info` 使用保守 PostgreSQL 兼容版本，避免触发不兼容的新系统表查询

### 2. 默认 SQL_ASCII 导致文本返回 bytes

部分环境默认 `client_encoding=SQL_ASCII`，底层 `gaussdb` DB-API 会将文本列返回为 `bytes`。

处理方式：

- 方言默认传入 `client_encoding=UTF8`
- 允许用户通过连接串显式覆盖

### 3. PostgreSQL 新版本系统表字段不兼容

直接复用 SQLAlchemy PostgreSQL 反射查询时，可能访问当前 GaussDB 不支持或不兼容的字段/表达式：

- `pg_attribute.attgenerated`
- `pg_attribute.attidentity`
- `pg_type.typcollation` 相关查询

处理方式：

- 覆盖 `get_columns()` 和 `get_multi_columns()`
- 使用保守的 `pg_class`、`pg_namespace`、`pg_attribute`、`pg_attrdef` 查询完成基础列反射

### 4. 索引反射返回值与 PostgreSQL 方言预期不一致

SQLAlchemy PostgreSQL 方言在索引反射时会处理 PostgreSQL 特有的 index flag。真实 GaussDB 环境中该路径返回的 flag 类型与 SQLAlchemy 预期不一致，导致位运算失败。

处理方式：

- 覆盖 `get_indexes()`
- 使用 `pg_index`、`pg_class`、`pg_attribute` 直接反射普通索引和唯一索引列

### 5. 约束反射采用保守查询

为了避免 PostgreSQL 新版本系统表字段差异，主键和唯一约束反射使用保守查询。

处理方式：

- 覆盖 `get_pk_constraint()`
- 覆盖 `get_unique_constraints()`

真实环境还发现当前 GaussDB 不支持 PostgreSQL 风格的 `unnest(...) with ordinality`。约束和索引反射改用 `attnum = any(...)` 的保守写法。

### 6. HSTORE 不应默认启用

HSTORE 是 PostgreSQL 扩展，不应假设轻量化集中式环境可用。

处理方式：

- 默认关闭 `use_native_hstore`

### 7. Alembic 不认识 gaussdb 方言名

Alembic 的 DDL 实现按 SQLAlchemy `dialect.name` 查找。`gaussdb` 是第三方方言名，默认不在 Alembic 注册表中。

处理方式：

- 增加 `gaussdb_sqlalchemy.alembic`
- 注册 `GaussDBImpl`
- 继承 Alembic PostgreSQL DDL 实现以支持基础 Operations

## 已纳入集成测试

- SQLAlchemy Core 建表、插入、查询、删表
- 事务回滚
- 批量插入
- ORM CRUD
- 列元数据反射
- 主键、唯一约束、普通索引反射
- 序列和 `nextval()` 默认值
- Alembic Operations 建表、加列、删表
- 连接池基础复用

其中主键、唯一约束、普通索引、序列默认值和 Alembic Operations 也可通过 `scripts/run_integration_probe.py` 在没有 pytest 的数据库主机上验证。

## 兼容语法探针

可使用 `scripts/run_syntax_probe.py` 对当前连接库执行 PostgreSQL、Oracle 风格、MySQL 风格 SQL 探测。

已验证 A 兼容环境：

```text
GaussDB Kernel 507.0.0
datcompatibility = A
```

结果摘要：

- PostgreSQL 风格基础语法通过：`::` cast、`now()`、`limit`、`serial`
- Oracle 风格基础语法通过：`dual`、`nvl`、`sysdate`、`rownum`
- MySQL 风格部分不通过：反引号别名、`ifnull()`、`current_timestamp()`、`auto_increment`
- MySQL 风格 `concat()` 在该环境可用，但不能据此认为支持 M 兼容

结论：

当前包可连接并使用 A/Oracle 兼容库中的 PG 基础语法和部分 Oracle 风格语法，但仍然不是 O 兼容专用 SQLAlchemy 方言；MySQL/M 兼容语法在当前 A 兼容库和 PG 协议路径下不成立。

已验证 B 兼容临时库：

```text
GaussDB Kernel 507.0.0
datcompatibility = B
```

结果摘要：

- PostgreSQL 风格基础语法通过：`::` cast、`now()`、`limit`、`serial`
- Oracle 风格基础语法仍可通过：`dual`、`nvl`、`sysdate`、`rownum`
- MySQL B 兼容常用语法通过：反引号别名、`ifnull()`、`concat()`、`auto_increment`
- `current_timestamp()` 形式未通过，应使用不带括号的 `current_timestamp` 或目标库支持的写法
- 主键、唯一约束、普通索引、序列默认值、Alembic Operations 探针通过

结论：

当前包在 GaussDB 507.0.0 上可连接 A 兼容和 B 兼容数据库，并完成基础 SQLAlchemy 能力验证。B 兼容不同于 M-Compatibility，当前结论不能外推到 M 兼容或 MySQL 原生协议。

## 待继续验证

- GaussDB 505.1 专项环境
- Windows 实机 DLL/PATH/客户端加载
- SSL 连接
- 更多数据类型：`numeric`、`timestamp`、`date`、`boolean`、`text`、`bytea`
- Alembic autogenerate 差异检测
- 复杂索引、表达式索引、分区表、视图反射
