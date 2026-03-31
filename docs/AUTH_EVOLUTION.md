# Auth 演进方案

> 状态：草稿 | 日期：2026-03-31 | 版本：v0.3 → V2 路线图

## 1. 当前 auth_service 的边界与适用范围

### 1.1 架构概览

```
auth_service.py          token 签发 / 验证 / 吊销
identity_service.py      身份目录（角色、部门、用户）的只读查询
schemas/auth.py          数据模型定义
core/_auth.py            配置（secret、issuer、过期时间）
api/v1/endpoints/auth.py HTTP 入口（login / logout / me / bootstrap）
```

### 1.2 功能边界

| 能力 | 实现方式 | 说明 |
|------|---------|------|
| 登录 | 用户名 + 密码 | PBKDF2-SHA256（200k iterations）验证 |
| Token 签发 | 自定义 `base64(payload).base64(hmac-sha256)` 格式 | 非 JWT 标准 |
| Token 验证 | HMAC 签名校验 + 过期检查 + 用户活跃状态检查 | 每次请求同步校验 |
| Token 吊销 | `revoked_token_ids: set[str]`（内存） | 仅存 jti |
| 权限上下文 | `AuthContext` 携带 user / role / department / accessible_department_ids | |
| 部门隔离 | 读链路可选隔离（`department_query_isolation_enabled`），写链路强制隔离 | |
| RBAC | 3 个固定角色：employee / department_admin / sys_admin | |

### 1.3 适用范围

当前 v0.3 鉴权设计适用于：

- **单实例部署**：开发环境和单节点试点
- **单租户场景**：所有用户属于 `tenant_id=wl`
- **内部系统**：企业内部使用，非公网暴露
- **中小用户量**：身份目录从 JSON 文件加载，全量放内存

---

## 2. 已知限制与风险

### 2.1 多实例部署问题

**现状：** `AuthService` 是单例（`@lru_cache`），`revoked_token_ids` 存在进程内存。

**影响：**
- 实例 A 上 `POST /auth/logout` 吊销的 token，实例 B 仍然接受
- 水平扩展（多 worker / 多节点）时吊销语义不一致
- 滚动部署时新实例不继承旧实例的吊销集合

### 2.2 重启后吊销丢失

**现状：** `revoked_token_ids` 没有持久化。

**影响：**
- 服务重启后所有已吊销的 token 恢复有效
- 攻击者获取的 token 在重启窗口内可复用
- 与"logout = 立即失效"的用户预期不符

### 2.3 自定义 Token 格式

**现状：** Token 采用 `base64(JSON).base64(HMAC-SHA256)` 格式，非 RFC 7519 JWT。

**影响：**
- 无法与标准 JWT 生态（jose、jwt.io、API Gateway 验签）互操作
- 前端无法使用标准 JWT 解码库解析 payload
- 第三方系统集成需要额外适配层
- 缺少 `alg` 头部，存在算法协商攻击面的理论风险（虽然当前硬编码 SHA256）

### 2.4 身份目录不可变

**现状：** `IdentityService` 启动时从 JSON 文件一次性加载，运行时不可修改。

**影响：**
- 增删用户/部门需要重启服务
- 密码修改无法实时生效（除非替换 JSON 后重启）
- 无法实现自助注册、密码修改等自助功能

### 2.5 无 Token 刷新机制

**现状：** Token 过期后只能重新登录。

**影响：**
- 用户活跃使用中被强制退出体验差
- 高频操作场景下登录请求集中

### 2.6 无速率限制

**现状：** 登录端点无暴力破解防护。

**影响：**
- 密码可被暴力枚举（虽有 200k iterations 增加成本，但仍有风险）

---

## 3. 演进路线

### V1.1 — 生产就绪补丁（最小改动）

**目标：** 修复影响生产安全的关键问题，不改变架构。

| 改动项 | 范围 | 优先级 |
|--------|------|--------|
| 吊销持久化到 Redis | `auth_service.py` | P0 |
| 登录速率限制 | `auth.py` 端点层 | P0 |
| Token 格式迁移为标准 JWT | `auth_service.py` `_encode/_decode` | P1 |
| 最小注释补全 | `auth_service.py` 关键方法 | P2 |

**详细说明：**

1. **吊销持久化（P0）**
   - `revoked_token_ids` 改为 Redis SET + TTL（TTL = token 剩余有效期）
   - 保留内存缓存作为热路径优化
   - 多实例通过共享 Redis 获得一致的吊销语义

2. **速率限制（P0）**
   - 在 `/auth/login` 端点增加基于 IP + username 的滑动窗口限流
   - 建议阈值：5 次 / 60 秒
   - 可使用 FastAPI 中间件或装饰器模式

