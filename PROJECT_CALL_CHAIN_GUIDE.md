# 项目调用链带读

这不是项目总结，也不是架构汇报。

它的目标只有一个：

带你从真实入口出发，一层一层看懂这个项目后端是怎么跑起来的。

说明：

- 这次我尝试用了 `filesystem` 和 `codegraph`
- `filesystem` 可用，源码和启动配置都能读到
- `codegraph` 现在已经可以正常建索引和查关系
- 但它当前更擅长“函数 / 类 / 调用关系”，不擅长“模块级赋值、router.include_router、装饰器语义”
- 所以这份文档现在是：
  “源码直读 + codegraph 已验证关系” 的混合版

---

## 补充：这次 codegraph 已经验证了哪些关系

先说清楚证据边界，不然后面你会分不清哪些是“我读源码得出的”，哪些是“图上已经跑通的”。

目前这份 guide 里，下面这些关系我已经用 `codegraph` 验证过：

1. API 入口

- `backend/app/main.py`
- `lifespan -> backend/app/core/config.py::ensure_data_directories`

2. Health 链

- `backend/app/services/health_service.py`
- `HealthService.get_snapshot -> HealthResponse`
- `HealthService.get_snapshot -> OCRClient.get_runtime_status`
- `HealthService.get_snapshot -> get_llm_base_url / get_llm_model / get_reranker_base_url / get_postgres_metadata_dsn`

3. Retrieval 链

- `backend/app/services/retrieval_service.py`
- `RetrievalService.search -> QueryProfileService.resolve`
- `RetrievalService.search -> EmbeddingClient.embed_texts`
- `RetrievalService.search -> DocumentService.is_document_readable`
- `RetrievalService.search -> DocumentService.get_document_readability_map`
- `RetrievalService.search -> RetrievalService._collect_candidates`
- `RetrievalService._collect_candidates -> RetrievalQueryRouter.resolve_branch_weights`
- `RetrievalService._collect_candidates -> RetrievalService._fuse_candidates`
- `RetrievalService._fuse_candidates -> RetrievalQueryRouter.fixed_branch_weights`

同时你也要记住它现在的边界：

- `app.include_router(api_router)` 这种模块级装配关系，还是直接看源码更准
- `router.include_router(...)` 这种路由注册，还是直接看 `router.py`
- `Depends(...)` 这种依赖注入，当前图里会有噪声，不能只靠图判断真实业务调用

所以你可以把 `codegraph` 理解成：

- 它适合帮你确认“这个函数下一步调了谁”
- 它不适合单独解释“整个 FastAPI 路由是怎么装起来的”

---

## 0. 先记住两个运行入口

这个项目不是只有一个进程。

你先记住两个入口：

1. API 进程入口

- 启动命令在 `docker-compose.yml`
- 真正启动的是：
  `uvicorn backend.app.main:app`
- 也就是说，后端 Web 服务入口是：
  `backend/app/main.py` 里的 `app`

2. Worker 进程入口

- 启动命令也在 `docker-compose.yml`
- 真正启动的是：
  `celery -A backend.app.worker.celery_app:celery_app worker ...`
- 也就是说，异步入库 worker 的入口是：
  `backend/app/worker/celery_app.py` 里的 `celery_app`

为什么先记这两个？

因为这个项目的主流程本来就分成两类：

- 在线请求：
  检索、问答、健康检查、配置页
- 异步任务：
  文档入库、切块、向量写入

如果你不先分清 API 进程和 worker 进程，后面会很容易把“谁在处理请求”和“谁在后台跑任务”搞混。

---

## 1. API 入口链

这一段只讲：

`请求是怎么进后端的`

### 第 1 层：`backend/app/main.py` -> `app`

这个文件是 API 入口。

它做的事很少，但很关键：

1. 调 `get_settings()`

- 文件：
  `backend/app/core/config.py`
- 作用：
  把 `.env` 和默认配置读进来

2. 定义 `lifespan()`

