# 当前实现链路与数据流说明

本文描述的是当前代码库里**已经实现并可运行**的链路，不是最初方案文档里的完整企业级目标架构。

一句话结论：

- 在线主检索链路当前还是 **Qdrant**
- `document/job` 元数据可以走 **本地 JSON**，也可以切到 **PostgreSQL**
- `rag_document_versions / rag_knowledge_chunks / rag_data_assets / pgvector embedding` 目前主要是**迁移 / 补数 / 分析支路**
- 不是当前线上请求的必经路径

---

## 1. 当前系统分成哪几条链路

当前实际可以分成 5 条链路：

1. 同步上传入库链路  
   `POST /api/v1/documents/upload`

2. 异步上传入库链路  
   `POST /api/v1/documents` -> Celery -> `GET /api/v1/ingest/jobs/{job_id}`

3. 检索链路  
   `POST /api/v1/retrieval/search`

4. 问答链路  
   `POST /api/v1/chat/ask`

5. PostgreSQL / pgvector 迁移补数链路  
   `scripts/backfill_postgres_data.py`  
   `scripts/backfill_pgvector_embeddings.py`

其中：

- 1 到 4 是业务主链路
- 5 是把现有 `data/` 和 Qdrant 内容补进 PostgreSQL 的数据治理链路

---

## 2. 当前总体结构

```text
前端(React/Vite)
    |
    v
FastAPI
    |
    +--> DocumentService
    |      +--> 本地 uploads/documents/jobs
    |      +--> 可选 PostgreSQL(document/job metadata)
    |      +--> Celery 投递异步任务
    |
    +--> DocumentIngestionService
    |      +--> DocumentParser
    |      +--> TextChunker
    |      +--> EmbeddingClient
    |      +--> QdrantVectorStore
    |
    +--> RetrievalService
    |      +--> EmbeddingClient(query embedding)
    |      +--> Qdrant search
    |
    +--> ChatService
           +--> RetrievalService
           +--> RerankerClient(当前是 heuristic)
           +--> LLMGenerationClient(mock / ollama / openai-compatible)
```

---

## 3. 不同数据现在是怎么走的

### 3.1 原始上传文件

来源：

- 前端上传文件
- FastAPI 接收 `UploadFile`

去向：

- 落到 `data/uploads/`

作用：

- 保留原始文件
- 后续解析链路读取这个原始文件

备注：

- 文件名最终会变成 `doc_id__原始文件名`
- 文档哈希 `file_hash` 会在上传阶段计算，用于去重

---

### 3.2 document 元数据

内容：

- `doc_id`
- `tenant_id`
- `file_name`
- `file_hash`
- `source_type`
- `visibility`
- `classification`
- `department_ids`
- `role_ids`
- `owner_id`
- `latest_job_id`
- `storage_path`
- `status`

当前有两种存储模式：

1. 默认模式：本地 JSON  
   落到 `data/documents/*.json`

2. 开启 `RAG_POSTGRES_METADATA_ENABLED=true` 后：PostgreSQL  
   落到 `rag_source_documents`

注意：

- 当前在线检索主链路**不直接读取** `rag_source_documents`
- 它主要承担 document metadata 真源角色

---

### 3.3 ingest job 元数据

内容：

- `job_id`
- `doc_id`
- `status`
- `stage`
- `progress`
- `retry_count`
- `error_code`
- `error_message`

当前有两种存储模式：

1. 默认模式：本地 JSON  
   落到 `data/jobs/*.json`

2. PostgreSQL 模式  
   落到 `rag_ingest_jobs`

作用：

- 前端轮询 job 状态
- worker 重试
- `dead_letter` 终态管理

---

### 3.4 解析后的纯文本

来源：

- `DocumentParser.parse()`

支持格式：

- `.pdf`
- `.md`
- `.markdown`
- `.txt`

去向：

- 落到 `data/parsed/{document_id}.txt`

