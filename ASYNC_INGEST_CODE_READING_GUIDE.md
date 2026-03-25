# Async Ingest Code Reading Guide

> 注意：这份文档以“异步入库链路讲解”为主，里面出现的 `localhost Redis/Qdrant` 和旧启动命令有些是代码默认值或历史基线示例。
> 当前实际运行基线请以 [LOCAL_DEV_RUNBOOK.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/LOCAL_DEV_RUNBOOK.md) 和 [backend/WORKER_RUNBOOK.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/WORKER_RUNBOOK.md) 为准。

这份文档只讲一件事：怎样把这个项目里“上传文档 -> Celery -> Redis -> worker -> 入库完成”这条主链路看懂。

如果你现在的核心困惑是下面这些，这份文档就是为这个准备的：

- 为什么项目里要同时有 Redis 和 Celery
- 它们两个到底是什么关系
- 为什么看起来像“一个 Redis 端口拉起两个东西”
- `POST /api/v1/documents` 之后，代码到底按什么顺序执行
- 第一次读这个项目，应该从哪个文件开始看

这份文档不试图覆盖整个 RAG 系统的所有功能，而是先把最关键、最容易绕晕的异步入库链路讲透。你先把这一条看懂，再去看 retrieval/chat，会轻松很多。

---

## 1. 先建立一个正确的心智模型

这个项目里有 4 个关键角色：

1. FastAPI API
2. Celery
3. Redis
4. Celery worker

它们的关系不是“包含关系”，而是“协作关系”。

最简化理解：

- FastAPI 负责收请求、存文档元数据、创建 job、返回 `queued`
- Celery 负责定义“异步任务”这套机制
- Redis 负责给 Celery 当 broker 和 result backend
- worker 负责真正执行耗时任务

可以把它理解成：

- API 像前台
- Celery 像派单系统
- Redis 像派单箱和结果登记处
- worker 像后台干活的人

所以不是 Redis 包含 Celery，也不是 Celery 包含 Redis。准确说法是：

- Celery 使用 Redis
- API 和 worker 都连接 Redis
- worker 通过 Celery 从 Redis 拿任务

---

## 2. 为什么这个项目要用 Redis + Celery

因为文档入库不是一个适合放在 HTTP 请求里同步完成的轻任务。

这个项目的入库链路至少包含这些步骤：

1. 接收上传文件
2. 落盘原始文件
3. 解析文档内容
4. 切 chunk
5. 调 embedding 服务生成向量
6. 写入 Qdrant
7. 持续更新任务状态

这条链路里只要 embedding 服务慢一点、Qdrant 有波动、文档大一点，同步接口就会很容易超时，或者让前端一直卡住。

所以这个项目把上传接口拆成了两类：

- 同步入口：`POST /api/v1/documents/upload`
- 异步入口：`POST /api/v1/documents`

真正推荐关注的是异步入口，因为它才是现在项目的主闭环之一。当前数据流文档已经明确写了这条链路：

- `POST /api/v1/documents` -> Celery -> `GET /api/v1/ingest/jobs/{job_id}`

参考：

- `CURRENT_RAG_DATA_FLOW.md`
- `backend/WORKER_RUNBOOK.md`

---

## 3. Redis 在这里到底干什么

Redis 在这个项目里不是主要用来做业务缓存，而是主要给 Celery 做队列基础设施。

配置在这里：

- `backend/app/core/config.py`

关键配置默认值：

```python
celery_broker_url: str = "redis://localhost:6379/0"
celery_result_backend: str = "redis://localhost:6379/1"
celery_ingest_queue: str = "ingest"
```

这 3 个字段非常关键。

它们的含义分别是：

- `broker_url`
  Celery 往哪里投任务，worker 从哪里取任务
- `result_backend`
  Celery 往哪里存任务执行结果和状态
- `ingest_queue`
  任务进入哪个逻辑队列，当前默认是 `ingest`

这里最容易误解的是：

