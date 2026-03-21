# Prisma / pgvector 迁移说明

## 1. 文档目的

这份文档说明 4 件事：

- 当前 Prisma 表结构在整个项目中的定位
- 为什么需要把当前项目逐步迁移到 PostgreSQL + pgvector
- 这次实际是怎么迁移到目标数据库的
- 后续继续接入业务代码时要注意什么

目标数据库：

```env
DATABASE_URL="postgresql://root:123456@192.168.10.200:5432/welllihaidb?schema=public"
```

最终 Prisma 文件位置：

- [prisma/schema.prisma](/home/reggie/vscode_folder/Enterprise-grade_RAG/prisma/schema.prisma)

---

## 2. 当前项目原本的存储形态

在这次迁移之前，这个仓库并不是 PostgreSQL 主导架构，而是：

- 文档与任务主数据：本地 JSON 文件
- 向量检索：Qdrant
- 问答与检索接口：FastAPI
- 前端：React + Vite

也就是说，原本的真实运行方式是：

1. 上传文件
2. 解析文件
3. 切 chunk
4. 算 embedding
5. 写入 Qdrant
6. 文档和任务元数据写到本地 `data/` 目录

这套方式适合 demo 和本地验证，但不适合后续做：

- 统一数据库管理
- 标准化备份
- 多服务共享
- 审计
- SQL 联查
- 版本治理
- 更稳定的生产部署

---

## 3. 原始 Prisma 结构分析

你给的原始 Prisma 结构主要分两部分。

### 3.1 旧 AI 系统的 4 张表

- `AiSession`
- `Message`
- `KnowledgeDocument`
- `PromptTemplate`

这 4 张表本质上对应的是：

- 会话映射
- 历史消息
- 旧版知识库向量文档
- Prompt 模板

这部分已经有自己的业务语义，所以本次迁移原则是：

`不改原表结构，只在旁边新增当前 Enterprise-grade_RAG 需要的表`

### 3.2 `KnowledgeDocument` 的问题

原始表如下：

```prisma
model KnowledgeDocument {
  id         String   @id @default(uuid())
  filename   String
  namespace  String   @default("default")
  content    String   @db.Text
  embedding  Unsupported("vector(1536)")?
  metadata   Json?
  createdAt  DateTime @default(now())

  @@index([namespace])
  @@map("knowledge_documents")
}
```

它适合：

- 单表 demo
- 快速验证 pgvector
- 没有 ACL / 版本 / 任务状态 / 文档生命周期要求的场景

它不适合当前项目直接复用的原因：

1. `1536` 维不匹配  
   当前项目实际 embedding 模型是 `BAAI/bge-m3`，维度是 `1024`，不是 `1536`。

2. 文档和 chunk 混在同一张表  
   当前项目是“文档 -> 多个 chunk -> 向量索引”的结构，单表会导致文档元数据重复很多次。

3. 缺少业务主键  
   当前项目稳定使用：
   - `doc_id`
   - `job_id`
   - `chunk_id`

4. 缺少 ACL 字段  
   当前项目已有：
   - `tenant_id`
   - `visibility`
   - `classification`
   - `department_ids`
   - `role_ids`
   - `owner_id`

5. 缺少生命周期字段  
   当前项目已有：
   - `file_hash`
   - `status`
   - `current_version`
   - `latest_job_id`

所以结论是：

`KnowledgeDocument` 保留，但不能直接承担当前 Enterprise-grade_RAG 的主存储职责。

---

## 4. 为什么要迁移到 PostgreSQL + pgvector

迁移的核心目的不是“为了换数据库而换数据库”，而是为了把当前 demo 结构变成可持续演进的后端底座。

### 4.1 当前本地 JSON + Qdrant 的限制

- 文档主数据不在数据库里，不方便统一管理
- 状态恢复和任务审计不方便做
- 去重、版本、重试逻辑更容易分散
- SQL 联查能力弱
- 备份恢复不统一
- 多实例或多服务接入时不够稳

### 4.2 PostgreSQL + pgvector 的价值