- 作用：
  应用启动时先跑 `ensure_data_directories(settings)`
- 人话：
  先把 `data/uploads`、`data/parsed`、`data/chunks` 这些目录建好

3. 创建 `FastAPI` 应用对象

- 代码是：
  `app = FastAPI(...)`
- 人话：
  真正把“Web 服务实例”创建出来

4. 加 CORS 中间件

- 作用：
  让前端页面能跨域调用后端

5. 挂总路由

- 代码是：
  `app.include_router(api_router)`

为什么这样设计？

因为入口层应该只负责“装配”。

它不应该直接写上传、检索、问答这些业务逻辑。
如果都写在入口文件里，后面会非常难维护。

它和上一层是什么关系？

- 上一层不是 Python 函数，而是启动命令：
  `uvicorn backend.app.main:app`
- 启动命令负责把这个模块加载进来
- 这个文件负责把 FastAPI 应用对象拼好

配置依赖：

- `app_name`
  用来显示应用标题
- `cors_origins`
  控制前端能不能调接口
- `api_v1_prefix`
  后面挂路由时会用到

如果这些配置没写会怎样？

- 不会直接起不来，因为 `Settings` 里有默认值
- 但默认值未必适合你的环境
- 最常见的问题是：
  前端能打开，但因为 CORS 或代理配置不对，请求打不过来

这里已经有一条被 `codegraph` 验证过的真实关系：

- `backend/app/main.py::lifespan`
- `-> backend/app/core/config.py::ensure_data_directories`

这条关系很值得记住，因为它说明：

- `main.py` 不只是“创建 app”
- 它在启动时还明确调用了配置层的目录初始化逻辑
- 所以后面你看到 `data/uploads`、`data/chunks` 这些目录时，要知道它们不是靠人工提前建的

### 第 2 层：`backend/app/api/router.py` -> `api_router`

上一层的 `main.py` 已经把总路由挂进来了。

这一层做什么？

- 它把所有业务接口统一挂到一个 API 前缀下面
- 代码核心只有一句：
  `api_router.include_router(v1_router, prefix=settings.api_v1_prefix)`

人话解释：

- 入口层不想知道每一个接口细节
- 它只想知道：
  “我把所有 v1 接口统一挂到 `/api/v1` 下面”

为什么这样设计？

因为版本管理要单独收口。

以后如果有 `v2`，最自然的做法就是：

- 新建另一套路由
- 继续挂到另一个前缀

它和上一层是什么关系？

- `main.py` 只知道 `api_router`
- `api_router` 再决定“业务接口到底挂到哪个版本前缀上”

配置依赖：

- `api_v1_prefix`

如果这个配置改了会怎样？

- 所有 API 路径都会跟着变
- 前端代理、接口请求路径、文档地址都要一起对齐

这里顺带记住一个 `codegraph` 的边界：

- 它现在能很好地追函数之间的 `Calls`
- 但 `api_router = APIRouter()`、`include_router(...)` 这种模块级装配关系，不会像函数调用那样被图工具完整表现出来

所以这一层我们还是以源码为准，不强行让 `codegraph` 解释它不擅长的东西。

### 第 3 层：`backend/app/api/v1/router.py` -> `router`

这一层才开始看到“业务分组”。

它做什么？

- 把 `health`、`auth`、`documents`、`ingest`、`retrieval`、`chat`、`ops` 这些接口模块全部注册进来

你可以把它理解成：

- 第 1 层：
  建应用
- 第 2 层：
  加版本前缀
- 第 3 层：
  按业务域分发

为什么这样设计？

因为这个项目的业务已经不少了：

- 健康检查
- 登录和权限
- 文档上传
- 异步入库
- 检索
- 问答
- SOP
- 运维汇总

如果这些都堆在一个 router 里，阅读成本会很高。

它和上一层是什么关系？

- `api/router.py` 把请求交给 `v1/router.py`
- `v1/router.py` 再把不同路径分发给不同业务模块

到这里你应该形成一个最基础的路径感：

