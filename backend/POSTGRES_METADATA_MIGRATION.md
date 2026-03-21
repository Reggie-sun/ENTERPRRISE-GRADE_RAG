# PostgreSQL Metadata Migration Runbook

## 1. 目标和范围

当前项目原本把 `DocumentRecord / IngestJobRecord` 落在本地 JSON：

- `data/documents/*.json`
- `data/jobs/*.json`

这会带来三个问题：

- 多实例不共享状态，任务面板容易“看不到数据”。
- 运维排查只能扫文件，不方便 SQL 查询。
- 无法和远端 PostgreSQL 运维体系统一（备份、审计、权限）。

本次迁移只做 **metadata 真源切换**：

- `document/job` 元数据 -> PostgreSQL
- 向量检索仍走 Qdrant（不改现有检索链路）

## 2. Prisma 结构分析（已存在）

在 [prisma/schema.prisma](/home/reggie/vscode_folder/Enterprise-grade_RAG/prisma/schema.prisma) 中，新增了以下表（不改 legacy 表）：

- `rag_source_documents`
- `rag_ingest_jobs`

对应关系：

- `DocumentRecord` -> `rag_source_documents`
- `IngestJobRecord` -> `rag_ingest_jobs`

后端写入代码位于：

- [backend/app/db/postgres_metadata_store.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/db/postgres_metadata_store.py)
- [backend/app/services/document_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/document_service.py)

## 3. 迁移前准备

### 3.1 配置数据库连接

推荐在后端 `.env` 设置：

```env
RAG_POSTGRES_METADATA_ENABLED=true
RAG_POSTGRES_METADATA_DSN=postgresql://root:123456@192.168.10.200:5432/welllihaidb?schema=public
```

说明：

- `RAG_POSTGRES_METADATA_DSN` 优先级高于 `DATABASE_URL`
- 两者都没配时，后端会报错并拒绝以 PostgreSQL 模式启动

### 3.2 建表（必须先做）

在项目根目录执行：

```bash
npx prisma db push --schema prisma/schema.prisma
```

如果你不想开 PostgreSQL 元数据开关，保持：

```env
RAG_POSTGRES_METADATA_ENABLED=false
```

## 4. 回填历史 JSON 元数据

执行 dry-run（先看数量）：

```bash
python scripts/backfill_postgres_metadata.py --dry-run
```

正式回填：

```bash
python scripts/backfill_postgres_metadata.py
```

自定义路径或 DSN：

```bash
python scripts/backfill_postgres_metadata.py \
  --document-dir data/documents \
  --job-dir data/jobs \
  --dsn "postgresql://root:123456@192.168.10.200:5432/welllihaidb?schema=public"
```

脚本位置：

- [scripts/backfill_postgres_metadata.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/scripts/backfill_postgres_metadata.py)

核心实现：

- [backend/app/tools/postgres_metadata_backfill.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/tools/postgres_metadata_backfill.py)

## 5. 验证步骤

### 5.1 健康检查确认后端模式

```bash
curl http://127.0.0.1:8020/api/v1/health
```

关注返回字段：

- `metadata_store.provider` 应为 `postgres`
- `metadata_store.postgres_enabled` 应为 `true`
- `metadata_store.dsn_configured` 应为 `true`

### 5.2 数据库计数验证

```sql
SELECT COUNT(*) FROM public.rag_source_documents;
SELECT COUNT(*) FROM public.rag_ingest_jobs;
```

### 5.3 接口验证

上传新文档后，检查：

- `POST /api/v1/documents` 返回 `doc_id/job_id`
- `GET /api/v1/documents/{doc_id}` 可读
- `GET /api/v1/ingest/jobs/{job_id}` 可读

## 6. 注意事项

- 回填脚本是幂等 upsert，可重复执行。
- 如果 JSON 有坏文件，脚本会输出 `warn`，并以非 0 退出码结束。
- 启用 PostgreSQL 元数据后，后端启动时会校验必需表是否存在，不会“假成功”。
- 这次迁移不触碰 `knowledge_documents` legacy 结构，也不替换 Qdrant 检索。

## 7. 回滚方案

如果你要临时回滚到 JSON 元数据模式：

```env
RAG_POSTGRES_METADATA_ENABLED=false
```

重启后端即可。

