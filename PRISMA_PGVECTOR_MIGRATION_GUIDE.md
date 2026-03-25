# Prisma / pgvector 迁移指南

最后核对时间：2026-03-23

这份文档聚焦 3 个问题：

1. 这个仓库里 Prisma 现在到底管哪些 PostgreSQL 表
2. pgvector 在当前项目里是如何落地的
3. 如果你要继续推进从 `JSON + Qdrant` 向 `PostgreSQL + pgvector` 过渡，应该按什么顺序做

这不是一份泛化教程，而是基于当前仓库的真实代码、真实 schema 和当前数据库状态整理出来的落地指南。

---

## 1. 一句话结论

当前项目已经完成了 **Prisma schema 落地 + PostgreSQL 建表 + pgvector 向量列落地 + 历史数据回填**，但还没有完成 **在线检索主链路从 Qdrant 切到 pgvector**。

更准确地说：

- Prisma 已经管理当前项目的 PostgreSQL 结构
- `rag_source_documents` / `rag_ingest_jobs` 已经能作为在线 metadata 真源
- `rag_document_versions` / `rag_knowledge_chunks` / `rag_data_assets` 已经通过 backfill 迁入 PostgreSQL
- `rag_knowledge_chunks.embedding vector(1024)` 已经补齐
- 当前在线检索仍由 `RetrievalService -> QdrantVectorStore` 执行

所以这份指南的核心不是“如何从零建一个 schema”，而是“如何正确理解当前已经迁了什么、下一步该改哪里”。

---

## 2. Prisma 在这个项目里的角色

### 2.1 不是所有数据库都由 Prisma 管

当前仓库是双数据库思路：

- PostgreSQL
  - 由 Prisma schema 管理
  - 用来承接 AI 元数据和 Enterprise-grade_RAG 的结构化数据
- MySQL
  - 业务系统自己的库
  - 不由 Prisma 管
  - 只给 AI / Tool Calling 做只读查询

这点在 [prisma/schema.prisma](/home/reggie/vscode_folder/Enterprise-grade_RAG/prisma/schema.prisma) 的顶部注释里已经写明。

### 2.2 Prisma 在当前项目真正管理什么

Prisma 现在管理两类表：

1. 旧 AI 系统原有表
   - `ai_sessions`
   - `messages`
   - `knowledge_documents`
   - `prompt_templates`

2. Enterprise-grade_RAG 迁移后新增表
   - `rag_source_documents`
   - `rag_document_versions`
   - `rag_ingest_jobs`
   - `rag_knowledge_chunks`
   - `rag_data_assets`

### 2.3 Prisma 在这里不是“ORM 演示”，而是 schema 真源

当前你应该把 Prisma 理解成：

- PostgreSQL 结构定义来源
- pgvector 列定义来源
- 后续 Node/管理后台接库时的类型契约来源

而不是简单理解成“后端现在所有读写都已经走 Prisma Client”。

当前真实情况是：

- Python 服务在线写 metadata 主要用 `psycopg`
- Prisma 负责定义 schema，不是 Python 主链路运行时 ORM

---

## 3. 当前 schema 的关键结构

当前核心文件：

- [prisma/schema.prisma](/home/reggie/vscode_folder/Enterprise-grade_RAG/prisma/schema.prisma)

### 3.1 数据源定义

当前 PostgreSQL 数据源定义是：

```prisma
datasource db {
  provider   = "postgresql"
  url        = env("DATABASE_URL")
  extensions = [pgvector(map: "vector")]
}
```

这表示两件事：

1. 当前 schema 依赖 PostgreSQL
2. 当前数据库必须启用 `vector` extension

### 3.2 为什么 `previewFeatures = ["postgresqlExtensions"]`

当前 generator 开启了：

```prisma
previewFeatures = ["postgresqlExtensions"]
```

这是因为 schema 里声明了：

- `extensions = [pgvector(map: "vector")]`

如果没有这个能力，Prisma 不能正确表达 “这个 PostgreSQL schema 依赖 pgvector 扩展”。

### 3.3 最关键的 5 张 RAG 表