`启动命令 -> main.py -> api/router.py -> api/v1/router.py`

这就是请求进入项目后的公共外层壳。

---

## 2. 先看一条最简单的业务链：Health

为什么先看 `health`？

因为它最薄，最适合建立“endpoint -> service -> schema”这套阅读习惯。

### 第 4 层：`backend/app/api/v1/endpoints/health.py` -> `health_check`

这个函数几乎不做业务。

它做什么？

- 接收 `GET /api/v1/health`
- 通过依赖注入拿到 `HealthService`
- 直接调用：
  `health_service.get_snapshot()`

为什么这样设计？

因为 endpoint 层应该薄。

它的职责主要是：

- 收请求
- 做依赖注入
- 调 service
- 返回响应模型

它和上一层是什么关系？

- 上一层 `v1/router.py` 负责把 `/health` 路径分到这个 endpoint 文件
- 这一层才真正接住 HTTP 请求

这里要提醒你一个 `codegraph` 当前的噪声点：

- 图里能看到 `health_check -> Depends`
- 但这是 FastAPI 依赖注入语法带出来的结果
- 真正重要的业务调用，还是源码最后一行：
  `return health_service.get_snapshot()`

### 第 5 层：`backend/app/services/health_service.py` -> `get_snapshot`

这才是 `health` 的业务实现层。

它做什么？

- 从 `settings` 里读取当前运行配置
- 组装出一个 `HealthResponse`
- 把这些运行时信息返回出去：
  `vector_store / llm / embedding / reranker / queue / metadata_store / ocr`

人话解释：

它不是去“做检索”或者“做问答”。
它只是把当前系统在用什么依赖、什么模型、什么存储拼成一个快照。

为什么这样设计？

因为运行态信息不适合散落在 endpoint 里拼。

如果以后还要给：

- ops 页
- 健康检查接口
- 调试工具

复用同一套状态，就应该放在 service 层统一组装。

它和上一层是什么关系？

- endpoint 不懂系统细节
- endpoint 只把事情交给 `HealthService`
- `HealthService` 才知道该去读哪些配置、拼哪些字段

这一层已经有几条 `codegraph` 跑通的真实关系：

- `HealthService.get_snapshot -> HealthResponse`
- `HealthService.get_snapshot -> OCRClient.get_runtime_status`
- `HealthService.get_snapshot -> get_llm_base_url`
- `HealthService.get_snapshot -> get_llm_model`
- `HealthService.get_snapshot -> get_reranker_base_url`
- `HealthService.get_snapshot -> get_postgres_metadata_dsn`

这些关系说明一件事：

- `get_snapshot()` 不是一个“简单读 settings”的薄函数
- 它已经把配置层、OCR 运行态、响应模型装配都串在一起了
- 所以 health 页和 ops 页能复用它，不是偶然，而是它本来就在做“运行态快照收口”

配置依赖：

- `qdrant_url`
- `qdrant_collection`
- `llm_provider`
- `llm_base_url`
- `llm_model`
- `embedding_provider`
- `embedding_base_url`
- `embedding_model`
- `reranker_provider`
- `reranker_model`
- `celery_broker_url`
- `postgres_metadata_enabled`
- `ocr_provider`

如果没配会怎样？

- 大部分字段会走默认值
- 所以 `/health` 还能返回
- 但返回的是“默认配置对应的状态”，不一定说明真实依赖能用

### 第 6 层：`backend/app/schemas/health.py` -> `HealthResponse`

这一层不是业务逻辑，是接口合同。

它做什么？

- 定义 `/health` 响应长什么样
- 把 `vector_store`、`llm`、`embedding`、`reranker` 这些结构固定下来

为什么这样设计？

因为前后端要靠稳定合同说话。

如果 service 想返回什么就返回什么：

- 前端类型会乱
- 测试会不好写
- 后面扩字段时容易破坏兼容

它和上一层是什么关系？

- `HealthService.get_snapshot()` 负责产出数据
- `HealthResponse` 负责约束这份数据的形状