- `redis://localhost:6379/0`
- `redis://localhost:6379/1`

这不是两个端口。

它们都是同一个 Redis 实例，同一个端口 `6379`，只是 Redis 的两个逻辑数据库：

- `/0` 用来放 broker 消息
- `/1` 用来放 result backend 结果

所以“一个端口拉起两个”的准确理解应该是：

- 一个 Redis 服务监听一个端口 `6379`
- Celery 在这个 Redis 上同时用了两个逻辑 DB

不是两个 Redis，也不是两个 Celery。

---

## 4. Celery 在这里到底干什么

Celery 是异步任务框架，不是消息队列本身。

它负责几件事：

1. 定义任务名字
2. 把任务投递到 broker
3. 启动 worker 去消费任务
4. 处理重试
5. 记录任务状态

关键文件：

- `backend/app/worker/celery_app.py`

你可以把这个文件理解成“异步任务系统的总入口”。

这里做了几件事：

1. 创建 Celery app
2. 把 Redis broker/backend 配进去
3. 注册任务 `ingest.run_job`
4. 导出 `celery_app` 给 worker 进程加载
5. 提供 `dispatch_ingest_job()` 给 API 侧投递任务

这个文件里最重要的两个函数是：

- `build_celery_app()`
- `dispatch_ingest_job()`

一个负责“建系统”，一个负责“发任务”。

---

## 5. worker 是什么，和 API 是什么关系

worker 不是 API 的子线程，也不是 API 的一个内部函数。

worker 是一个独立进程。

启动命令在运行手册里很清楚：

```bash
conda run -n rag_backend celery -A backend.app.worker.celery_app:celery_app worker --loglevel=info -Q ingest
```

对应文档：

- `LOCAL_DEV_RUNBOOK.md`
- `backend/WORKER_RUNBOOK.md`

这说明当前系统至少是两个进程协作：

1. API 进程
2. worker 进程

如果用 Docker Compose，一次会拉起来更多服务：

1. `api`
2. `worker`
3. `redis`
4. `qdrant`

参考：

- `docker-compose.yml`

这里也能解释你之前那个疑问。

`docker-compose.yml` 里：

- `api` 连接 `redis://redis:6379/0`
- `worker` 也连接 `redis://redis:6379/0`
- `api` 和 `worker` 不是包含关系
- 它们只是都依赖同一个 Redis 服务

---

## 6. 先看这条主链路，不要一上来全项目乱翻

如果你第一次读这个项目，我建议你只盯住这条链路：

```text
前端/调用方
  -> POST /api/v1/documents
  -> DocumentService.create_document()
  -> dispatch_ingest_job()
  -> Redis broker
  -> Celery worker 消费 ingest.run_job
  -> DocumentService.run_ingest_job()
  -> DocumentIngestionService.ingest_document()
  -> parse -> chunk -> embedding -> qdrant upsert
  -> job status = completed
  -> document status = active
```

把这条链路吃透之后，再去看 retrieval/chat，就不会迷路。

---

## 7. 代码执行顺序，按真实调用链展开

下面按“真实执行顺序”讲，不按文件目录顺序讲。

### 第 1 步：FastAPI 应用启动

先看：

- `backend/app/main.py`

这个文件做的事情很基础：

1. 创建 FastAPI app
2. 注册 CORS
3. 挂总路由
4. 启动时创建 `data/` 目录

它不包含业务逻辑，但它告诉你项目入口在哪里。

继续顺着路由往下看：

- `backend/app/api/router.py`
- `backend/app/api/v1/router.py`

你会看到 `/api/v1/documents` 这个入口最终挂到了 `documents.py`。

### 第 2 步：进入上传异步接口

看：

- `backend/app/api/v1/endpoints/documents.py`

这里最重要的是这个接口：

- `POST /documents`

它对应的函数会调用：

- `document_service.create_document(...)`

这个文件本身很薄，主要是把 HTTP 参数交给 service 层。

