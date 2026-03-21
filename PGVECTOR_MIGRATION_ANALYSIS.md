# PostgreSQL / pgvector 迁移分析与落地说明

## 1. 文档目的

这份文档把两部分内容合并成一版：

- 原有的迁移分析：为什么要从 `JSON + Qdrant` 补齐到 `PostgreSQL + pgvector`
- 已经完成的实际落地：建表、回填 `data/`、回填 pgvector、验证结果、代码说明

目标不是只讲“应该怎么做”，而是明确：

1. 当前项目原来的真实数据形态是什么
2. 这次到底迁了什么
3. PostgreSQL 里现在已经有什么
4. 代码是怎么完成迁移的
5. 当前仍然没切换的部分是什么

---

## 2. 当前项目原始运行形态

迁移前，这个项目的真实运行形态是：

- 文档与任务主数据：本地 JSON
  - `data/documents/*.json`
  - `data/jobs/*.json`
- 解析文本：本地文件
  - `data/parsed/*.txt`
- chunk 数据：本地 JSON
  - `data/chunks/*.json`
- 原始上传文件：本地文件
  - `data/uploads/*`
- 向量检索：Qdrant
- embedding 模型：`BAAI/bge-m3`
- 向量维度：`1024`

也就是说，原来不是“只有向量在 Qdrant”，而是：

- 元数据散在 JSON
- 文件散在 `data/`
- 向量在 Qdrant
- 在线检索依赖 Qdrant

这会带来几个典型问题：

1. 元数据不方便集中查询  
   要查文档状态、任务状态、文件 hash、版本，只能扫 JSON。

2. 数据不统一  
   `document/job` 在文件里，向量在 Qdrant，无法直接做完整 SQL 运维。

3. 不利于后续切换到 pgvector  
   因为你不能只迁 `embedding`，还必须补齐文档主数据、chunk 元数据和资产文件映射。

---

## 3. 先把几个概念说清楚

### 3.1 什么是 embedding

`embedding` 不是你在检索结果里看到的 `0.83`、`0.91` 那种分数。

`embedding` 是一条向量，例如：

```text
[0.012, -0.337, 0.291, ...]
```

在当前项目里：

- 每个 chunk 会有一条 `1024` 维向量
- 每个 query 也会生成一条 `1024` 维向量
- 检索时是 `query 向量` 和 `chunk 向量` 做相似度计算

### 3.2 什么是相似度分数

相似度分数是在线计算出来的结果，例如：

- `0.78`
- `0.91`

这个分数会随着 query 改变而改变，所以它不是数据库里的“固定真源数据”。

### 3.3 什么是 rerank 分数

rerank 分数也是在线算出来的，通常来自重排模型。

它也不是 chunk 自带字段，不应该作为静态主数据写死在主表里。

### 3.4 结论

数据库里应该存的是：

- chunk 文本
- chunk embedding 向量
- 文档和任务元数据

数据库里不应该把“某次 query 的相似度分数”当静态数据长期保存。

---

## 4. 为什么要迁到 PostgreSQL / pgvector

迁移不是为了替换一项技术名词，而是为了统一数据边界。

### 4.1 迁移目标

希望达到：

- `document/job` 元数据可 SQL 查询
- `data/` 目录内容在 PostgreSQL 有镜像
- chunk 文本和向量能进入 PostgreSQL
- 后续具备从 Qdrant 切换到 pgvector 检索的能力

### 4.2 为什么不能只用一个旧表 `knowledge_documents`

原来的 legacy Prisma 模型：

```prisma
model KnowledgeDocument {
  id         String   @id @default(uuid())
  filename   String
  namespace  String   @default("default")
  content    String   @db.Text
  embedding  Unsupported("vector(1536)")?
  metadata   Json?
  createdAt  DateTime @default(now())
}
```

它的问题很明确：

1. 维度不匹配  
   当前项目是 `bge-m3`，维度 `1024`，不是 `1536`。

2. 文档和 chunk 混在一起  
   这张表更像“chunk 表”，并不是文档主表。