到这里，你应该已经看懂一个最完整、最简单的调用链：

`/api/v1/health -> health endpoint -> HealthService.get_snapshot -> HealthResponse`

---

## 3. 再看项目最核心的业务链：Retrieval

这条链是理解整个项目的关键。

因为后面的 chat、SOP，本质上都要复用它。

### 第 7 层：`backend/app/api/v1/endpoints/retrieval.py` -> `search_documents`

这个 endpoint 做什么？

- 接收 `POST /api/v1/retrieval/search`
- 接收请求体 `RetrievalRequest`
- 通过依赖注入拿到：
  `AuthContext | None`
  `RetrievalService`
- 然后直接调用：
  `retrieval_service.search(...)`

为什么这样设计？

因为检索是有权限边界的。

所以 endpoint 在把请求交给 service 前，会顺手把：

- 当前用户上下文
- 请求参数

一起传下去。

它和上一层是什么关系？

- `v1/router.py` 把 `/retrieval/search` 路径分到这里
- 这里负责把 HTTP 层输入翻译成 service 层调用

这里也要提醒你一个 `codegraph` 当前的噪声点：

- 图里能看到 `search_documents -> Depends`
- 但这同样主要是 FastAPI 依赖注入语法带出来的结果，不是你真正想看的业务主调用

所以这个 endpoint 最重要的阅读点，还是源码最后一行：

- `return retrieval_service.search(request, auth_context=auth_context)`

也就是说，真正的检索业务入口还是下一层的 `RetrievalService.search()`

### 第 8 层：`backend/app/services/retrieval_service.py` -> `search`

这是检索真正的业务入口。

这个函数做什么？

1. 先解析查询档位
2. 校验 `document_id` 权限
3. 生成 query embedding
4. 调 vector store 做向量召回
5. 视策略决定是否补 lexical recall
6. 做 fusion
7. 再把结果整理成 `RetrievedChunk`

人话解释：

它就是“检索总控室”。

真正和检索有关的关键动作，都是在这里串起来的。

为什么这样设计？

因为这个项目不想让：

- endpoint 自己调 embedding
- chat 自己写一份检索
- SOP 再写一份检索

所以要有一个统一的检索服务入口。

它和上一层是什么关系？

- endpoint 只负责接请求
- `RetrievalService.search()` 才负责真正组织检索流程

这一层是目前 `codegraph` 最有价值的地方，因为主调用链已经能直接跑出来：

- `RetrievalService.search -> QueryProfileService.resolve`
- `RetrievalService.search -> EmbeddingClient.embed_texts`
- `RetrievalService.search -> DocumentService.is_document_readable`
- `RetrievalService.search -> DocumentService.get_document_readability_map`
- `RetrievalService.search -> RetrievalService._collect_candidates`

这几条关系能帮你建立一个正确顺序：

1. 先定查询档位
2. 再做权限预检查
3. 再生成 query embedding
4. 再收集候选
5. 最后才整理结果并做可读性过滤

这比只盯着一坨长函数更容易抓主线。

### 第 9 层：`backend/app/services/query_profile_service.py` -> `resolve`

`RetrievalService.search()` 里第一件重要的事，就是先调这个函数。

它做什么？

- 把 `mode=fast/accurate`
- 把 `top_k`
- 把 `candidate_top_k`
- 把 `lexical_top_k`
- 把 `rerank_top_n`
- 把 `timeout_budget`

这些参数统一收口成一个 `QueryProfile`

为什么这样设计？

因为这些参数如果散落在：

- retrieval
- chat
- SOP

三个服务里，各写一份，后面一定会打架。

所以这里的设计思路是：

- 先统一算出一份查询档位配置
- 后面所有链路都只消费这份配置

它和上一层是什么关系？

- `RetrievalService.search()` 不直接手写各种 magic number
- 它先让 `QueryProfileService` 把“本次检索该怎么跑”算出来

配置依赖：