作用：

- 保留解析结果
- 便于后续追溯、调试、补数

---

### 3.5 chunk 数据

来源：

- `TextChunker.split()`

当前切块方式：

- 按字符长度切
- 带 overlap
- 尝试按自然边界断开

去向：

- 落到 `data/chunks/{document_id}.json`

内容包括：

- `chunk_id`
- `document_id`
- `chunk_index`
- `text`
- `char_start`
- `char_end`

作用：

- 入 Qdrant 前的中间结果
- 迁移 PostgreSQL 时的补数来源

---

### 3.6 embedding 向量

分两类：

1. 文档 chunk embedding
2. 用户 query embedding

当前 provider 支持：

- `mock`
- `ollama`
- `openai-compatible`

当前默认开发基线通常是：

- chunk/query 都走 `EmbeddingClient`
- 模型一般配置为 `BAAI/bge-m3`

去向：

- 文档 chunk 向量：在线主链路写入 Qdrant
- query 向量：只在检索请求内存中使用，不落盘

---

### 3.7 Qdrant 向量数据

这是当前在线检索的主数据面。

写入来源：

- `DocumentIngestionService.ingest_document()`
- `QdrantVectorStore.upsert_document()`

每个 point payload 目前主要包含：

- `chunk_id`
- `document_id`
- `document_name`
- `chunk_index`
- `text`
- `source_path`
- `parsed_path`
- `char_start`
- `char_end`

当前检索时实际读的是这里，不是 PostgreSQL。

---

### 3.8 retrieval 结果

来源：

- `RetrievalService.search()`

流程：

1. query -> embedding
2. Qdrant search
3. 可选 `document_id` 二次过滤

输出字段：

- `chunk_id`
- `document_id`
- `document_name`
- `text`
- `score`
- `source_path`

---

### 3.9 rerank 结果

来源：

- `ChatService.answer()`
- `RerankerClient.rerank()`

当前不是模型 reranker，而是：

- `heuristic` 启发式 rerank
- 用 token overlap + 向量检索分数做线性融合

所以当前链路里：

- 有 rerank 这一步
- 但还不是你方案里说的 `bge-reranker-v2-m3` 线上服务形态

---

### 3.10 LLM 回答和 citations

来源：

- `ChatService.answer()`
- `LLMGenerationClient.generate()`

当前支持：

- `mock`
- `ollama`
- `openai-compatible`

当前回答模式有 3 种：

1. `no_context`  
   没检索到任何 chunk

2. `rag`  
   检索 + rerank + 生成成功

3. `retrieval_fallback`  
   生成模型超时/远端 5xx/请求错误时，直接把证据片段拼成兜底回答

citations 来源：

- rerank 后保留的 chunk

---

## 4. 同步上传链路

接口：

- `POST /api/v1/documents/upload`

这条链路是开发验证最短路径。

```text
前端上传文件
  -> DocumentService.save_upload()
  -> 文件落到 data/uploads
  -> DocumentIngestionService.ingest_document()
  -> DocumentParser 解析
  -> data/parsed/*.txt
  -> TextChunker 切块
  -> data/chunks/*.json
  -> EmbeddingClient 生成 chunk 向量
  -> Qdrant upsert
  -> 返回 document_id / chunk_count / vector_count
```

特点：

- 不经过 Celery
- 请求内同步完成
- 适合本地调试 parse/chunk/embedding/Qdrant

---

## 5. 异步上传链路

接口：

- `POST /api/v1/documents`
- `GET /api/v1/ingest/jobs/{job_id}`
- `POST /api/v1/ingest/jobs/{job_id}/run`

流程：

```text
前端上传文件
  -> DocumentService.create_document()
  -> 写 uploads 原始文件
  -> 保存 document metadata
  -> 保存 ingest job metadata
  -> dispatch_ingest_job(job_id)
  -> Celery worker 消费 ingest.run_job
  -> DocumentService.run_ingest_job()
  -> DocumentIngestionService.ingest_document()
  -> 解析 / 切块 / embedding / Qdrant
  -> job.status = completed
  -> document.status = active
```