这说明真正的业务核心不在 endpoint，而在 service。

### 第 3 步：创建 document 和 ingest job

看：

- `backend/app/services/document_service.py`

先看函数：

- `create_document()`

这是整条异步链路的第一个核心函数。

它做的事情按顺序是：

1. 读取并校验上传文件
2. 清洗表单字段
3. 计算文件哈希，做去重判断
4. 生成 `doc_id`
5. 生成 `job_id`
6. 把原始文件落盘到 `data/uploads/`
7. 创建 `DocumentRecord`
8. 创建 `IngestJobRecord`
9. 持久化 document/job 元数据
10. 调用 `_dispatch_job_or_fail()` 投递 Celery 任务
11. 立刻返回 `queued`

这里有两个要点必须记住：

第一，这个接口不会同步做 parse/chunk/embed/upsert。

第二，它在返回前只做两类事：

- 把“将来要做的任务”记录下来
- 把任务丢进 Celery

所以接口返回 `queued` 是合理的，不是没做完，而是故意异步化。

### 第 4 步：投递 Celery 任务

还在 `document_service.py` 里，看：

- `_dispatch_job_or_fail()`

这个函数会调用：

- `dispatch_ingest_job(job_record.job_id, self.settings)`

然后跳到：

- `backend/app/worker/celery_app.py`

再看：

- `dispatch_ingest_job()`

这个函数做的事情是：

1. 取到当前配置对应的 Celery app
2. 找到已经注册好的任务名 `ingest.run_job`
3. 调用 `apply_async()`
4. 指定目标队列 `ingest`

这一步本质上就是：

- 把一个参数为 `job_id` 的任务，投递给 Celery

到这里为止，API 进程的核心工作就结束了。

### 第 5 步：Redis 接住任务

这一步代码里不一定有你期望的“显式函数调用”，因为这是 Celery 和 Redis 的协作过程。

你要这样理解：

1. `apply_async()` 把任务消息写入 Redis broker
2. worker 进程一直在监听 `ingest` 队列
3. worker 从 Redis 拿到任务后开始执行

所以 Redis 在这里像一个中转站。

API 并不是直接调用 worker 的 Python 函数，而是通过 Redis 把任务交出去。

### 第 6 步：worker 消费任务

继续看：

- `backend/app/worker/celery_app.py`

这里最重要的是被注册的任务：

- `ingest.run_job`

这个任务函数内部做的事情是：

1. 创建 `DocumentService(settings)`
2. 调用 `service.run_ingest_job(job_id)`
3. 根据结果判断是否需要 `self.retry(...)`

也就是说，真正的 worker 入口不是另写一套业务，而是复用了 `DocumentService`。

这是个很重要的设计点。

它表示项目把“业务逻辑”尽量放在 service 层，而不是散落在 endpoint 和 worker 各写一套。

### 第 7 步：run_ingest_job 开始真正执行入库

再回到：

- `backend/app/services/document_service.py`

看：

- `run_ingest_job()`

这个函数是异步入库链路的第二个核心函数。

它做的事情按顺序是：

1. 加载 job_record
2. 加载 document_record
3. 如果任务已完成或正在处理中，直接返回
4. 把 document 状态改成 `uploaded`
5. 把 job 状态改成 `parsing`
6. 定义阶段回调 `on_stage(stage, progress)`
7. 调用 `self.ingestion_service.ingest_document(...)`
8. 成功则把 job 改成 `completed`
9. 把 document 改成 `active`
10. 失败则进入 `_mark_ingest_failure()`

你可以把它理解成：

- `create_document()` 负责“建任务 + 发任务”
- `run_ingest_job()` 负责“真正干活 + 写状态”

### 第 8 步：真正的 parse / chunk / embedding / indexing

继续看：

- `backend/app/services/ingestion_service.py`

重点函数：

- `ingest_document()`

这是纯入库执行逻辑，不关心 HTTP，也不关心 Celery。

它做的事情按顺序是：