- `query_fast_top_k_default`
- `query_fast_candidate_multiplier`
- `query_fast_lexical_top_k_default`
- `query_accurate_top_k_default`
- `query_accurate_candidate_multiplier`
- `query_accurate_lexical_top_k_default`

如果这些配置没写会怎样？

- 会走 `Settings` 默认值
- 系统仍然能跑
- 但你的 fast/accurate 行为就完全依赖默认基线

### 第 10 层：`backend/app/rag/embeddings/client.py` -> `embed_texts`

在拿到 `QueryProfile` 后，`RetrievalService.search()` 会把 query 先变成向量。

这个函数做什么？

- 根据 `embedding_provider` 决定怎么生成向量
- 支持：
  `mock / ollama / openai`
- 支持按 batch 分批发请求

为什么这样设计？

因为检索主链路不应该依赖某一家 embedding 服务的私有协议。

所以这里抽了一个 `EmbeddingClient`：

- retrieval 只管“我要向量”
- client 才管“怎么去拿这个向量”

它和上一层是什么关系？

- `RetrievalService.search()` 负责组织流程
- `EmbeddingClient.embed_texts()` 负责把 query 变成可检索的向量

配置依赖：

- `embedding_provider`
- `embedding_base_url`
- `embedding_model`
- `embedding_timeout_seconds`
- `embedding_batch_size`

如果没有可用 embedding 服务会怎样？

- `mock` 模式下还能跑，用伪向量
- 非 mock 模式下，如果远端不可达，会在这里抛错

### 第 11 层：`backend/app/rag/vectorstores/qdrant_store.py` -> `search`

query 有了向量之后，会进这一层。

它做什么？

- 调 Qdrant 的 `query_points`
- 按 query vector 做相似度检索
- 可选带 `document_id` 过滤
- 返回 `ScoredPoint`

为什么这样设计？

因为向量库操作应该单独封装。

不然 service 层会直接到处写：

- Qdrant client 初始化
- collection 判断
- filter 组装
- query_points 调用

这样会很乱。

它和上一层是什么关系？

- `EmbeddingClient` 负责把 query 变成向量
- `QdrantVectorStore.search()` 负责拿这个向量去库里找候选 chunk

配置依赖：

- `qdrant_url`
- `qdrant_collection`

如果 Qdrant 没起来会怎样？

- 如果 collection 不存在，会直接返回空结果
- 如果服务地址不可达，在更底层 client 调用时会报错

### 第 12 层：`backend/app/rag/retrievers/lexical_retriever.py` -> `QdrantLexicalRetriever.search`

这一层是 hybrid retrieval 的另一条支路。

它做什么？

- 顺序读取 Qdrant payload
- 把 query 和 chunk 文本做词法切分
- 算 BM25-like 分数
- 返回 lexical match

当前中文分词策略是什么？

- 主分词：
  `jieba_search`
- 补充分词：
  `2-gram`

为什么这样设计？

因为这个项目当前不想为了 V1 直接上独立搜索集群。

所以它选了一条更轻的路：

- 复用现有 chunk 文本
- 在当前数据上补一个 lexical recall

它和上一层是什么关系？

- `QdrantVectorStore.search()` 给你语义候选
- `QdrantLexicalRetriever.search()` 给你关键词候选
- 两边候选后面再统一融合

配置依赖：

- `retrieval_lexical_chinese_tokenizer`
- `retrieval_lexical_supplemental_bigram_weight`

如果没装 `jieba` 会怎样？

- 中文主分词会退化
- 代码会走 fallback token 路径
- 但系统不会因为这个直接起不来

### 第 13 层：`backend/app/services/retrieval_service.py` -> `_collect_candidates`

这一层是“把两条召回支路收口”的地方。

它做什么？

- 先把 vector 结果转成内部 candidate
- 看当前策略是不是 `hybrid`
- 如果是，就再跑 lexical recall
- 如果 lexical 分支报错或没结果，就回退 `qdrant`
- 如果有 lexical 结果，就进入 fusion

为什么这样设计？

因为 hybrid 不是强依赖。