状态流转大致是：

- `queued`
- `parsing`
- `chunking`
- `embedding`
- `indexing`
- `completed`

失败时会进入：

- `failed`
- 超过上限后 `dead_letter`

作用：

- 这是当前前端 demo 主用链路
- 前端上传后轮询 job 状态

---

## 6. 检索链路

接口：

- `POST /api/v1/retrieval/search`

流程：

```text
用户 query
  -> RetrievalService.search()
  -> EmbeddingClient.embed_texts([query])
  -> Qdrant search
  -> 可选 document_id 二次过滤
  -> 返回 RetrievedChunk 列表
```

当前实现特点：

- 只有向量检索，没有 BM25
- 没有 RRF
- 没有 ACL 在线过滤
- 支持按 `document_id` 过滤

这意味着当前检索链路是：

- 简洁
- 可跑通
- 但还不是你最早 RAG 架构文档中的完整企业版检索链路

---

## 7. 问答链路

接口：

- `POST /api/v1/chat/ask`

流程：

```text
用户问题
  -> ChatService.answer()
  -> RetrievalService.search()
  -> RerankerClient.rerank()
  -> LLMGenerationClient.generate()
  -> 返回 answer + citations
```

细化后是：

1. 先检索 top_k
2. 再 rerank 到 `rerank_top_n`
3. 把 rerank 后的 snippet 作为 context
4. 交给 LLM 生成回答
5. 返回 citations

当前 citations 是怎么来的：

- 直接来自 rerank 后的检索结果

当前如果 LLM 出问题：

- 不直接 500
- 返回 evidence-based fallback answer

---

## 8. PostgreSQL 现在到底承担什么角色

当前 PostgreSQL 分成两层角色，必须区分开。

### 8.1 在线元数据真源角色

只在开启 `RAG_POSTGRES_METADATA_ENABLED=true` 时生效。

在线读写的是：

- `rag_source_documents`
- `rag_ingest_jobs`

它们替代的是原来的：

- `data/documents/*.json`
- `data/jobs/*.json`

也就是说：

- document/job 元数据可以切到 PostgreSQL
- 但在线检索主链路依然还是 Qdrant

---

### 8.2 迁移 / 补数 / 分析角色

通过脚本补入 PostgreSQL 的还有：

- `rag_document_versions`
- `rag_knowledge_chunks`
- `rag_data_assets`

以及：

- `rag_knowledge_chunks.embedding` 的 pgvector 列

这些不是当前在线写入主链路默认实时维护的，而是通过脚本补进去：

- `scripts/backfill_postgres_data.py`
- `scripts/backfill_pgvector_embeddings.py`

所以要明确：

- 当前在线入库不等于实时把所有 chunk/asset/vector 都写 PostgreSQL
- 这些更多是为了迁移、分析、审计、后续切 pgvector 做准备

---

## 9. pgvector 现在是怎么接进来的

当前 pgvector 不是在线主检索路径。

它的作用是：

1. 把 `rag_knowledge_chunks.embedding` 列补齐
2. 为后续切 PostgreSQL 向量检索做准备
3. 支持离线分析、数据治理、迁移验证

当前补数来源有两种：

1. 从 Qdrant 把已有向量拷贝到 PostgreSQL
2. 重新调用 embedding 服务给 chunk 再算一遍向量

脚本：

- `scripts/backfill_pgvector_embeddings.py`

默认理解应该是：

- Qdrant = 当前线上检索主库
- pgvector = 当前已接入但还没切主的备线/迁移线

---

## 10. data/ 目录现在是什么角色

当前 `data/` 仍然非常重要，它不是缓存，而是当前实现里的核心落盘层。

主要内容：