- 文档、任务、chunk 元数据统一进数据库
- 向量和业务字段能在同库管理
- 方便做 SQL 过滤和元数据联查
- 更适合做版本控制、ACL、审计和治理
- 便于未来接 Prisma / Node / 管理后台

### 4.3 为什么不是“直接删掉 Qdrant”

因为当前 Python 后端已经在用 Qdrant，链路已经跑通。

更稳的策略不是立刻替换，而是：

1. 先把 PostgreSQL schema 建好
2. 让 PostgreSQL 成为新的结构化真源
3. 再决定：
   - 保留 Qdrant 做检索副本
   - 或者逐步切到 pgvector 检索

这是一种“先接入、再替换”的迁移方式，风险更低。

---

## 5. 本次最终采用的 Prisma 结构

最终 schema 采取“双层兼容”策略：

### 5.1 保留原表

以下表完全保留，不改结构：

- `ai_sessions`
- `messages`
- `knowledge_documents`
- `prompt_templates`

### 5.2 新增当前项目专用表

新增了 4 张表：

- `rag_source_documents`
- `rag_document_versions`
- `rag_ingest_jobs`
- `rag_knowledge_chunks`

它们分别对应：

#### `rag_source_documents`

文档主表，负责存：

- `docId`
- `tenantId`
- `fileName`
- `fileHash`
- `sourceType`
- `sourceSystem`
- `createdBy`
- `ownerId`
- `visibility`
- `classification`
- `departmentIds`
- `roleIds`
- `tags`
- `namespace`
- `status`
- `currentVersion`
- `latestJobId`
- `storagePath`

#### `rag_document_versions`

版本表，负责存：

- `docId`
- `version`
- `storagePath`
- `parsedPath`
- `chunkPath`
- `chunkCount`
- `vectorCount`
- `indexVersion`
- `isCurrent`

#### `rag_ingest_jobs`

任务表，负责存：

- `jobId`
- `docId`
- `version`
- `fileName`
- `status`
- `stage`
- `progress`
- `retryCount`
- `errorCode`
- `errorMessage`

#### `rag_knowledge_chunks`

当前项目真正使用的向量 chunk 表，负责存：

- `chunkId`
- `docId`
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

---

## 6. 为什么新增表而不是改原表

原因很简单：你已经明确要求：

`不要动原来的表结构`

这个要求本身也是合理的，因为：

1. 原系统可能已经依赖这些旧表
2. 旧 AI 系统和当前 RAG 项目不是一套完全相同的数据模型
3. 强改旧表会引入兼容性风险
4. 新项目的数据语义更复杂，硬塞进旧表不干净

所以现在这套设计的优点是：

- legacy 表继续可用
- 新 RAG 项目有自己的规范表
- 后续可以平滑迁移业务代码
- 不会破坏旧系统

---

## 7. 本次实际迁移过程

### 7.1 连接目标数据库

目标库：

```env
postgresql://root:123456@192.168.10.200:5432/welllihaidb?schema=public
```

连接检查通过，说明数据库端口可达。

### 7.2 Prisma 校验

由于 Prisma 7 对 datasource 配置方式有变动，这次迁移使用 Prisma 6.16.2 完成。

执行过的关键动作：

1. 校验 schema
2. `db push` 到目标库
3. `db pull` 反查数据库结构
4. `migrate diff` 确认数据库已经和 schema 对齐

结果是：

- schema 校验通过
- 数据库已同步
- 差异为空

### 7.3 pgvector 索引