系统的设计目标很明确：

- hybrid 能工作时，用 hybrid
- lexical 分支坏了，也不能把整个主流程拖死

它和上一层是什么关系？

- 上一层分别拿到了：
  vector candidate
  lexical candidate
- 这一层决定：
  “本次是继续 hybrid，还是退回 vector-only”

这一层现在也已经能用 `codegraph` 验证到关键关系：

- `RetrievalService._collect_candidates -> RetrievalQueryRouter.resolve_branch_weights`
- `RetrievalService._collect_candidates -> RetrievalService._fuse_candidates`

这两条关系非常重要，因为它们把当前 V1 的 hybrid 主线说清楚了：

- 不是 endpoint 决定怎么混
- 不是 lexical retriever 决定最终权重
- 而是 `_collect_candidates()` 先判断“本次 query 用什么分支策略”，再把候选交给融合层

### 第 14 层：`backend/app/services/retrieval_service.py` -> `_fuse_candidates`

这一层是 hybrid retrieval 最关键的一层。

它做什么？

- 按 rank 做 weighted RRF 融合
- 把 vector 候选和 lexical 候选合并成一个排序结果
- 支持 fixed fallback
- 支持规则式 dynamic weighting

现在的分支间融合逻辑是什么？

- 不是直接拼原始分数
- 而是：
  `vector_weight / (rrf_k + vector_rank)`
  `lexical_weight / (rrf_k + lexical_rank)`

为什么这样设计？

因为向量分数和 BM25 分数本来就不是同一量纲。

如果直接线性相加，很容易把系统调得很脆。

RRF 的好处是：

- 稳
- 可解释
- 适合多路召回融合

它和上一层是什么关系？

- `_collect_candidates()` 决定要不要融合
- `_fuse_candidates()` 负责真正把两路候选揉成一份最终结果

这里 `codegraph` 还验证到一条小但关键的 fallback 关系：

- `RetrievalService._fuse_candidates -> RetrievalQueryRouter.fixed_branch_weights`

这条关系能帮你理解“为什么 dynamic weighting 不会污染主流程”：

- 动态权重只是可选输入
- 一旦没传 branch weights，融合层会自己回退到 fixed baseline
- 也就是说，系统把“可扩展”和“可回退”都收在了融合层，不会把风险散到别的模块

配置依赖：

- `retrieval_strategy_default`
- `retrieval_hybrid_rrf_k`
- `retrieval_dynamic_weighting_enabled`
- `retrieval_hybrid_fixed_vector_weight`
- `retrieval_hybrid_fixed_lexical_weight`
- `retrieval_hybrid_exact_*`
- `retrieval_hybrid_semantic_*`
- `retrieval_hybrid_mixed_*`

如果 dynamic weighting 没开会怎样？

- 会走 fixed fallback
- 也就是保持当前稳定基线

到这里，retrieval 主链路就算完整闭环了：

`retrieval endpoint -> RetrievalService.search -> QueryProfileService.resolve -> EmbeddingClient.embed_texts -> QdrantVectorStore.search -> QdrantLexicalRetriever.search -> _collect_candidates -> _fuse_candidates`

---

## 4. Chat 链是怎么复用 Retrieval 的

这条链很重要，因为它说明这个项目不是“检索一套、问答再写一套”。

### 第 15 层：`backend/app/api/v1/endpoints/chat.py` -> `ask_question`

这一层和 retrieval endpoint 很像。

它做什么？

- 接收 `POST /api/v1/chat/ask`
- 通过依赖注入拿到 `ChatService`
- 直接调用：
  `chat_service.answer(...)`

为什么这样设计？

- endpoint 保持薄
- 复杂逻辑放 service

它和上一层是什么关系？

- `v1/router.py` 把 `/chat/ask` 路径分到这里
- 这里把 HTTP 请求交给 `ChatService`

### 第 16 层：`backend/app/services/chat_service.py` -> `answer`

这个函数是问答链的总控室。

它做什么？