| Prisma Model | 物理表 | 作用 |
| --- | --- | --- |
| `RagSourceDocument` | `rag_source_documents` | 文档主表 |
| `RagDocumentVersion` | `rag_document_versions` | 文档版本 |
| `RagIngestJob` | `rag_ingest_jobs` | ingest 任务状态 |
| `RagKnowledgeChunk` | `rag_knowledge_chunks` | chunk 文本和向量元数据 |
| `RagDataAsset` | `rag_data_assets` | `data/` 目录文件镜像 |

### 3.4 表关系图

```mermaid
erDiagram
    RagSourceDocument ||--o{ RagDocumentVersion : has
    RagSourceDocument ||--o{ RagIngestJob : has
    RagSourceDocument ||--o{ RagKnowledgeChunk : has
    RagSourceDocument ||--o{ RagDataAsset : has
    RagIngestJob ||--o{ RagDataAsset : has

    RagSourceDocument {
        string docId
        string tenantId
        string fileName
        string fileHash
        string status
        int currentVersion
        string latestJobId
    }

    RagDocumentVersion {
        string docId
        int version
        int chunkCount
        int vectorCount
        bool isCurrent
        string status
    }

    RagIngestJob {
        string jobId
        string docId
        string status
        string stage
        int progress
        int retryCount
    }

    RagKnowledgeChunk {
        string chunkId
        string docId
        int chunkIndex
        string embeddingModel
        vector embedding
    }

    RagDataAsset {
        string assetKey
        string kind
        string relativePath
        string docId
        string jobId
    }
```

---

## 4. 为什么不能直接复用 `KnowledgeDocument`

当前 legacy 表：

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

这个表不能直接承担当前项目主存储职责，原因是具体的，不是抽象的：

1. 向量维度不匹配  
   当前项目 embedding 模型是 `BAAI/bge-m3`，维度是 `1024`，不是 `1536`。

2. 它没有文档 / 版本 / 任务拆层  
   当前项目真实结构是：
   - document
   - version
   - ingest job
   - chunk

3. 它没有当前项目已经落地的 ACL / 生命周期字段  
   例如：
   - `tenantId`
   - `visibility`
   - `classification`
   - `departmentIds`
   - `roleIds`
   - `ownerId`
   - `currentVersion`
   - `latestJobId`
   - `fileHash`

4. 它更像 demo 级向量表  
   不适合作为企业级 RAG 的主数据模型。

所以当前正确策略不是去“硬改旧表”，而是：

- 保留 `KnowledgeDocument` 不动
- 在旁边新增当前项目自己的 RAG 表结构

---

## 5. pgvector 在当前 schema 里是怎么落地的

### 5.1 向量列定义

当前真正承接 pgvector 的表是：

- `RagKnowledgeChunk`

它的向量列定义是：

```prisma
embedding Unsupported("vector(1024)")?
```

这和当前 embedding 模型完全一致：

- `BAAI/bge-m3`
- 维度 `1024`

### 5.2 为什么用 `Unsupported("vector(1024)")`

Prisma 目前不能把 pgvector 当成普通标量类型直接建模成 `Float[]` 那种高层抽象，所以这里用：

- `Unsupported("vector(1024)")`

它的意义是：

- Prisma 能把列建出来
- Prisma schema 能表达这个字段确实是原生 `vector(1024)`
- 但你不能指望 Prisma Client 对这个字段提供完整高层操作体验

这也是为什么当前仓库里：

- schema 用 Prisma 定义
- 向量补数和 metadata 写入用 `psycopg`

### 5.3 当前数据库里 pgvector 已经不是“待办”

实测当前数据库已经满足：

- `vector` extension 已安装
- `rag_knowledge_chunks.embedding` 已有数据
- 当前 `embedding IS NULL = 0`
- 当前 `embedding IS NOT NULL = 557`
- HNSW 索引已存在：
  - `rag_knowledge_chunks_embedding_hnsw_idx`

也就是说，pgvector 在数据库层面已经是“可用状态”，不是“设计图状态”。

---

## 6. 当前真实落地状态

下面这些数字不是文档推演，而是 2026-03-23 实测快照。

### 6.1 PostgreSQL 当前行数

| 表名 | 当前行数 |
| --- | ---: |
| `rag_source_documents` | 17 |
| `rag_ingest_jobs` | 17 |
| `rag_document_versions` | 5 |
| `rag_knowledge_chunks` | 557 |
| `rag_data_assets` | 30 |