3. 缺少稳定业务主键  
   当前系统已经稳定使用：
   - `doc_id`
   - `chunk_id`

4. 缺少 ACL 字段  
   当前项目已有：
   - `tenant_id`
   - `department_ids`
   - `role_ids`
   - `owner_id`
   - `visibility`
   - `classification`

5. 缺少版本和生命周期字段  
   当前项目已有：
   - `current_version`
   - `status`
   - `latest_job_id`
   - `file_hash`

6. 不适合作为企业级 RAG 主数据模型  
   它适合 demo，不适合当前项目 V1 的真实数据结构。

---

## 5. 当前 PostgreSQL 表设计

在不改 legacy 表结构的前提下，本次迁移新增并使用了这些表：

### 5.1 文档主表

- `rag_source_documents`

承接：

- `doc_id`
- `tenant_id`
- `file_name`
- `file_hash`
- `source_type`
- `source_system`
- `created_by`
- `owner_id`
- `visibility`
- `classification`
- `department_ids`
- `role_ids`
- `tags`
- `status`
- `current_version`
- `latest_job_id`
- `storage_path`

### 5.2 文档版本表

- `rag_document_versions`

承接：

- 文档版本
- `parsed_path`
- `chunk_path`
- `chunk_count`
- `vector_count`

### 5.3 入库任务表

- `rag_ingest_jobs`

承接：

- `job_id`
- `doc_id`
- `version`
- `status`
- `stage`
- `progress`
- `retry_count`
- `error_code`
- `error_message`

### 5.4 chunk 向量表

- `rag_knowledge_chunks`

这是当前项目真正用于承接 pgvector 的表。

关键字段包括：

- `chunkId`
- `docId`
- `version`
- `tenantId`
- `namespace`
- `chunkIndex`
- `content`
- `embeddingModel`
- `embedding vector(1024)`
- `sourcePath`
- `parsedPath`
- `charStart`
- `charEnd`
- `pageNo`
- `ownerId`
- `visibility`
- `classification`
- `departmentIds`
- `roleIds`
- `metadata`

### 5.5 data 目录镜像表

- `rag_data_assets`

这张表是本次迁移新增的关键补充。

它的作用是把 `data/` 下的文件资产整体镜像进 PostgreSQL，包括：

- `documents/*.json`
- `jobs/*.json`
- `parsed/*.txt`
- `chunks/*.json`
- `uploads/*`

---

## 6. 当前 Prisma 结构说明

当前核心结构位于：

- [prisma/schema.prisma](/home/reggie/vscode_folder/Enterprise-grade_RAG/prisma/schema.prisma)

关键点：

1. 保留 legacy `KnowledgeDocument` 不动
2. 新增 `RagSourceDocument`
3. 新增 `RagDocumentVersion`
4. 新增 `RagIngestJob`
5. 新增 `RagKnowledgeChunk`
6. 新增 `RagDataAsset`

其中 `RagKnowledgeChunk.embedding` 明确使用：

```prisma
embedding Unsupported("vector(1024)")?
```

这和当前 `bge-m3` 的向量维度一致。

---

## 7. 本次已经完成的迁移范围

这次不是只做了“分析”，而是已经完成了实际迁移。

### 7.1 已完成项

已经完成：

1. PostgreSQL metadata 建表
2. `DocumentRecord / IngestJobRecord` 从 JSON 回填到 PostgreSQL
3. `data/` 目录全量镜像进 PostgreSQL
4. `chunk` 文本写入 PostgreSQL
5. `Qdrant -> pgvector` 回填，把向量写入 `rag_knowledge_chunks.embedding`

### 7.2 尚未切换项

当前**还没有**自动切换的是：

- 在线检索主链路仍然默认走 Qdrant

也就是说：

- PostgreSQL 里现在已经有完整副本
- 但在线 `retrieval_service` 还没有改成从 pgvector 检索

---

## 8. 本次实际执行结果

以下是已经实际执行并验证过的结果。