- 先 resolve 查询档位
- 处理 runtime gate
- 调 `_build_citations()` 去拿证据
- 调 `generation_client.generate()` 去生成答案
- 记录 event log / trace / snapshot

为什么这样设计？

因为 chat 不是“直接调 LLM”。

这个项目的问答是完整 RAG 流程：

- 先找证据
- 再重排
- 再生成
- 再记录可追踪信息

它和上一层是什么关系？

- endpoint 只把请求交给它
- 它才真正负责把 retrieval、rerank、generation 串起来

### 第 17 层：`backend/app/services/chat_service.py` -> `_build_citations`

这是 chat 和 retrieval 接上的关键点。

它做什么？

1. 调 `RetrievalService.search()`
2. 拿到检索结果
3. 调 `QueryProfileService.rerank_with_fallback()`
4. 把结果转成 `Citation`

为什么这样设计？

因为 chat 需要的不是“裸 chunk”，而是“可直接回给前端的引用结构”。

所以这里做了一层转换：

- retrieval 返回的是 `RetrievedChunk`
- chat 最后需要的是 `Citation`

它和上一层是什么关系？

- `ChatService.answer()` 负责总流程
- `_build_citations()` 负责其中的“证据构建”这一步

### 第 18 层：`backend/app/services/query_profile_service.py` -> `rerank_with_fallback`

这一层是 chat 里“重排”的统一入口。

它做什么？

- 先调用 `RerankerClient.rerank()`
- 如果 provider 出错，而且允许降级
- 就退回 `rerank_heuristic()`

为什么这样设计？

因为 rerank 服务本身也是在线依赖。

如果它挂了，系统不应该立刻完全不可用。

所以这里的设计思路是：

- provider 能用就走模型级 rerank
- 不能用就退回 heuristic

它和上一层是什么关系？

- `_build_citations()` 拿到了 retrieval 结果
- `rerank_with_fallback()` 决定这些候选证据如何重排

### 第 19 层：`backend/app/rag/rerankers/client.py` -> `RerankerClient.rerank`

这一层是真正执行 rerank 的客户端。

它做什么？

- 根据 `reranker_provider` 决定走：
  `heuristic`
  或 `openai-compatible`

为什么这样设计？

因为 service 层不想知道不同 provider 的协议差异。

所以和 embedding client 一样，这里也做了 provider 抽象。

它和上一层是什么关系？

- `QueryProfileService.rerank_with_fallback()` 决定“要不要降级”
- `RerankerClient.rerank()` 负责真正发请求或做启发式排序

### 第 20 层：`backend/app/rag/generators/client.py` -> `LLMGenerationClient.generate`

这就是问答链最后的生成层。

它做什么？

- 根据 `llm_provider` 走：
  `mock / ollama / openai / deepseek`
- 把 question + contexts 组织成 prompt
- 调远端 LLM 生成回答

为什么这样设计？

因为 chat service 不应该直接关心：

- URL 怎么拼
- headers 怎么带
- 超时怎么处理
- 什么错误能降级

这些都应该在 client 层收口。

它和上一层是什么关系？

- `ChatService.answer()` 负责整体编排
- `LLMGenerationClient.generate()` 负责真正拿答案

到这里，chat 主链路就闭环了：

`chat endpoint -> ChatService.answer -> _build_citations -> RetrievalService.search -> rerank_with_fallback -> RerankerClient.rerank -> LLMGenerationClient.generate`

---

## 5. Worker 链为什么是另一条入口

这个项目不是所有逻辑都走在线请求。

文档入库是后台异步任务。

### 第 21 层：`backend/app/worker/celery_app.py` -> `celery_app`

这是 worker 入口。

它做什么？

- 创建 Celery app
- 注册 ingest 任务
- 导出默认 `celery_app`

为什么这样设计？

因为 worker 进程和 API 进程不是同一个运行模型。

API 是：

- 收 HTTP 请求

Worker 是：

- 消费消息队列任务

它和上一层是什么关系？