### 6.2 为什么 `17 / 17 / 5 / 557 / 30` 这个组合很重要

这个组合说明当前项目不是简单的“已经全切”：

- `rag_source_documents = 17`
- `rag_ingest_jobs = 17`

说明在线 metadata 已经持续进入 PostgreSQL。

但：

- `rag_document_versions = 5`
- `rag_knowledge_chunks = 557`

说明版本和 chunk 层并没有随着每一次在线上传实时补齐，而是目前主要依赖 backfill。

所以你不能把当前架构理解成：

- “所有在线 ingest 结果都自动写进 PostgreSQL 向量表”

当前更准确的理解是：

- “metadata 在线写 PostgreSQL”
- “chunk/vector/data-asset 主要通过 backfill 补齐”

### 6.3 当前 `rag_knowledge_chunks` 的实际完成度

实测：

- chunk 总数：`557`
- `embedding IS NOT NULL`：`557`
- `embedding IS NULL`：`0`

这说明只要你从 PostgreSQL 读，它已经具备完整的向量检索数据基础。

### 6.4 当前 `rag_data_assets` 的意义

当前 `rag_data_assets = 30`，它不是“附加表”，而是这次 Prisma 迁移非常关键的补充。

它解决的问题是：

- 如果只迁 document/job/chunk 元数据，你并没有真正把 `data/` 目录整体纳入 PostgreSQL

而 `rag_data_assets` 能承接：

- `documents/*.json`
- `jobs/*.json`
- `parsed/*.txt`
- `chunks/*.json`
- `uploads/*`

所以这张表的价值是：

- 把 `data/` 从磁盘散文件变成数据库可审计资产

---

## 7. 当前在线链路和 Prisma schema 的关系

### 7.1 当前在线链路图

```mermaid
flowchart TD
    A[Upload / API 请求] --> B[DocumentService]
    B --> C[保存原始文件到 data/uploads]
    B --> D[写 metadata]
    D --> D1[rag_source_documents]
    D --> D2[rag_ingest_jobs]

    B --> E[DocumentIngestionService]
    E --> F[parse]
    F --> G[data/parsed/*.txt]
    E --> H[chunk]
    H --> I[data/chunks/*.json]
    E --> J[embedding]
    J --> K[Qdrant]

    L[RetrievalService] --> M[query embedding]
    M --> N[Qdrant search]
```

### 7.2 这张图对应的真实代码

在线主链路关键代码：

- [document_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/document_service.py)
- [ingestion_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/ingestion_service.py)
- [retrieval_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/retrieval_service.py)
- [qdrant_store.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/vectorstores/qdrant_store.py)

当前关键事实：

1. `DocumentService` 在 `RAG_POSTGRES_METADATA_ENABLED=true` 时会写：
   - `rag_source_documents`
   - `rag_ingest_jobs`

2. `DocumentIngestionService` 仍然写：
   - `data/parsed/*.txt`
   - `data/chunks/*.json`
   - Qdrant collection

3. `RetrievalService` 当前检索模式固定是：
   - `mode = "qdrant"`

所以当前 Prisma schema 虽然已经具备 pgvector 表结构，但**在线读取路径还没有切换到这些表**。

---

## 8. 当前 backfill 链路和 Prisma schema 的关系

### 8.1 当前 backfill 流程图

```mermaid
flowchart LR
    A[data/documents + data/jobs] --> B[backfill_postgres_metadata.py]
    B --> C[rag_source_documents + rag_ingest_jobs]

    D[data/] --> E[backfill_postgres_data.py]
    E --> F[rag_document_versions]
    E --> G[rag_knowledge_chunks]
    E --> H[rag_data_assets]

    I[Qdrant / embedding service] --> J[backfill_pgvector_embeddings.py]
    J --> K[rag_knowledge_chunks.embedding]
    J --> L[同步 rag_document_versions.vectorCount]
```

### 8.2 三个脚本各自负责什么

#### `scripts/backfill_postgres_metadata.py`

职责：

- 把 `data/documents/*.json`
- 把 `data/jobs/*.json`

写入：

- `rag_source_documents`
- `rag_ingest_jobs`

#### `scripts/backfill_postgres_data.py`

职责：