### 8.1 data 全量回填结果

执行脚本后，成功导入：

- 文档：`5`
- 任务：`5`
- 文档版本：`5`
- chunk：`557`
- 资产文件：`30`

### 8.2 PostgreSQL 当前总量

数据库当前总记录数为：

- `rag_source_documents = 17`
- `rag_ingest_jobs = 17`
- `rag_document_versions = 5`
- `rag_knowledge_chunks = 557`
- `rag_data_assets = 30`

这里要注意：

- `17 / 17` 不是只来自 `data/`
- 其中包含你之前在线测试时写进去的历史 document/job 记录

### 8.3 只看本次 data 回填对应的命中结果

只按 `data/` 里那一批文档和任务核对，已经确认：

- `matched_data_documents = 5`
- `matched_data_jobs = 5`
- `matched_data_versions = 5`
- `matched_data_chunks = 557`

### 8.4 data 资产类型分布

`rag_data_assets` 当前分布为：

- `chunk_json = 4`
- `document_json = 5`
- `job_json = 5`
- `parsed_text = 4`
- `upload_file = 12`

### 8.5 pgvector 回填结果

执行 pgvector 回填后，结果是：

- `target_chunks = 557`
- `qdrant_points_scanned = 557`
- `qdrant_matches = 557`
- `qdrant_written = 557`
- `reembedded = 0`
- `remaining_without_embedding = 0`

实际核对 PostgreSQL：

- `embedding_not_null = 557`
- `embedding_null = 0`

这说明：

- 557 条 chunk 文本已经有对应 pgvector 向量
- 当前 PostgreSQL 里的向量数据已经完整

---

## 9. 本次用到的迁移脚本

### 9.1 metadata 回填脚本

- [scripts/backfill_postgres_metadata.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/scripts/backfill_postgres_metadata.py)

用途：

- 把 `data/documents/*.json`
- 把 `data/jobs/*.json`

写入：

- `rag_source_documents`
- `rag_ingest_jobs`

核心实现：

- [backend/app/tools/postgres_metadata_backfill.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/tools/postgres_metadata_backfill.py)
- [backend/app/db/postgres_metadata_store.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/db/postgres_metadata_store.py)

### 9.2 data 全量回填脚本

- [scripts/backfill_postgres_data.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/scripts/backfill_postgres_data.py)

用途：

- 把 `data/` 目录整体导入 PostgreSQL

写入：

- `rag_source_documents`
- `rag_ingest_jobs`
- `rag_document_versions`
- `rag_knowledge_chunks`
- `rag_data_assets`

核心实现：

- [backend/app/tools/postgres_data_backfill.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/tools/postgres_data_backfill.py)

### 9.3 pgvector 回填脚本

- [scripts/backfill_pgvector_embeddings.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/scripts/backfill_pgvector_embeddings.py)

用途：

- 给 `rag_knowledge_chunks.embedding` 回填向量

支持三种模式：

- `qdrant`
- `reembed`
- `hybrid`

核心实现：

- [backend/app/tools/pgvector_backfill.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/tools/pgvector_backfill.py)

### 9.4 旧的一体化导入脚本

仓库里还保留了一份旧脚本：

- [scripts/import_data_qdrant_to_rag_tables.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/scripts/import_data_qdrant_to_rag_tables.py)

它更像“一次性历史导入工具”，不是这次主线方案的核心。

当前更推荐的使用方式是：

1. `backfill_postgres_metadata.py`
2. `backfill_postgres_data.py`
3. `backfill_pgvector_embeddings.py`

这样职责更清楚，也更容易排查。

---

## 10. 代码实现原理说明

## 10.1 `PostgresMetadataStore` 做了什么

文件：

- [backend/app/db/postgres_metadata_store.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/db/postgres_metadata_store.py)

它负责：

- 把 `DocumentRecord` 写入 `rag_source_documents`
- 把 `IngestJobRecord` 写入 `rag_ingest_jobs`
- 按 `docId / jobId` 做幂等 upsert
- 启动时检查必需表是否存在