1. `parsing`
2. `chunking`
3. `embedding`
4. `indexing`

具体对应：

1. `DocumentParser.parse()`
2. `TextChunker.split()`
3. `EmbeddingClient.embed_texts()`
4. `QdrantVectorStore.upsert_document()`

中间会落一些调试和追溯文件：

- 解析结果写到 `data/parsed/{document_id}.txt`
- chunk 结果写到 `data/chunks/{document_id}.json`

这一步完成后，向量已经真正进了 Qdrant。

### 第 9 步：状态推进到 completed

如果 `ingest_document()` 没有抛异常：

- job 状态会被更新为 `completed`
- document 状态会被更新为 `active`

这说明文档已经可检索。

如果抛了异常：

- 进入 `_mark_ingest_failure()`
- 根据 `retry_count` 和 `ingest_failure_retry_limit` 判定是 `failed` 还是 `dead_letter`

状态机定义在：

- `backend/INGEST_STATE_MACHINE.md`

---

## 8. 为什么有 `DocumentRecord` 和 `IngestJobRecord`

这是这个项目很关键的一层“业务真相记录”。

看：

- `backend/app/schemas/document.py`

这里定义了两个核心持久化对象：

- `DocumentRecord`
- `IngestJobRecord`

你可以把它们理解成两张逻辑表。

它们分工不同：

- `DocumentRecord`
  记录文档本身的状态、归属、文件路径、最新 job
- `IngestJobRecord`
  记录这一次入库任务的状态、阶段、进度、重试次数、错误码

为什么要分开？

因为“文档”和“某次入库任务”不是同一件事。

一份文档将来可能有多次重跑、重新入队、失败重试。如果不把 job 独立出来，状态会混乱。

---

## 9. document 状态和 job 状态不要混着看

第一次看这套代码最容易混淆的，就是 document status 和 ingest job status。

你要强制区分这两个层级。

### document status

这是“文档整体生命周期状态”。

当前常见值：

- `queued`
- `uploaded`
- `active`
- `failed`

你可以理解成“这份文档当前总体处于什么可用状态”。

### ingest job status

这是“某一次入库任务执行到了哪一步”。

当前常见值：

- `queued`
- `parsing`
- `chunking`
- `embedding`
- `indexing`
- `completed`
- `failed`
- `dead_letter`

你可以理解成“这次后台任务具体跑到哪了”。

简单说：

- document status 更像业务层视角
- job status 更像任务执行视角

---

## 10. 元数据到底存哪里

这个项目的一个关键点是：文档和 job 元数据的存储有两种模式。

### 模式 1：默认本地 JSON

默认情况下：

- `DocumentRecord` 存在 `data/documents/*.json`
- `IngestJobRecord` 存在 `data/jobs/*.json`

这也是为什么你本地调试时很容易直接看到状态文件。

### 模式 2：PostgreSQL

如果打开：

- `RAG_POSTGRES_METADATA_ENABLED=true`

那元数据会走：

- `backend/app/db/postgres_metadata_store.py`

也就是说：

- 文档和 job 的元数据真源可以切换成 PostgreSQL
- 但 Celery + Redis 这套异步机制并没有消失

这一点要特别注意。

PostgreSQL 是 document/job metadata store。
Redis 是 Celery broker/result backend。

它们不是互相替代关系。

---

## 11. 为什么 API 要先返回 `queued`

因为这是异步接口的设计目标。

`POST /api/v1/documents` 的职责不是“立刻把文档处理完”，而是：

1. 确保文档和任务记录被创建
2. 确保任务被成功投递到队列
3. 给调用方一个可追踪的 `job_id`

之后调用方应该轮询：

- `GET /api/v1/ingest/jobs/{job_id}`

这也是为什么运行手册里一直强调：

1. 先上传文档
2. 拿到 `job_id`
3. 再轮询任务状态

如果你把这个接口当成同步接口去看，就会一直觉得“为什么它只返回 queued，不直接处理完”。其实这是刻意设计的。