- 扫整个 `data/`
- 构造：
  - document version
  - chunk rows
  - data asset rows

写入：

- `rag_source_documents`
- `rag_ingest_jobs`
- `rag_document_versions`
- `rag_knowledge_chunks`
- `rag_data_assets`

#### `scripts/backfill_pgvector_embeddings.py`

职责：

- 给 `rag_knowledge_chunks.embedding` 回填向量

支持模式：

- `qdrant`
- `reembed`
- `hybrid`

默认推荐 `hybrid`，因为它优先复用 Qdrant 旧向量，再补缺失 embedding。

### 8.3 为什么这三步不能混成一步理解

这三类动作解决的是不同层次的问题：

1. metadata backfill  
   解决 “document/job 元数据进 PostgreSQL”

2. data backfill  
   解决 “version/chunk/asset 进 PostgreSQL”

3. pgvector backfill  
   解决 “chunk 向量真正补齐”

如果只做第 1 步，你有的是 metadata，不是可检索向量库。  
如果只做第 2 步，你有的是 chunk 文本，不是完整 pgvector。  
必须第 1、2、3 步一起完成，PostgreSQL 才算具备“结构化副本 + 向量副本”。

---

## 9. 实际迁移时该怎么做

### 9.1 先准备环境变量

当前项目里最关键的配置是：

```env
RAG_POSTGRES_METADATA_ENABLED=true
RAG_POSTGRES_METADATA_DSN=postgresql://root:123456@192.168.10.200:5432/welllihaidb?schema=public
DATABASE_URL=postgresql://root:123456@192.168.10.200:5432/welllihaidb?schema=public
RAG_QDRANT_URL=http://192.168.10.200:6333
RAG_QDRANT_COLLECTION=enterprise_rag_v1_local_bge_m3
```

这里有两个容易踩坑的点：

1. Python 运行时读的是：
   - `RAG_POSTGRES_METADATA_DSN`
   - 或回退 `DATABASE_URL`

2. Prisma schema 读的是：
   - `DATABASE_URL`

所以如果你只配一边，往往会出现：

- Prisma 能建表，但 Python 服务连不上
- 或 Python 能写 metadata，但 Prisma 命令找不到库

### 9.2 建表

当前推荐的建表命令是：

```bash
DATABASE_URL="postgresql://root:123456@192.168.10.200:5432/welllihaidb?schema=public" \
npx prisma@6.19.0 db push --schema prisma/schema.prisma
```

为什么这里显式写 `prisma@6.19.0`：

- 这版是当前项目已经实际用过并验证过的版本
- 这样能避免本机全局 Prisma 版本不一致导致 schema push 行为漂移

### 9.3 然后做 metadata backfill

```bash
python scripts/backfill_postgres_metadata.py \
  --dsn "postgresql://root:123456@192.168.10.200:5432/welllihaidb?schema=public"
```

### 9.4 再做 `data/` 全量 backfill

```bash
python scripts/backfill_postgres_data.py \
  --dsn "postgresql://root:123456@192.168.10.200:5432/welllihaidb?schema=public"
```

### 9.5 最后补 pgvector

```bash
python scripts/backfill_pgvector_embeddings.py --mode hybrid
```

这个顺序不要反过来。  
原因很直接：

- 你必须先有 `rag_knowledge_chunks`
- 才谈得上给它补 `embedding`

---

## 10. Prisma 能做什么，不能做什么

### 10.1 Prisma 能做的

Prisma 在当前项目里适合负责：

- 定义 PostgreSQL 表结构
- 定义 `vector(1024)` 列
- 定义枚举、关系、索引声明
- 给 Node/管理端提供统一 schema 视图

### 10.2 Prisma 当前不适合直接承担的

Prisma 在当前项目里不适合直接承担：

- Python 在线 ingest 主链路的所有实时写入
- pgvector 大批量回填
- Qdrant -> PostgreSQL 向量搬运
- ANN 索引治理

原因是：

1. 当前主业务逻辑在 Python/FastAPI
2. 批量导入和向量列更新更适合 `psycopg`
3. ANN 索引仍需要 SQL 级控制

### 10.3 为什么 HNSW 索引没有放在 Prisma 里一次性解决

Prisma schema 能定义向量列，但对 HNSW / IVF Flat 这种索引能力仍然不够细。