关键处理：

1. 兼容 Prisma DSN  
   Prisma 常用：

```text
postgresql://...?...schema=public
```

   但 `psycopg` 不能直接按这个 schema 参数工作，所以代码里增加了：

- `_normalize_psycopg_dsn`

   用来把 Prisma 风格 DSN 转成 libpq 可接受的形式。

2. 补稳定主键  
   Prisma 表里有独立 `id` 字段，而业务上真正稳定的主键是：

- `docId`
- `jobId`

   所以代码里用 `_stable_uuid(...)` 生成稳定 `id`，保证：

- 多次回填不重复造脏数据
- upsert 可重复执行

## 10.2 `postgres_data_backfill.py` 做了什么

文件：

- [backend/app/tools/postgres_data_backfill.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/tools/postgres_data_backfill.py)

它的职责是把 `data/` 整体导入 PostgreSQL。

主要步骤：

1. 读取 `documents/*.json`
2. 读取 `jobs/*.json`
3. 推导 `document_version`
4. 读取 `chunks/*.json`
5. 读取 `parsed/*.txt`
6. 递归扫描 `data/` 下所有文件
7. 写入 PostgreSQL

其中：

- `build_document_version_rows(...)`
  - 负责构造版本行
- `build_chunk_rows(...)`
  - 负责把 chunk JSON 变成 `rag_knowledge_chunks` 行
- `build_asset_rows(...)`
  - 负责把 `data/` 文件变成 `rag_data_assets` 行

### 10.2.1 为什么新增 `rag_data_assets`

因为你要求的是：

- “把 `data/` 全部放入服务器端 psql”

如果只存 document/job/chunk 元数据，还不算“全部”。

所以增加 `rag_data_assets` 承接：

- 原始 JSON
- parsed 文本
- chunk JSON
- 上传文件资产

这样 PostgreSQL 里就有 `data/` 的完整镜像。

### 10.2.2 为什么要包一层 `Jsonb`

PostgreSQL 脚本导入时，Python `dict` 不能直接自动适配到 `jsonb`。

所以代码里增加了：

- `_with_jsonb(...)`

把：

- `metadata: dict`

显式包装成 `Jsonb(...)` 再插库，避免：

- `cannot adapt type 'dict'`

这种错误。

## 10.3 `pgvector_backfill.py` 做了什么

文件：

- [backend/app/tools/pgvector_backfill.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/tools/pgvector_backfill.py)

这部分是本次最关键的新能力。

它负责把 `rag_knowledge_chunks.embedding` 填满。

核心流程：

1. 先查 PostgreSQL 里哪些 chunk 还没有 embedding
2. 如果模式是 `qdrant` 或 `hybrid`
   - 从 Qdrant scroll 全量点位
   - 按 `chunk_id` 对齐 PostgreSQL chunk
   - 直接把 Qdrant 向量写入 PostgreSQL
3. 如果模式是 `reembed` 或 `hybrid`
   - 对剩余缺失 chunk 调 embedding 服务
   - 重新生成向量
   - 再写回 PostgreSQL

### 10.3.1 为什么默认推荐 `hybrid`

因为它最稳：

- Qdrant 里已有的向量，不必重算
- Qdrant 缺失的，再按文本重算

这样兼顾：

- 迁移速度
- 成本
- 完整性

### 10.3.2 `qdrant` / `reembed` / `hybrid` 的差异

#### `qdrant`

优点：

- 快
- 不依赖 embedding 服务吞吐

缺点：

- 前提是 Qdrant 里原向量仍然完整可用

#### `reembed`

优点：

- 不依赖 Qdrant 旧向量
- 最适合模型升级后重建向量

缺点：

- 慢
- 依赖 embedding 服务

#### `hybrid`

优点：

- 先搬现成向量
- 再补缺失
- 最适合作为迁移默认模式

这次实际执行时，由于 Qdrant 中 `557` 条都存在，所以结果是：

- 全部由 Qdrant 直接补齐
- 不需要额外 reembed