---

## 12. 为什么任务会一直停在 `queued`

这个现象其实文档里已经写得很直白了。

看：

- `backend/WORKER_RUNBOOK.md`

任务一直停在 `queued`，通常说明：

1. worker 没起来
2. Redis 地址不对
3. worker 监听的队列名不对
4. Redis 不可达

这也反过来证明了一个事实：

- `queued` 只是“任务已经创建并准备等待消费”
- 它不等于“任务已经开始执行”

从架构上说，这很正常。

---

## 13. Celery 的重试是怎么工作的

看：

- `backend/app/worker/celery_app.py`
- `backend/app/services/document_service.py`
- `backend/INGEST_STATE_MACHINE.md`

这个项目的重试分两层理解。

### 第一层：执行失败后的业务状态

在 `run_ingest_job()` 里，如果解析、embedding、Qdrant 写入出错，会进入：

- `_mark_ingest_failure()`

它会做这些事：

1. `retry_count + 1`
2. 判断是否达到 `ingest_failure_retry_limit`
3. 未到上限则标 `failed`
4. 到上限则标 `dead_letter`
5. 文档状态同步标为 `failed`

### 第二层：Celery 的自动 retry

在 `celery_app.py` 里，worker 任务执行后，如果结果是 `failed` 且还没到上限，会执行：

- `self.retry(...)`

也就是说：

- 业务层先决定“这次算失败”
- Celery 层再决定“要不要重新入队再试一次”

这套分层是合理的，因为：

- 业务层最懂业务状态和错误码
- Celery 层最懂队列重试机制

---

## 14. 同步接口 `/documents/upload` 和异步接口 `/documents` 的区别

这两个接口名字很像，但一定不要混。

### `/api/v1/documents/upload`

这是同步链路。

它会直接调用：

- `DocumentService.save_upload()`
- `DocumentIngestionService.ingest_document()`

也就是当前请求线程里直接做完解析、切块、embedding、Qdrant upsert。

所以它返回的是：

- `DocumentUploadResponse`
- 状态是 `ingested`

### `/api/v1/documents`

这是异步链路。

它只会：

1. 创建 document/job 元数据
2. 投递 Celery
3. 返回 `queued`

所以如果你要看 Redis/Celery 这套机制，只看 `/documents`，不要看 `/documents/upload`。

---

## 15. 第一次读代码，推荐顺序

不要按目录从上到下扫。那样效率很低，而且会被一堆细节淹没。

建议严格按下面顺序读。

### 第一轮：只建立全局图

顺序：

1. `CURRENT_RAG_DATA_FLOW.md`
2. `LOCAL_DEV_RUNBOOK.md`
3. `backend/WORKER_RUNBOOK.md`
4. `docker-compose.yml`

这一轮不要钻实现，目标只有一个：

- 知道系统里有哪些进程、依赖、端口、入口

### 第二轮：只看异步上传入口

顺序：

1. `backend/app/main.py`
2. `backend/app/api/router.py`
3. `backend/app/api/v1/router.py`
4. `backend/app/api/v1/endpoints/documents.py`
5. `backend/app/api/v1/endpoints/ingest.py`

这一轮目标：

- 知道 HTTP 请求是怎么进来的
- 知道查询 job 状态的接口在哪

### 第三轮：只看任务创建和状态流转

顺序：

1. `backend/app/schemas/document.py`
2. `backend/app/services/document_service.py`
3. `backend/INGEST_STATE_MACHINE.md`

这一轮目标：

- 搞清楚 `DocumentRecord`
- 搞清楚 `IngestJobRecord`
- 搞清楚 `queued / failed / dead_letter / completed`

### 第四轮：只看 Celery 和 Redis

顺序：

1. `backend/app/core/config.py`
2. `backend/app/worker/celery_app.py`
3. `docker-compose.yml`

这一轮目标：