- `data/uploads/`：原始上传文件
- `data/parsed/`：解析文本
- `data/chunks/`：chunk JSON
- `data/documents/`：document metadata JSON
- `data/jobs/`：job metadata JSON

如果开启 PostgreSQL metadata：

- `documents/jobs` 的真源会切到 PostgreSQL

如果运行 backfill：

- `data/` 里的内容还能继续补到 PostgreSQL 的 `versions/chunks/assets`

所以 `data/` 当前承担三件事：

1. 在线流程的真实落盘
2. 调试追溯
3. PostgreSQL/pgvector 迁移源数据

---

## 11. 前端现在实际怎么调后端

前端 API 在 `frontend/src/api/client.ts`。

主要调用：

- `createDocument(formData)` -> `POST /api/v1/documents`
- `uploadDocument(formData)` -> `POST /api/v1/documents/upload`
- `getIngestJobStatus(jobId)` -> `GET /api/v1/ingest/jobs/{job_id}`
- `runIngestJob(jobId)` -> `POST /api/v1/ingest/jobs/{job_id}/run`
- `searchDocuments(req)` -> `POST /api/v1/retrieval/search`
- `askQuestion(req)` -> `POST /api/v1/chat/ask`
- `getHealth()` -> `GET /api/v1/health`

前端主 demo 现在偏向：

- 异步上传
- 轮询 job
- 再做检索和问答

---

## 12. `/health` 现在能告诉你什么

`GET /api/v1/health` 当前会返回：

- 当前 Qdrant 地址和 collection
- 当前 LLM provider / base_url / model
- 当前 embedding provider / base_url / model
- 当前 Celery broker / result backend / ingest queue
- 当前 metadata store 是 `local_json` 还是 `postgres`
- PostgreSQL DSN 是否已配置

这相当于当前链路的运行时配置快照。

---

## 13. 当前没有走上的那些链路

下面这些能力在你最初方案里有，但当前代码主链路还没有真正上线：

- BM25
- Hybrid retrieval
- RRF 融合
- ACL 在线过滤
- OCR
- PaddleOCR / PP-Structure
- 真正的模型级 reranker 服务
- 生产级 refusal / groundedness 判断
- 会话 memory

所以当前代码的准确定位应该是：

**一个已经跑通上传、异步入库、Qdrant 检索、基础 rerank、LLM 生成、可选 PostgreSQL metadata、可补 pgvector 的 V1 实现。**

---

## 14. 最后给你一个最实用的理解方式

如果只看当前“线上请求到底怎么走”，你可以这么记：

### 上传

`前端 -> FastAPI -> uploads -> parse -> parsed -> chunk -> embeddings -> Qdrant`

### 异步任务状态

`前端 -> FastAPI -> document/job metadata -> Celery -> worker -> ingest -> 状态回写`

### 检索

`query -> embedding -> Qdrant -> results`

### 问答

`question -> retrieval -> heuristic rerank -> LLM -> answer + citations`

### PostgreSQL

`document/job metadata 可在线写入`  
`versions/chunks/assets/vector 目前主要靠 backfill 脚本补入`

---

## 15. 你现在应该怎么理解“不同数据怎么走”

最简版：

- 原始文件走 `uploads`
- 解析文本走 `parsed`
- chunk 走 `chunks`
- 向量主检索走 `Qdrant`
- document/job 元数据走 `local JSON 或 PostgreSQL`
- chunk/version/asset/pgvector 走 `PostgreSQL backfill 支路`
- query 不落盘，实时 embedding 后直接查 Qdrant
- answer/citations 是运行时拼出来的响应，不是长期真源

如果后面你要继续演进到企业版，正确顺序仍然是：

1. 先把当前这套链路口径固定
2. 再决定哪些数据要从 `data/ + Qdrant` 真正切到 `PostgreSQL + pgvector`
3. 最后再加 BM25、ACL、OCR 和更重的企业能力