仅声明 `Unsupported("vector(...)")` 还不够，所以额外执行了：

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE INDEX IF NOT EXISTS knowledge_documents_embedding_hnsw_idx
ON "knowledge_documents"
USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS rag_knowledge_chunks_embedding_hnsw_idx
ON "rag_knowledge_chunks"
USING hnsw (embedding vector_cosine_ops);
```

这一步的意义是：

- 不只是“能存向量”
- 而是已经具备基础 ANN 检索索引能力

---

## 8. 迁移完成后数据库里有什么

迁移完成后，`public` schema 中至少包含：

### 原有保留表

- `ai_sessions`
- `messages`
- `knowledge_documents`
- `prompt_templates`

### 新增 RAG 表

- `rag_source_documents`
- `rag_document_versions`
- `rag_ingest_jobs`
- `rag_knowledge_chunks`

### 枚举

- `MessageRole`
- `RagVisibility`
- `RagClassification`
- `RagDocumentStatus`
- `RagIngestJobStatus`

---

## 9. 后续怎么真正把项目接入这套 PostgreSQL

这次做的是：

`把表结构迁到数据库`

还没做的是：

`让当前 Python RAG 代码真正读写这些表`

后续真正接入，建议分 3 步。

### 第 1 步：先把 PostgreSQL 作为“结构化真源”

先把这些对象改成落 PostgreSQL：

- 文档主数据
- 文档版本
- 入库任务
- chunk 元数据

也就是说，把当前 `data/documents`、`data/jobs`、`data/chunks` 这些 JSON 存储逐步替掉。

### 第 2 步：保持 Qdrant 继续跑

短期内不要一上来就移除 Qdrant。

建议：

- PostgreSQL：真源
- Qdrant：检索副本

这样能保证：

- 老链路不断
- 新结构先稳定

### 第 3 步：再评估是否切成 pgvector 检索

等到 PostgreSQL 真源和写入链路稳定之后，再决定：

- 继续 Qdrant 检索
- 或改成 pgvector 检索
- 或做混合检索

---

## 10. 迁移时最需要注意的点

### 10.1 不要把 legacy 表和新表混着写

尤其不要让当前 Python RAG 项目去直接写 `knowledge_documents`，因为：

- 它是 1536 维 legacy 表
- 当前项目实际是 1024 维

当前项目应该写：

- `rag_source_documents`
- `rag_document_versions`
- `rag_ingest_jobs`
- `rag_knowledge_chunks`

### 10.2 向量维度不能搞错

当前项目的 embedding 模型是 `bge-m3`，维度是：

```text
1024
```

如果你后面改成别的 embedding 模型，必须同步调整：

- Prisma schema
- 数据迁移策略
- 向量索引

### 10.3 pgvector 只是“存储能力”，不是全部检索能力

你还需要额外关注：

- 向量索引类型：`hnsw` 或 `ivfflat`
- 相似度算子：`vector_cosine_ops`
- 查询 SQL
- 元数据过滤

### 10.4 ACL 字段不要偷懒都塞进 JSON

像这些字段必须保持结构化：

- `tenantId`
- `visibility`
- `classification`
- `departmentIds`
- `roleIds`
- `ownerId`

因为这些字段未来是要参与过滤的，不只是展示。

### 10.5 先解决“写入一致性”，再考虑“完全替换检索”

更稳的顺序是：

1. 先把 PostgreSQL 表建好
2. 再让文档、任务、chunk 元数据进入 PostgreSQL
3. 再考虑检索是否切到 pgvector

不要反过来一上来就替换检索层。

### 10.6 Prisma 版本要注意

这次迁移使用 Prisma 6.16.2 是因为：

- 这份 schema 是传统写法
- Prisma 7 对 datasource URL 管理方式变了

如果你后面要升级到 Prisma 7，需要额外处理：

- `prisma.config.ts`
- 连接配置迁移

---

## 11. 推荐的后续动作

按优先级建议这样推进：

### P1

- 让 Python 后端真正写入 `rag_source_documents / rag_ingest_jobs / rag_knowledge_chunks`

### P2

- 做一版从现有 JSON / Qdrant 导入 PostgreSQL 的迁移脚本

### P3

- 再评估是否把检索从 Qdrant 切到 pgvector

---

## 12. 一句话结论

这次迁移的本质不是“把老表改掉”，而是：

`在保留旧 AI 系统表结构不变的前提下，为当前 Enterprise-grade_RAG 项目新增一套规范的 PostgreSQL + pgvector 数据结构，并已经成功落到目标数据库 welllihaidb.public。`