- 启动命令 `celery -A backend.app.worker.celery_app:celery_app worker`
- 会直接加载这个文件里的 `celery_app`

配置依赖：

- `celery_broker_url`
- `celery_result_backend`
- `celery_ingest_queue`

如果这些配置不对会怎样？

- worker 进程可能能起来
- 但连不上 broker
- 或者收不到 ingest 队列里的任务

### 第 22 层：`backend/app/worker/celery_app.py` -> `_register_tasks` / `run_ingest_job_task`

这一步才真正把任务注册进 Celery。

它做什么？

- 注册一个统一任务名：
  `ingest.run_job`
- worker 收到这个任务时，会创建 `DocumentService`
- 然后调用：
  `service.run_ingest_job(job_id)`

为什么这样设计？

因为 Celery 本身只负责调度任务，不懂你的业务。

所以你要显式告诉它：

- 这个任务名对应哪段业务逻辑

它和上一层是什么关系？

- `celery_app` 是 worker 运行容器
- `run_ingest_job_task` 是容器里真正执行的业务任务

### 第 23 层：`backend/app/services/document_service.py` -> `run_ingest_job`

这一层就是异步入库真正的业务入口。

它做什么？

- 按 `job_id` 读取任务状态
- 更新 ingest 阶段
- 跑文档解析、切块、embedding、索引写入
- 最后更新 document 和 job 状态

为什么这样设计？

因为“文档入库”本身是一个长流程，而且会改很多状态：

- 文档状态
- job 状态
- 本地文件
- 向量库

这种流程最适合单独放在 service 层收口。

它和上一层是什么关系？

- Celery task 只是任务壳
- `DocumentService.run_ingest_job()` 才是真正的入库执行器

---

## 6. 配置层为什么你一定要一起看

如果你想真正看懂这个项目，`backend/app/core/config.py` 不能跳过。

最关键的原因是：

这个项目很多行为不是硬编码的，而是配置驱动的。

你至少要认识这几组配置：

1. API 外壳

- `app_name`
- `api_v1_prefix`
- `cors_origins`

2. 检索

- `qdrant_url`
- `qdrant_collection`
- `retrieval_strategy_default`
- `retrieval_hybrid_rrf_k`

3. embedding / rerank / llm

- `embedding_provider`
- `embedding_model`
- `reranker_provider`
- `reranker_model`
- `llm_provider`
- `llm_model`

4. 查询档位

- `query_fast_*`
- `query_accurate_*`

5. worker

- `celery_broker_url`
- `celery_result_backend`
- `celery_ingest_queue`

6. OCR

- `ocr_provider`
- `ocr_language`
- `ocr_pdf_native_text_min_chars`

7. dynamic weighting

- `retrieval_dynamic_weighting_enabled`
- `retrieval_hybrid_fixed_*`
- `retrieval_hybrid_exact_*`
- `retrieval_hybrid_semantic_*`
- `retrieval_hybrid_mixed_*`

如果 `.env` 里没配会怎样？

- `Settings` 会先用默认值
- 所以项目不一定直接起不来
- 但很多依赖可能会指向“本地默认地址”
- 最后表现出来就是：
  服务在跑，但功能不可用

这也是为什么你调项目时，不能只看代码，还要一起看配置。

---

## 7. 推荐你接下来怎么读

如果你现在要继续往下真正读代码，我建议顺序是：

1. 先把 API 外层三层读熟

- `main.py`
- `api/router.py`
- `api/v1/router.py`

2. 再把 retrieval 主链读熟

- 这是整个项目最核心的公共能力

3. 再看 chat

- 因为 chat 是在 retrieval 上加 rerank 和 generation

4. 最后再看 worker 和 document ingest

- 因为它是另一条运行入口

如果你只想先搞懂一个最重要的问题，那就先吃透这条链：

`RetrievalService.search()`

因为它是：

- 检索页的核心
- 问答链的证据入口
- SOP 链的证据入口

这条线一旦看懂，你对整个项目的把握会一下子上来。