- 看懂 Redis URL 配置
- 看懂 `broker_url` 和 `result_backend`
- 看懂 worker 为什么是独立进程

### 第五轮：只看真正入库执行

顺序：

1. `backend/app/services/ingestion_service.py`
2. `backend/app/rag/parsers/document_parser.py`
3. `backend/app/rag/chunkers/text_chunker.py`
4. `backend/app/rag/embeddings/client.py`
5. `backend/app/rag/vectorstores/qdrant_store.py`

这一轮目标：

- 看懂 parse / chunk / embed / upsert 的真实执行路径

### 第六轮：最后用测试反推行为

顺序：

1. `backend/tests/test_document_ingestion.py`

这是非常有价值的一轮，因为测试把你最关心的行为都冻结住了：

- 创建文档后返回 `queued`
- job 状态如何变化
- 非 eager 场景如何模拟 worker 消费
- dispatch 失败为什么返回 502
- 重试和 `dead_letter` 语义是什么

如果你前 5 轮读完再来看这个测试文件，很多实现会一下子变得非常清楚。

---

## 16. 如果你只想最短时间看懂，盯住 7 个函数

如果时间不够，就先只看这 7 个函数。

1. `backend/app/services/document_service.py` 里的 `create_document()`
2. `backend/app/services/document_service.py` 里的 `_dispatch_job_or_fail()`
3. `backend/app/worker/celery_app.py` 里的 `dispatch_ingest_job()`
4. `backend/app/worker/celery_app.py` 里注册的 `run_ingest_job_task`
5. `backend/app/services/document_service.py` 里的 `run_ingest_job()`
6. `backend/app/services/ingestion_service.py` 里的 `ingest_document()`
7. `backend/app/services/document_service.py` 里的 `_mark_ingest_failure()`

把这 7 个函数串起来，你对这条链路的理解就已经超过大多数“只看表面配置”的阅读方式了。

---

## 17. 你读代码时最容易掉进去的坑

### 坑 1：把 Redis 当成 Celery

不对。

- Redis 是存任务消息和结果的基础设施
- Celery 是任务框架

### 坑 2：把 worker 当成 API 的一部分

不对。

worker 是独立进程。

### 坑 3：把 document status 和 job status 混为一谈

不对。

一个是文档视角，一个是任务视角。

### 坑 4：把 `/documents/upload` 和 `/documents` 当成一个接口

不对。

一个同步，一个异步。

### 坑 5：看到 `redis://.../0` 和 `redis://.../1` 以为是两个端口

不对。

这是同一个 Redis 端口上的两个逻辑数据库。

### 坑 6：看到 `queued` 以为任务已经开始跑

不对。

`queued` 只表示“已入队，等待 worker 消费”。

---

## 18. 调试这条链路时，应该看什么

如果你要实操调试，建议按这个顺序查。

### 第 1 步：确认 Redis 和 worker 真在跑

看：

- `LOCAL_DEV_RUNBOOK.md`
- `backend/WORKER_RUNBOOK.md`

当前默认基线下，核心命令是：

```bash
docker compose up -d
conda run -n rag_backend uvicorn backend.app.main:app --host 0.0.0.0 --port 8020
conda run -n rag_backend celery -A backend.app.worker.celery_app:celery_app worker --loglevel=info -Q ingest
```

### 第 2 步：先打健康检查

```bash
curl http://127.0.0.1:8020/api/v1/health
```

你需要特别确认返回里的：

- `queue.provider`
- `queue.broker_url`
- `queue.result_backend`

### 第 3 步：发一次异步上传

调用：

- `POST /api/v1/documents`

预期：

- 立刻拿到 `doc_id`
- 立刻拿到 `job_id`
- 状态是 `queued`

### 第 4 步：轮询 job 状态

调用：

- `GET /api/v1/ingest/jobs/{job_id}`

预期状态流转：

```text
queued -> parsing -> chunking -> embedding -> indexing -> completed
```

### 第 5 步：如果一直卡在 queued

优先怀疑：