## 10.4 为什么 `rag_knowledge_chunks` 现在能做 pgvector 检索

因为它已经具备：

1. `content`
2. `embedding vector(1024)`
3. ACL 字段
4. `docId`
5. `chunkId`
6. `chunkIndex`

这意味着它已经具备后续改写检索 SQL 的基础。

---

## 11. 实际执行命令

## 11.1 建表

由于本机 Prisma 版本兼容问题，这次实际使用的是：

```bash
DATABASE_URL="postgresql://root:123456@192.168.10.200:5432/welllihaidb?schema=public" \
npx prisma@6.19.0 db push --schema prisma/schema.prisma
```

## 11.2 metadata 回填

```bash
python scripts/backfill_postgres_metadata.py \
  --dsn "postgresql://root:123456@192.168.10.200:5432/welllihaidb?schema=public"
```

## 11.3 data 全量回填

```bash
python scripts/backfill_postgres_data.py \
  --dsn "postgresql://root:123456@192.168.10.200:5432/welllihaidb?schema=public"
```

## 11.4 pgvector 回填

```bash
python scripts/backfill_pgvector_embeddings.py --mode hybrid
```

---

## 12. 验证方法

## 12.1 看健康检查

```bash
curl http://127.0.0.1:8020/api/v1/health
```

关注：

- `metadata_store.provider = postgres`

## 12.2 看 PostgreSQL 表数量

```sql
SELECT COUNT(*) FROM public.rag_source_documents;
SELECT COUNT(*) FROM public.rag_ingest_jobs;
SELECT COUNT(*) FROM public.rag_document_versions;
SELECT COUNT(*) FROM public.rag_knowledge_chunks;
SELECT COUNT(*) FROM public.rag_data_assets;
```

## 12.3 看 pgvector 是否完整

```sql
SELECT COUNT(*) FROM public.rag_knowledge_chunks WHERE embedding IS NOT NULL;
SELECT COUNT(*) FROM public.rag_knowledge_chunks WHERE embedding IS NULL;
```

当前结果应为：

- `embedding IS NOT NULL = 557`
- `embedding IS NULL = 0`

---

## 13. 当前状态总结

现在 PostgreSQL 里已经有：

- `data/` 的完整镜像
- 文档元数据
- 任务元数据
- 文档版本
- 557 条 chunk 文本
- 557 条 pgvector 向量

所以可以明确说：

- PostgreSQL 现在已经有你当前 `data/` 的完整可用副本
- 不是只有 document/job
- 也不是只有 chunk 文本
- 向量也已经进去了

---

## 14. 当前仍然存在的边界

虽然 PostgreSQL 里已经有完整 pgvector 数据，但当前项目仍有一个边界：

- 在线检索主链路仍然默认走 Qdrant

也就是说：

- PostgreSQL 已经具备检索数据基础
- 但代码还没有正式切换到“用 PostgreSQL 做向量检索”

当前状态可以概括为：

- **数据已迁好**
- **检索未切换**

---

## 15. 下一步建议

如果继续往下推进，建议按这个顺序：

1. 先保留 Qdrant 作为在线检索主链路
2. 增加一个 PostgreSQL pgvector 检索实现
3. 做 A/B 对照验证：
   - Qdrant top-k
   - pgvector top-k
4. 验证召回结果、耗时、ACL 过滤
5. 确认稳定后，再决定是否把默认检索切到 PostgreSQL

更直白一点：

- 现在已经完成“数据迁移”
- 下一阶段才是“检索切换”

---

## 16. 一句话结论

这次迁移已经把当前项目从：

`JSON + 本地文件 + Qdrant`

扩展成：

`PostgreSQL 元数据 + PostgreSQL data 镜像 + PostgreSQL pgvector + Qdrant 在线检索`

当前 PostgreSQL 里已经有完整 `data/` 内容和 `557` 条 chunk 向量；下一步如果要继续推进，重点就不再是“迁数据”，而是“把在线检索从 Qdrant 切到 PostgreSQL pgvector”。