所以当前项目采取的是更实用的做法：

- Prisma 负责把表和列建出来
- `pgvector_backfill.py` 负责确保 ANN 索引存在

当前实测已经有：

```sql
CREATE INDEX rag_knowledge_chunks_embedding_hnsw_idx
ON public.rag_knowledge_chunks
USING hnsw (embedding vector_cosine_ops)
WHERE embedding IS NOT NULL;
```

---

## 11. 当前 schema 已经支持什么，尚不支持什么

### 11.1 已支持

当前 Prisma schema 已经能稳定支持：

- 文档主数据
- 任务状态
- 文档版本
- chunk 文本
- 1024 维 pgvector
- `data/` 文件镜像
- ACL / owner / tenant 等治理字段

### 11.2 尚未完成在线接入的能力

当前 schema 虽然已经有，但在线链路还没有完全利用这些能力：

- `rag_document_versions` 不是在线实时维护
- `rag_knowledge_chunks` 不是在线实时写入
- `rag_data_assets` 不是在线实时镜像
- `RetrievalService` 还没有从 PostgreSQL 读向量

也就是说，当前 schema 具备能力，不代表当前流量已经走这套能力。

---

## 12. 如果下一步继续推进，应该怎么改

### 12.1 第一阶段：让在线 ingest 真正写全 PostgreSQL

这一阶段建议改动目标：

- 在线 ingest 完成后，同步写：
  - `rag_document_versions`
  - `rag_knowledge_chunks`
  - `rag_data_assets`

这样做的结果是：

- 新文档不再依赖 backfill 才能在 PostgreSQL 里完整出现

### 12.2 第二阶段：增加 pgvector 检索实现，但先不切主读

建议增加：

- `PgvectorVectorStore`
- 或 `PgvectorRetrievalService`

然后做双跑：

```mermaid
flowchart LR
    A[query] --> B[生成 query embedding]
    B --> C1[Qdrant 检索]
    B --> C2[pgvector 检索]
    C1 --> D[对比 top-k / chunkId / score]
    C2 --> D
    D --> E[结果稳定后再切主读]
```

### 12.3 第三阶段：再决定 Qdrant 的角色

等 pgvector 检索稳定后，你再决定：

1. 保留 Qdrant 作为检索副本
2. 或让 PostgreSQL / pgvector 成为唯一向量主库

这个决定不应该在 schema 刚落地时就做。

---

## 13. 当前最容易误解的 5 个点

1. “Prisma schema 已经有 pgvector 列”  
   不等于 “在线检索已经走 pgvector”。

2. “`rag_source_documents` / `rag_ingest_jobs` 已经在增长”  
   不等于 “`rag_document_versions` / `rag_knowledge_chunks` 也在实时增长”。

3. “当前数据库里有 557 条向量”  
   不等于 “这些向量一定是在线 ingest 直接写进去的”。  
   当前主要是通过 backfill 补进去的。

4. “保留 `KnowledgeDocument`”  
   不等于 “当前项目实际还在用它做主向量表”。

5. “Prisma 可以定义 vector 列”  
   不等于 “Prisma 就适合做当前项目全部向量写入和批处理”。

---

## 14. 推荐你把这份文档当成什么用

这份文档最适合作为：

- schema 设计说明
- PostgreSQL / pgvector 落地状态说明
- 后续改在线链路的开发基线

它不适合作为：

- “项目已经完全切换 pgvector”的对外口径

因为到今天为止，最关键的事实仍然是：

- **schema 已经切过去了**
- **数据副本也已经补过去了**
- **在线主检索还没有切过去**

---

## 15. 最终判断

如果只从 Prisma / schema 角度看，这次迁移已经是成功的：

- 新表结构合理
- legacy 兼容保留
- pgvector 维度和当前模型一致
- 数据库里已经有真实数据和真实向量

如果从系统流量路径角度看，这次迁移仍然处在过渡期：

- metadata 已部分在线化
- chunk/vector 仍偏 backfill 驱动
- retrieval 主读仍是 Qdrant

所以当前最准确的说法是：

- **Prisma / pgvector 基础设施已经建好**
- **要把它真正变成线上主路径，还需要继续改在线 ingest 和 retrieval**