1. worker 没启动
2. worker 队列名不是 `ingest`
3. Redis 地址错了
4. Redis 根本没通

---

## 19. 用测试文件验证你的理解

如果你觉得“我好像看懂了，但又不确定”，最快的方法不是继续瞎翻代码，而是去看测试。

重点文件：

- `backend/tests/test_document_ingestion.py`

你可以重点看这些测试在表达什么：

- 创建文档接口为什么应该返回 `queued`
- 为什么 job 初始状态是 `queued`
- 为什么 detail 接口里 document status 也是 `queued`
- 为什么 dispatch 失败会直接返回 502
- 为什么非 eager worker 消费后状态会到 `completed`
- 为什么重跑接口会让 job 回到 `queued`

测试文件不是辅助材料，它其实是这个项目当前行为最明确的说明书之一。

---

## 20. 看到这里之后，你应该已经能回答的几个问题

如果你真的把上面的内容看顺了，现在你应该已经能自己回答下面这些问题：

1. 为什么这个项目要引入 Celery
2. 为什么 Celery 还要配一个 Redis
3. 为什么 worker 必须单独启动
4. 为什么 `POST /api/v1/documents` 只返回 `queued`
5. 为什么任务状态要单独提供 `/ingest/jobs/{job_id}`
6. 为什么 `failed` 和 `dead_letter` 要区分
7. 为什么 Redis URL 里有 `/0` 和 `/1`
8. 为什么这个项目既有本地 JSON 元数据，也能切到 PostgreSQL

如果这些你都能顺着代码讲出来，这条异步链路你就已经看懂了。

---

## 21. 最后的阅读建议

第一次看项目，最重要的不是“看完所有文件”，而是“建立稳定的调用图”。

对这个项目来说，最值得先建立的调用图就是这一条：

```text
main.py
  -> api/router.py
  -> api/v1/router.py
  -> endpoints/documents.py
  -> services/document_service.py:create_document
  -> worker/celery_app.py:dispatch_ingest_job
  -> Redis
  -> worker/celery_app.py:run_ingest_job_task
  -> services/document_service.py:run_ingest_job
  -> services/ingestion_service.py:ingest_document
  -> parser / chunker / embedding / qdrant
```

你以后只要迷路，就重新回到这条图。

不要一开始就试图同时理解：

- RAG 检索
- Chat
- PostgreSQL 迁移
- pgvector
- 前端面板
- 所有 runbook

先把异步入库主链路打穿，再扩展到别的模块。这个顺序是对的。

---

## 22. 相关文件清单

建议优先阅读的文件：

- `backend/app/main.py`
- `backend/app/api/router.py`
- `backend/app/api/v1/router.py`
- `backend/app/api/v1/endpoints/documents.py`
- `backend/app/api/v1/endpoints/ingest.py`
- `backend/app/core/config.py`
- `backend/app/services/document_service.py`
- `backend/app/services/ingestion_service.py`
- `backend/app/worker/celery_app.py`
- `backend/app/schemas/document.py`
- `backend/app/rag/parsers/document_parser.py`
- `backend/app/rag/chunkers/text_chunker.py`
- `backend/app/rag/embeddings/client.py`
- `backend/app/rag/vectorstores/qdrant_store.py`
- `backend/INGEST_STATE_MACHINE.md`
- `backend/WORKER_RUNBOOK.md`
- `LOCAL_DEV_RUNBOOK.md`
- `CURRENT_RAG_DATA_FLOW.md`
- `backend/tests/test_document_ingestion.py`
- `docker-compose.yml`

---

如果你接下来要继续深挖，最自然的下一步不是继续扩展文档，而是做两件事：

1. 对着这份文档，把 `create_document()` 到 `ingest_document()` 这条调用链在编辑器里手动跟一遍
2. 实际跑一次本地 worker，然后观察一个 job 从 `queued` 走到 `completed`

这样理解会从“能读懂文档”变成“能自己解释代码”。