3. **JWT 标准化（P1）**
   - 替换 `_encode_token` / `_decode_token` 为标准 JWT（HS256）
   - 保留现有 `AuthTokenPayload` 结构作为 claims
   - 前端无需改动（Bearer token 透传）
   - 向后兼容：支持双格式验证窗口期

### V2 — 企业级鉴权

**目标：** 支持多租户、可扩展的身份管理和会话管理。

| 改动项 | 范围 | 优先级 |
|--------|------|--------|
| 身份目录迁入 PostgreSQL | `identity_service.py` + 新增 migration | P0 |
| Refresh Token 机制 | `auth_service.py` + `schemas/auth.py` | P0 |
| 多租户隔离强化 | 全链路 | P1 |
| RBAC → ABAC 扩展 | `schemas/auth.py` + 权限引擎 | P1 |
| OAuth2 / SSO 集成 | 新增 `sso_provider` 服务 | P2 |
| 审计日志 | 新增 `audit_log` 服务 | P2 |

**详细说明：**

1. **身份目录数据库化（P0）**
   - 用户、部门、角色从 JSON 迁入 PostgreSQL 表
   - 支持运行时增删改查（admin API）
   - 密码修改、用户启停实时生效
   - 现有 `IdentityBootstrapData` 作为 seed migration

2. **Refresh Token（P0）**
   - 登录时签发一对：access_token（短，15min）+ refresh_token（长，7d）
   - Refresh token 存 Redis，支持即时吊销
   - 新增 `POST /auth/refresh` 端点

3. **多租户隔离（P1）**
   - `tenant_id` 从 token claims 传播到所有数据层查询
   - 数据库行级安全（Row Level Security）或应用层强制过滤
   - 租户级别的配置隔离（LLM provider、embedding model 等）

---

## 4. V1.1 最小代码补充

### 4.1 已有注释补充

以下注释已存在于代码中，记录了关键设计决策：

- `auth_service.py:27` — `# v0.3 最小鉴权服务`
- `schemas/auth.py:6` — `# v0.3 冻结最小角色集合`
- `schemas/auth.py:7` — `# 当前权限范围只区分部门级和全局级`

### 4.2 建议补充的最小注释

在 `auth_service.py` 的 `revoke_token` 方法增加已知限制说明：

```python
def revoke_token(self, token_id: str) -> None:
    # WARNING(v0.3): 吊销集合仅存内存，重启后丢失，多实例不同步。
    # V1.1 将迁移到 Redis SET + TTL。详见 docs/AUTH_EVOLUTION.md。
    self.revoked_token_ids.add(token_id.strip())
```

在 `_encode_token` 方法增加 JWT 迁移说明：

```python
def _encode_token(self, payload: AuthTokenPayload) -> str:
    # NOTE(v0.3): 自定义 base64+HMAC 格式，非标准 JWT。
    # V1.1 将迁移到标准 JWT (HS256)。详见 docs/AUTH_EVOLUTION.md。
```

### 4.3 最小回归测试

现有测试已覆盖核心场景（7 个端点测试 + 9 个授权过滤测试）。

建议补充的最小测试用例：

| 测试 | 说明 |
|------|------|
| `test_auth_revoke_is_per_process` | 验证两个 `AuthService` 实例之间吊销不共享（记录当前行为，V1.1 修复后改为验证共享） |
| `test_auth_token_format_is_base64_hmac` | 验证 token 结构（记录当前自定义格式，V1.1 迁移 JWT 后此测试需更新） |
| `test_auth_tampered_signature_rejected` | 验证篡改签名的 token 被拒绝 |

---

## 5. 兼容性策略

### Token 格式迁移

V1.1 从自定义格式迁移到 JWT 时，建议：

1. **双格式验证窗口**：`_decode_token` 同时尝试自定义格式和 JWT 格式
2. **新签发全部使用 JWT**：`_encode_token` 只输出 JWT
3. **窗口期 = token 最大有效期**（当前 60 分钟）
4. 窗口期过后移除自定义格式支持

### 前端影响

- 前端仅使用 `access_token` 作为 Bearer 透传，格式变更对前端透明
- `LoginResponse` schema 不变
- 无需前端配合改动

---

## 6. 决策记录

| 日期 | 决策 | 原因 |
|------|------|------|
| 2026-03-31 | V1.1 吊销用 Redis 而非数据库 | 性能要求（每次请求检查）、已有 Redis 基础设施 |
| 2026-03-31 | V1.1 JWT 使用 HS256 而非 RS256 | 单签发者场景、简化密钥管理、避免过早引入非对称密钥 |
| 2026-03-31 | V2 身份目录使用 PostgreSQL 而非独立 LDAP | 与现有 pgvector/元数据基础设施统一、减少运维复杂度 |
