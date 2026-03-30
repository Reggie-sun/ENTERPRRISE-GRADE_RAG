# V1 Plan

## 0. 编写依据

本版计划基于以下两类输入：

- 需求文档：
  [宁波伟立机器人 企业级RAG智能知识库系统 需求规格说明书（V1.0 精简版）](/home/reggie/文档/xwechat_files/wxid_ut5o9e1igztd22_f3a1/msg/file/2026-03/宁波伟立机器人 企业级RAG智能知识库系统 需求规格说明书（V1.0 精简版）.docx)
- 当前代码现实：
  已具备文档异步入库、检索、问答、引用返回、前端基础联调链路

这份 `V1_PLAN` 不再把需求文档里的全部能力当成一个版本硬塞进去，而是把它拆成基于现有代码、可以逐步落地的小版本路线。

---

## 1. 为什么不能直接做“大而全 V1”

需求文档定义的是产品目标，但当前代码更接近以下形态：

- 一个已经跑通的 RAG 主链路
- 一部分前端联调页面
- 一套正在收口的本地 / 服务器协同开发基线

如果直接一次性做完整 V1，会把这些模块耦在一起：

- 登录与 RBAC
- 部门 / 分类主数据
- 文档管理后台
- SOP 查看、下载、生成、版本管理
- 日志与审计
- 企业微信入口

这样做的结果通常不是更快，而是：

- schema 反复变
- 接口反复变
- 前后端互相阻塞
- 已经跑通的入库 / 检索 / 问答链路被持续打断

所以这版计划的核心原则是：

**总目标按需求文档对齐，实施路径按小版本拆解，优先保证低耦合和可连续交付。**

---

## 2. 当前冻结边界

以下内容在这一轮计划中视为固定底座，不主动推翻：

- 当前在线检索底座继续沿用：
  `query -> embedding -> Qdrant vector recall + lexical recall -> weighted RRF fusion -> results`
- 当前 Embedding / Rerank / LLM 接入方式继续沿用
- 当前异步入库主链路继续沿用：
  `上传 -> document/job -> worker -> 向量入库 -> 检索 / 问答`
- 当前本地开发与服务器协同的运行基线继续沿用
- 当前已具备轻量关键词 / BM25 / RRF 混合检索，不再把这块当成空白能力

这意味着：

- 本轮先做产品能力，不先做基础设施重构
- 文档里可以保留需求文档的目标表述，但实现计划不能倒逼切库、切模型、重写部署
- 模型级 `rerank` 暂时不阻塞 `v0.4.0`，先用当前 `heuristic rerank` 跑通首轮业务试点
- OCR 图片处理不纳入当前冻结底座，但必须在 `v0.5.0` SOP 直生前补上最小可用版，否则扫描件和图片资料无法进入主链路

补充说明：

- 当前代码里仍保留一部分 `Ollama` 兼容字段和旧 provider 口径，但 V1 规划不再继续扩展 `Ollama`
- V1 的生成服务主路径统一收敛为：
  `vLLM(OpenAI-compatible)` 
- 同时预留统一的外部 LLM API provider 边界，便于后续接公司外部模型服务、云 API 或高峰期兜底
- 业务层不直接依赖某一家 provider 的特有字段，问答、SOP、日志、配置统一只依赖内部 LLM provider 抽象
- 当前 retrieval 主链路已经是轻量 hybrid retrieval，不要再把它误写成“纯向量召回”
- 当前代码里已有 lexical retriever + BM25-like 关键词召回 + RRF 融合；`heuristic rerank` 仍只是后置重排信号
- 后续在线检索质量增强的重点不再是“补第一版 hybrid retrieval”，而是验证、治理、配置收口与更复杂策略是否必要
- 当前代码已经有 `rerank` 插槽，但 provider 仍是 `heuristic`
- 模型级 `rerank` 不属于异步入库改造，而属于在线检索质量增强
- 更合适的接入时机是：
  `v0.4.0` 业务试点之后，最迟在 `v0.5.0` SOP 智能生成扩展前落地
- 这样做的原因是：
  它不需要重跑文档入库，但会直接增加在线问答与生成链路的延迟、模型服务依赖和运维复杂度

---

## 3. 当前代码起点

当前代码已经具备这些基础：

- 文档上传
- 文档异步入库
- ingest job 状态流转
- worker 消费与失败重试
- 文档检索
- 问答生成
- citations 返回
- 前端基础上传 / 检索 / 问答联调
- 在线主检索当前是：
  `query -> embedding -> Qdrant vector recall + lexical recall -> weighted RRF fusion -> results`
- 问答和 SOP 上层链路当前再接：
  `retrieval -> heuristic rerank -> LLM`
- 当前已经具备轻量 lexical retriever、BM25-like 关键词召回、`vector_only` fallback，以及 `retrieval_strategy / vector_score / lexical_score / fused_score`
- 当前 hybrid fusion 已支持规则式 dynamic branch weighting，默认关闭，保留 fixed fallback
- 当前 `heuristic rerank` 里的 token overlap 仍只是重排信号，不是第一阶段关键词召回
- 但当前主链路还不支持扫描件 / 图片 OCR，也还没有正式的模型级 `rerank` 服务

所以接下来的计划，不应该从“零开始搭系统”写，而应该从“基于已跑通链路逐步扩功能”写。

---

## 4. 低耦合拆分原则

后续所有版本都按下面的边界拆：

### 4.1 认证权限单独收口

- 用户、部门、角色、授权关系是独立领域
- 不能把部门权限直接散落在问答、检索、SOP、前端页面里各写一份

### 4.2 文档主数据和检索副本分开

- 文档主数据单独管理
- 检索索引只保留检索和过滤需要的字段
- 文档删除、重建、分类调整不能直接和向量层强耦合

### 4.3 SOP 当成独立业务对象

- SOP 查看 / 下载先当“资产管理能力”实现
- SOP 智能生成后续再接进来
- 不要一开始就把 SOP 的查看、下载、生成、版本、入库、导出绑成一个大功能

### 4.4 企业微信是补充入口，不是主流程

- 企业微信只复用已有问答能力
- 不单独发展成另一套业务流程

### 4.5 日志和审计后补，但接口要预留

- 先保证主功能可用
- 管理日志和审计能力后补
- 但关键操作要提前预留事件点，避免后面大面积返工

---

## 5. 总体目标与拆分策略

需求文档里的总目标不变：

- 员工端：
  智能问答、文档检索、SOP 生成、SOP 查看下载、个人中心
- 管理后台：
  文档管理、分类管理、SOP 管理、权限管理、日志、系统配置
- 后端：
  认证鉴权、异步入库、RAG 问答、SOP 生成、日志审计、企业微信接入

但实现上不按一个版本做完，而是拆成下面这些连续小版本。

---

## 6. 版本路线图

### 6.1 `v0.1.2` 稳定现有 RAG 主链路

目标：

- 把当前已经跑通的链路稳定下来，形成可重复验证的开发基线

必须完成：

- 上传、异步入库、检索、问答四块联通
- 当前文档名称和 `doc_id` 在前端可见
- 检索和问答支持按当前文档过滤
- 失败状态、重试状态、错误提示可见
- 本地运行文档、端口、`.env`、Compose 口径统一

明确不做：

- 登录
- 部门权限
- SOP 管理
- 企业微信
- 大规模后台管理

验收标准：

- 能上传一个文档并完成异步入库
- 能检索到当前文档 chunk
- 能基于当前文档问答并返回引用
- 前端页面和运行文档可被别人复现

具体拆分：

后端：

- 收口上传、job 查询、手动重投递、检索、问答这几条现有接口的输入输出
- 固化 ingest 状态语义：
  `queued / parsing / chunking / embedding / indexing / completed / failed / dead_letter`
- 保证重复上传、旧路径修复、失败重试这几条已有逻辑稳定
- 给检索和问答接口补当前 `document_id` 过滤参数，并统一校验语义
- 收口健康检查和最小依赖检查接口，便于前端和部署排查

前端：

- 上传后展示当前文档名称、`doc_id`、`job_id`
- 轮询 job 状态并显示阶段、进度、失败信息
- 每次新上传文档后清空旧检索结果和旧问答结果
- 检索和问答默认绑定当前文档，避免历史测试数据串结果
- 对上传失败、检索失败、问答失败、后端不可达给出明确提示

数据与接口：

- 统一当前前端依赖的接口字段，避免页面层自己猜字段含义
- 明确 `document_id` 与 `doc_id` 的使用口径，不再混用
- 固化 `.env`、端口、前端代理地址、后端健康检查地址

测试与验收：

- 后端至少回归：
  文档上传、job 状态、手动重投递、检索、问答、`document_id` 过滤
- 前端至少通过：
  `npm run build`
- 提供一份最小 smoke test：
  上传 -> queued -> completed -> 检索 -> 问答

建议按 issue 拆分：

1. API 合同收口

- 收口上传、job 查询、检索、问答接口的字段命名
- 固化 `doc_id / job_id / status / stage / progress / error_message` 的响应口径
- 明确前端统一使用的字段，不再页面里临时兼容多种写法

2. 检索与问答的当前文档过滤

- 后端检索接口支持按当前文档过滤
- 后端问答接口支持按当前文档过滤
- 前端上传新文档后，把当前文档上下文写入检索和问答请求

3. 上传后状态展示

- 前端上传完成后展示当前文档名称、`doc_id`、`job_id`
- 轮询 job 状态，并把阶段、进度、失败原因显示出来
- `queued / parsing / embedding / completed / failed / dead_letter` 要能直观看到

4. 前端状态隔离

- 每次上传新文档时清空旧检索结果
- 每次上传新文档时清空旧问答记录
- 当前页面上的所有检索和问答都默认绑定当前文档

5. 错误提示收口

- 上传失败有单独提示
- 检索失败有单独提示
- 问答失败有单独提示
- 后端不可达、依赖未 ready、接口超时三类情况尽量区分

6. 健康检查与排障入口

- 后端保留统一健康检查接口
- 健康检查里至少能看到当前模型和依赖地址
- runbook 里写清楚“页面打不开 / worker 未启动 / 向量入库失败 / 检索为空”这几种最小排查步骤

7. 配置与运行文档收口

- 前端代理地址和后端端口统一
- `.env` 与 `.env.example` 字段口径统一
- `docker compose`、本地命令、前端启动方式写成统一说明

8. 回归测试补齐

- 后端回归：
  上传、job、手动重投递、检索、问答、当前文档过滤
- 前端至少保证：
  构建通过、页面可正常联调

9. 最终 smoke test

- 上传一个文档
- 等待 job 完成
- 检索返回当前文档 chunk
- 问答返回当前文档引用
- 整套流程由另一人按文档可复现

建议执行顺序：

1. 先做 `API 合同收口`
2. 再做 `当前文档过滤`
3. 再做 `状态展示` 和 `前端状态隔离`
4. 然后做 `错误提示` 和 `健康检查`
5. 最后做 `文档收口`、`回归测试`、`smoke test`

### 6.2 `v0.2.0` 文档主数据与管理最小闭环

目标：

- 先把“知识库内容怎么被管理”补起来，但不先上完整权限系统

必须完成：

- 文档主数据补字段：
  部门、二级分类、上传人、状态
- 文档列表页
- 文档预览
- 删除文档
- 重新构建向量
- 批量上传

明确不做：

- 完整 RBAC
- SOP 智能生成
- 个人中心

低耦合要求：

- 文档主数据变更通过独立服务处理
- 重建向量只复用现有 ingest 机制，不另起一套流程

验收标准：

- 管理员可看到文档列表
- 可按文档执行预览、删除、重建向量
- 批量上传不会破坏现有异步主链路

具体拆分：

后端：

- 给文档主数据补齐字段：
  `department_id`、`category_id`、`uploaded_by`、`status`
- 补文档列表查询接口，支持分页、按部门筛选、按分类筛选、按状态筛选
- 补文档删除接口，约束为“先改主数据状态，再删检索副本”
- 补重建向量接口，内部复用现有 ingest job 投递机制
- 补批量上传接口或批量上传任务封装，保持单文档仍走原有 job 机制

前端：

- 增加文档列表页
- 增加筛选项：
  部门、分类、状态、关键字
- 增加文档操作按钮：
  预览、删除、重建向量
- 增加批量上传入口和上传结果反馈

数据与接口：

- 先冻结“部门”和“二级分类”的主数据结构，即使后台页面先做简化版也要先定字段
- 明确文档状态和 ingest 状态不是同一个字段，避免前端混用
- 删除文档和重建向量统一通过后端服务层处理，不允许前端自己拼流程

测试与验收：

- 回归现有单文档上传链路不受影响
- 新增测试覆盖：
  文档列表、删除、重建向量、批量上传
- 至少人工验证一轮：
  批量上传 3-5 个文档后，列表、预览、删除、重建向量都能工作

建议按 issue 拆分：

1. 文档主数据扩展

- 给文档主数据补 `department_id / category_id / uploaded_by / status`
- 兼容旧文档数据的默认值和迁移策略
- 明确文档状态与 ingest 状态的关系，不混为一个字段

2. 文档列表接口与筛选

- 增加文档列表接口
- 支持分页、关键字、部门、分类、状态筛选
- 返回前端需要的最小展示字段

3. 文档列表页

- 增加文档表格页
- 展示名称、部门、分类、上传人、状态、更新时间
- 支持筛选和刷新

4. 文档预览

- 增加文档预览接口或预览入口
- 前端支持点击列表项进入预览
- 先保证文本和基础 PDF 预览可用，不先做复杂 Office 预览

5. 删除文档

- 后端删除逻辑统一走服务层
- 删除顺序固定为：
  改主数据状态 -> 清理检索副本 -> 返回结果
- 前端加删除确认和删除结果反馈

6. 重建向量

- 新增重建向量接口
- 内部统一复用现有 ingest job 机制
- 前端增加“重建向量”操作按钮和状态提示

7. 批量上传

- 支持多文件上传
- 每个文件仍走独立 job
- 前端展示每个文件的上传和入库结果

8. 回归测试

- 覆盖文档列表
- 覆盖删除
- 覆盖重建向量
- 覆盖批量上传
- 确保不影响现有单文档上传、检索、问答主链路

建议执行顺序：

1. 先做 `文档主数据扩展`
2. 再做 `文档列表接口与筛选`
3. 再做 `文档列表页` 和 `文档预览`
4. 然后做 `删除文档` 和 `重建向量`
5. 最后做 `批量上传` 和 `回归测试`

### 6.3 `v0.3.0` 登录、部门与最小权限

目标：

- 在不打散主链路的前提下，补最小鉴权和部门隔离

必须完成：

- 账号密码登录
- Token 鉴权
- 用户、部门、角色三类基础模型
- 普通员工默认仅看本部门授权内容
- 部门管理员仅管理本部门内容
- 系统管理员拥有全局管理权限

明确不做：

- 复杂 ACL 规则引擎
- 跨部门精细授权后台
- 审计大盘

低耦合要求：

- 权限上下文统一由后端构造
- 前端不自行决定最终权限
- 检索过滤复用统一部门上下文，不在各接口手写一套

验收标准：

- 不同角色登录后看到的入口和数据范围正确
- 文档检索和问答能按部门过滤
- 管理员操作边界不串部门

具体拆分：

后端：

- 补登录接口、登出接口、当前用户信息接口
- 增加用户、部门、角色三类核心模型
- 中间件或依赖层统一解析 Token，并构造权限上下文
- 文档列表、检索、问答、SOP 列表都复用同一份部门过滤逻辑
- 部门管理员接口操作范围限制在本部门

前端：

- 增加登录页
- 增加登录态持久化和过期处理
- 根据角色控制导航和页面入口显隐
- 未登录、无权限、会话过期三种状态分开提示

数据与接口：

- 先冻结最小角色模型：
  `employee / department_admin / sys_admin`
- 先只做“部门级隔离”，不在这版上复杂 ACL
- JWT 或 Token 中不直接塞过多业务字段，详细权限上下文由后端查询并构造
- 当前阶段可以先导入真实部门结构，但不建议一开始就把全企业所有账号一次性开通
- 部门主数据和账号主数据要分开推进：
  先完成组织结构整理，再按试点部门逐步开账号
- 账号初始化建议采用“小范围试点”：
  先选 `1~3` 个部门验证登录、权限过滤、上传、检索、SOP 查看流程，稳定后再扩全量
- 全公司部门结构建议在 `v0.3.0` 前后尽早整理并导入，方便后续主数据、筛选和权限边界一次定准
- 全员账号和人数导入不建议在 `v0.3.0` 一开始完成，建议放到：
  `v0.4.0` 试点稳定之后，最早在 `v0.5.0` 后半段准备，最合适的落点是 `v0.6.0` 开始前或扩大推广前
- 全员导入前必须先具备：
  账号停用、初始密码规则、密码重置、导入回滚、批量状态校验
- 如果后续走企业微信通讯录同步，全员导入前还要先冻结：
  企业微信 `department_id / user_id` 到系统内部 `department_id / user_id` 的映射规则
- 当前首个试点部门先定为：
  `数字化部`
- 不建议使用“一个部门一个公共账号”或“一个部门统一默认密码”的方式
- 用户账号应保持一人一号，初始密码也应按用户唯一分配；即使采用统一生成规则，也不应整部门共用同一密码
- 后续如果进入真实上线阶段，需继续补：
  密码重置、账号停用、批量导入、首次改密，以及与企业现有身份系统对接的能力

测试与验收：

- 覆盖登录成功、登录失败、Token 过期、无权限访问
- 覆盖不同角色进入同一页面的数据差异
- 覆盖问答、检索、文档列表三个入口的部门过滤一致性

建议按 issue 拆分：

1. 用户、部门、角色基础模型

- 新增用户、部门、角色三类基础模型
- 冻结最小角色集：
  `employee / department_admin / sys_admin`
- 明确用户和部门的归属关系
- 明确“部门可先全量导入、账号先试点导入”的初始化策略
- 明确账号命名规则、初始密码规则、停用规则不按部门共享

2. 登录与鉴权接口

- 新增登录接口
- 新增登出接口
- 新增当前用户信息接口
- 明确 Token 过期和刷新策略
- 登录实现默认按“用户独立账号、独立密码”设计，不为部门公共账号做优先适配

3. 后端权限上下文

- 中间件或依赖层统一解析 Token
- 统一构造用户、角色、部门上下文
- 业务接口不再各自解析权限

4. 部门级数据过滤

- 文档列表按部门过滤
- 检索按部门过滤
- 问答按部门过滤
- SOP 列表后续也复用同一逻辑

5. 前端登录态和导航控制

- 增加登录页
- 增加登录态持久化
- 根据角色控制导航和页面可见入口
- 未登录、无权限、Token 过期分别提示

6. 部门管理员边界控制

- 部门管理员只可操作本部门内容
- 系统管理员拥有全局入口
- 普通员工只保留查看和检索能力

7. 权限回归测试

- 覆盖登录成功与失败
- 覆盖 Token 过期
- 覆盖跨部门访问被拒绝
- 覆盖检索、问答、文档列表三处过滤一致性

建议执行顺序：

1. 先做 `用户、部门、角色基础模型`
2. 再做 `登录与鉴权接口`
3. 再做 `后端权限上下文`
4. 然后做 `部门级数据过滤`
5. 最后做 `前端登录态和导航控制`、`部门管理员边界控制`、`权限回归测试`

### 6.4 `v0.4.0` SOP 查看与下载

目标：

- 先把 SOP 作为可浏览、可预览、可下载的业务资产接进系统

必须完成：

- SOP 列表页
- 按部门分类浏览
- 按工序 / 场景分类浏览
- SOP 在线预览
- SOP 下载 `docx / pdf`

明确不做：

- SOP 智能生成
- SOP 富文本编辑
- SOP 多版本回溯后台

低耦合要求：

- SOP 资产管理独立于当前 RAG 解析主链路
- SOP 下载能力不反向要求现在就把 `docx` 全量纳入解析主链路

验收标准：

- 员工可以浏览、预览、下载 SOP
- 权限仍按部门边界生效
- 不影响现有文档入库和问答链路

具体拆分：

后端：

- 新增 SOP 主数据对象：
  至少包含 `sop_id`、标题、部门、工序/场景、版本、文件路径、预览路径、状态
- 新增 SOP 列表接口、详情接口、预览接口、下载接口
- 下载接口支持 `docx` 和 `pdf` 两种格式
- SOP 列表按部门权限过滤

前端：

- 增加 SOP 列表页
- 增加部门筛选和工序/场景筛选
- 增加 SOP 详情或预览页
- 增加下载按钮和下载格式选择

数据与接口：

- SOP 作为独立业务对象管理，不复用文档对象硬塞字段
- 预览资源路径和下载资源路径分开，避免后面导出逻辑耦合
- 先支持系统中已有 SOP 资产的展示，不要求这版先做 SOP 生成

测试与验收：

- 覆盖 SOP 列表、详情、预览、下载接口
- 覆盖部门权限过滤
- 人工验证：
  同一个用户能按分类找到 SOP，预览正常，下载 `docx/pdf` 正常

建议按 issue 拆分：

1. SOP 主数据模型

- 新增 SOP 主数据对象
- 至少补齐：
  标题、部门、工序/场景、版本、状态、预览资源、下载资源
- 保证 SOP 与普通文档对象分开管理

2. SOP 列表接口

- 新增 SOP 列表接口
- 支持部门、工序/场景筛选
- 支持按权限过滤结果

3. SOP 列表页

- 增加 SOP 列表页
- 增加部门筛选
- 增加工序 / 场景筛选
- 展示标题、部门、版本、更新时间

4. SOP 详情与预览

- 新增 SOP 详情接口
- 新增预览接口
- 前端支持进入详情页或预览页

5. SOP 下载

- 增加 `docx / pdf` 下载接口
- 前端增加下载格式选择
- 对文件不存在、无权限、下载失败给出提示

6. 权限与资源路径收口

- SOP 权限统一复用部门权限逻辑
- 预览路径和下载路径分开管理
- 不让 SOP 下载逻辑反向侵入文档解析主链路

7. 回归测试

- 覆盖列表、详情、预览、下载
- 覆盖部门权限
- 覆盖资源缺失和下载失败路径

建议执行顺序：

1. 先做 `SOP 主数据模型`
2. 再做 `SOP 列表接口`
3. 再做 `SOP 列表页`
4. 然后做 `SOP 详情与预览`
5. 最后做 `SOP 下载`、`权限与资源路径收口`、`回归测试`

补充说明：模型级 `rerank` 在这一版不是强依赖。

- `v0.4.0` 的目标是先让员工能稳定地“找到、看到、下载” SOP
- 问答与检索先继续使用当前 `heuristic rerank`
- 如果首轮业务试点已经暴露出“召回有了，但排序不准、引用不稳、上下文质量不够”的问题，再把模型级 `rerank` 拉进下一步
- 不建议为了 `v0.4.0` 先引入新的 rerank 模型服务，把试点时间推迟
- OCR 图片处理和模型级 `rerank` 单独收敛到 `v0.4.5`，作为 `v0.5.0` SOP 直生前的能力增强版

### 6.4.5 `v0.4.5` OCR 图片处理、混合检索与检索质量增强

目标：

- 在 SOP 直生前补齐文档理解缺口，并把 OCR / hybrid retrieval / rerank 收口成可复用底座

当前代码现实补充（`2026-03-28`）：

- 轻量 hybrid retrieval 主干已经落地：
  `lexical retriever + BM25-like recall + weighted RRF fusion + vector_only fallback`
- OCR 主干已经落地：
  图片文件 OCR、扫描 PDF / 图片型 PDF OCR fallback、OCR artifact 落盘、OCR metadata 进入 chunk / retrieval / citation / snapshot
- `2026-03-28` 新增：
  `DOCX` 内嵌图片 OCR 已进入异步入库主链路，支持“正文 + 嵌图 OCR”混合入库
- 模型级 `rerank` 代码路径已具备 openai-compatible provider + `heuristic` fallback

已完成：

- 图片文件 OCR 入库
- 扫描 PDF / 图片型 PDF OCR fallback
- `DOCX` 内嵌图片 OCR
- `ocr_processing / partial_failed` ingest 状态真正接入主链路
- OCR artifact 落盘
- OCR metadata 进入 chunk / retrieval / citation / snapshot
- hybrid retrieval 主干
- `lexical_top_k` 配置化
- OCR quality-aware heuristic rerank

剩余缺口：

- 普通 PDF 中“局部图片”精细 OCR，而不是仅整页 fallback
- OCR 质量阈值与低质量 chunk 的治理策略
- OCR 结果在前端的解释性增强
- 模型级 `rerank` 进入生产默认路径前的收益验证、路由收口与配置回归

低耦合要求：

- OCR 继续只进入异步入库链路：
  `上传 -> document/job -> parse/native_extract -> ocr -> chunk -> embedding -> index`
- hybrid retrieval 与模型级 `rerank` 继续只进入在线检索链路
- 不为 OCR 文档单独维护第二套 chunk 索引
- `heuristic` 继续保留为统一降级路径

下一步：

1. 做模型级 `rerank` 生产化验证与默认路由收口
2. 再做 OCR 质量阈值、低质量 chunk 治理与前端解释性
3. 最后再考虑普通 PDF 的局部图片精细 OCR

### 6.5 `v0.5.0` SOP 文档直生与轻交付

目标：

- 把 SOP 主线收敛成“员工上传或选中文档后，直接生成并下载草稿”，并把系统内复杂编辑降为增强项

当前代码现实补充（`2026-03-28`）：

- 员工端 `/portal/sop` 主路径已经可用：
  上传文档 -> 生成 SOP -> 预览 -> 下载
- SOP 草稿已支持 `Markdown / DOCX / PDF` 导出，且未保存草稿也能直接导出
- 来源引用、request trace、request snapshot / replay 已经串到 SOP 生成链路
- `fast / accurate` 两档已接通，SOP 生成默认走 `accurate`
- 工作台 SOP 页仍存在，但已经不再是员工主入口

已完成：

- 员工端 `/portal/sop` 上传文档 -> 生成 SOP -> 下载
- 按当前文档直接生成 SOP
- 按场景生成 SOP
- 自定义主题生成 SOP
- Markdown 草稿下载
- `DOCX / PDF` 草稿导出
- 来源引用与追溯
- SOP 生成 snapshot / replay
- `fast / accurate` 基础双档接通
- 工作台从主入口降级为内部调试/高级入口

剩余缺口：

- 轻记忆 / 多轮上下文还未真正进入 chat / SOP 主链路
- 模型级 `rerank` 还没有收口成生产默认路径
- SOP 模板和结构稳定性还需要进一步收口
- OCR 文档理解还有边角能力待补：
  普通 PDF 局部图片精细 OCR、OCR 质量阈值治理、前端解释性增强

低耦合要求：

- SOP 生成继续复用现有检索、OCR、rerank、query profile 能力
- 不为 SOP 单独维护第二套文档理解链路
- 生成结果继续优先视为可直接下载的交付产物
- 系统内版本保存、复杂在线编辑继续作为增强能力，不反向绑回员工主流程

下一步：

1. 先做模型级 `rerank` 的生产化验证与默认路由收口
2. 再做轻记忆 / 多轮上下文
3. 最后收口 SOP 模板、结构稳定性和来源展示细节

### 6.6 `v0.6.0` 运行治理、配置收口与企业微信接入

目标：

- 把系统补到可追溯、可配置、可复现、可控，并为企业微信和数据库真源迁移留出稳定接口

#### 6.6A 已落地（`2026-03-28` 当前代码现实）

已完成：

- 事件日志底座
- 日志查询接口与日志页
- 系统配置接口与配置页
- 运行态页 `/workspace/ops`
- request trace
- request snapshot / replay
- 通道并发闸门
- 单用户并发保护
- 忙时返回与 `Retry-After`
- `fast / accurate / sop_generation` 运行配置收口

代码现实锚点：

- `backend/app/services/event_log_service.py`
- `backend/app/api/v1/endpoints/logs.py`
- `backend/app/services/system_config_service.py`
- `backend/app/api/v1/endpoints/system_config.py`
- `backend/app/services/ops_service.py`
- `backend/app/api/v1/endpoints/ops.py`
- `backend/app/services/request_trace_service.py`
- `backend/app/services/request_snapshot_service.py`
- `backend/app/services/runtime_gate_service.py`
- `frontend/src/pages/LogsPage.tsx`
- `frontend/src/pages/AdminPage.tsx`
- `frontend/src/pages/OpsPage.tsx`

#### 6.6B 剩余缺口

仍需完成：

- Prometheus / OpenTelemetry 级 metrics/exporter
- 数据库真源：
  日志、配置、会话、轻记忆、外部身份映射
- 企业微信消息接入与通讯录同步
- Query Rewrite
- 轻记忆 / 多轮上下文
- tokenizer-aware 上下文预算与证据裁剪
- 更正式的 busy/degrade UX 细化

低耦合要求：

- metrics、trace、日志继续共享统一的 `request_id / trace_id`，但存储和展示分层
- 企业微信继续只复用已有问答链路，不另起第二套知识处理流程
- 数据库演进继续以“增量加表、增量加列”为主，不推翻当前 `rag_*` 主表
- 运行控制继续通过统一配置/控制服务收口，不允许页面直接修改 service 硬编码

建议新增的数据库对象：

- `rag_departments`
- `rag_users`
- `rag_user_department_bindings`
- `rag_user_role_bindings`
- `rag_external_identities`
- `rag_chat_sessions`
- `rag_chat_messages`
- `rag_system_configs`
- `rag_event_logs`
- `rag_request_traces`
- `rag_request_snapshots`
- `rag_request_snapshot_contexts`

下一步：

1. 先把轻记忆 / 多轮上下文补进主链路
2. 再做 Query Rewrite 与 tokenizer-aware 上下文预算
3. 然后做企业微信消息接入与通讯录同步
4. 最后把日志、配置、会话和外部身份映射逐步迁到数据库真源

### 6.7 `v0.6.x` 当前主契约收口

目标：

- 在继续扩企业微信、数据库真源、metrics/exporter 之前，先把当前 V1 已经对外可见的主契约冻结下来
- 防止后续继续加功能时，把 `documents / retrieval / chat / sops / system-config / logs / ops` 的字段语义再次打散

为什么现在做：

- `v0.4.5` 的 OCR / hybrid retrieval 主干已落地，问答和 SOP 生成已经依赖新的 metadata 字段
- `v0.5` 的员工端 SOP 直生主路径已通，再继续改字段会直接影响前端主流程
- `v0.6A` 的 logs / config / ops / trace / snapshot / gate 已经有页面和接口，再往下继续做企业微信和数据库迁移时，必须先分清“主契约”和“诊断面”

需要冻结的主契约面：

- 身份与健康：
  `GET /api/v1/health`
  `POST /api/v1/auth/login`
  `GET /api/v1/auth/me`
- 文档与入库：
  `POST /api/v1/documents`
  `POST /api/v1/documents/batch`
  `GET /api/v1/documents`
  `GET /api/v1/documents/{doc_id}`
  `GET /api/v1/ingest/jobs/{job_id}`
- 检索与问答：
  `POST /api/v1/retrieval/search`
  `POST /api/v1/chat/ask`
  `POST /api/v1/chat/ask/stream`
- SOP 主路径：
  `POST /api/v1/sops/generate/document`
  `POST /api/v1/sops/export`
  `GET /api/v1/sops`
  `GET /api/v1/sops/{sop_id}`
- 运行治理：
  `GET /api/v1/system-config`
  `PUT /api/v1/system-config`
  `GET /api/v1/logs`
  `GET /api/v1/ops/summary`

冻结的统一字段口径：

- ID 口径：
  `document_id` 为外部统一主字段；当前 `documents / ingest` 响应处于收口过渡期，暂时同时返回 `document_id + doc_id`，其中 `doc_id` 仅用于兼容存量前端，后续逐步退出
- 模式口径：
  `mode` 只使用 `fast / accurate`
- rerank 口径：
  `provider / default_strategy / effective_strategy / model / fallback / cooldown`
- OCR 主路径口径：
  `ocr_used / parser_name / page_no / ocr_confidence / quality_score`
  在 `retrieval results`、`chat citations`、`SOP citations` 三条主链路上保持一致
- 检索 / 引用字段分层：
  稳定主契约优先冻结：
  `chunk_id / document_id / document_name / text|snippet / score / source_path / retrieval_strategy / ocr_used / parser_name / page_no`
  当前诊断字段先不冻结为强承诺：
  `vector_score / lexical_score / fused_score / ocr_confidence / quality_score`
- `logs` 字段分层：
  稳定主契约优先冻结：
  `event_id / category / action / outcome / occurred_at / actor / target_id / mode / rerank_strategy / rerank_provider / duration_ms / downgraded_from`
  当前诊断字段先不冻结为强承诺：
  `target_type / top_k / candidate_top_k / rerank_top_n / rerank_model / timeout_flag / details`
- `ops/summary` 字段分层：
  稳定主契约优先冻结：
  `checked_at / health / queue / runtime_gate / recent_window / rerank_usage / rerank_decision / categories / recent_failures / recent_degraded / config`
  其中 `rerank_usage` 当前优先冻结计数类字段，`last_provider_at / last_heuristic_at` 先保留为诊断字段
  `categories` 当前优先冻结计数字段，`last_event_at / last_failed_at` 先保留为诊断字段
  当前诊断字段先不冻结为强承诺：
  `stuck_ingest_jobs / recent_traces / recent_snapshots`
- `health` 字段分层：
  稳定主契约优先冻结：
  顶层 `status / app_name / environment / vector_store / llm / embedding / reranker / queue / metadata_store / ocr`
  其中 `reranker` 当前优先冻结：
  `provider / base_url / model / default_strategy / timeout_seconds / failure_cooldown_seconds / effective_provider / effective_model / effective_strategy / fallback_enabled / lock_active / cooldown_remaining_seconds / ready`
  `ocr` 当前优先冻结：
  `provider / language / enabled / ready / pdf_native_text_min_chars / angle_cls_enabled`
  当前诊断字段先不冻结为强承诺：
  `reranker.lock_source / reranker.detail / ocr.detail`
- `system-config` 字段分层：
  顶层稳定主契约优先冻结：
  `query_profiles / model_routing / reranker_routing / degrade_controls / retry_controls / concurrency_controls / prompt_budget / updated_at / updated_by`
  组内字段当前也按稳定主契约冻结，不再允许静默漂移
- 文档与任务状态：
  文档主状态和 ingest/job 状态分离，不混用
- 分页口径：
  统一使用 `total / page / page_size / items`
- 时间字段：
  统一使用 ISO 8601 datetime
- 错误语义：
  主业务接口优先返回稳定的 HTTP 状态 + 结构化错误描述，不让页面依赖临时拼出来的 detail 文本
  当前冻结口径为：
  保留兼容字段 `detail`
  并统一补 `error.code / error.message / error.status_code`
  其中请求校验错误继续保留 FastAPI 风格的 `detail[]` 明细列表，不另造一套自定义结构
- `chat/ask/stream` 事件口径：
  冻结 `meta / answer_delta / done / error` 四类事件
  其中 `error` 事件统一使用：
  `code / message / retryable / retry_after_seconds`

明确不冻结的诊断面：

- `POST /api/v1/retrieval/rerank-compare`
- `GET /api/v1/traces`
- `GET /api/v1/request-snapshots`
- request replay
- OCR artifact JSON 明细
- 各类 debug / trace / snapshot 扩展字段

这些接口当前仍可继续演进，但必须明确标成：
“当前可用的内部诊断面，不作为 V1 对外稳定契约承诺”。

执行顺序：

1. 先把契约冻结原则写进：
   `RAG架构.md`
   `V1_PLAN.md`
   `.codex/skills/auto-feature-smoke-test/SKILL.md`
2. 再按当前代码现实补一份主契约清单：
   路径、请求体、响应体、状态码、字段语义
3. 然后给冻结的主契约补 contract 回归：
   最少覆盖 `documents / retrieval / chat / sops / system-config / logs / ops`
4. 最后再继续企业微信、数据库真源迁移和更正式 metrics/exporter

当前契约矩阵已单独收口到：

- `MAIN_CONTRACT_MATRIX.md`

验收标准：

- `RAG架构.md` 能明确区分：
  主契约冻结面 vs 诊断面
- `V1_PLAN.md` 不再把契约收口写成“以后再说”，而是明确为当前优先动作
- smoke skill 默认围绕冻结主契约做验证，不把 `traces / request-snapshots / rerank-compare` 误当成稳定接口
- 后续新增功能如果要改主契约，必须在计划和架构里显式记录，而不是静默漂移

---

## 7. 当前版本与需求文档的对应关系

需求文档里的“V1 最小可用版”更像是上面 `v0.1.2 -> v0.6.0` 这一串小版本合起来的结果，而不是今天当前代码状态本身。

所以这里要明确区分：

- 需求文档里的 `V1`：
  是产品目标
- 仓库里的当前状态：
  是技术底座 + 第一阶段能力
- 这份计划里的版本号：
  是从当前代码逐步走向需求文档 V1 的实施路线

这样定义后，计划、代码和业务预期才不会互相打架。

---

## 8. 建议优先级

真实推进顺序建议固定为：

1. `v0.1.2`
2. `v0.2.0`
3. `v0.3.0`
4. `v0.4.0`
5. `v0.5.0`
6. `v0.6.0`

原因很简单：

- 先稳主链路
- 再补文档管理
- 再补权限
- 然后再做 SOP 查看下载
- 最后再做 SOP 生成和外围能力

如果顺序反过来，后面的每个模块都会重新定义前面的接口和数据结构。

---

## 9. 试点节奏建议

当前不建议等到 `v0.6.0` 全部完成后再开始试点。

建议节奏：

- 现在开始“试点准备”：
  整理真实部门结构、选定 `1~3` 个试点部门、准备少量真实账号和真实文档
- 当前第一个试点部门先按：
  `数字化部`
- 在 `v0.3.0` 完成后继续做“权限与组织验证”：
  验证登录、部门隔离、账号初始化策略、上传与检索边界是否符合企业实际
- 在 `v0.4.0` 完成后启动“业务试点”：
  这时已经具备登录、部门权限、问答检索、SOP 查看/预览/下载，足以让业务用户给出真实反馈
- 不建议把第一次真实用户试用拖到 `v0.6.0`：
  太晚才试点，会导致前面几个版本在缺少真实用户反馈的情况下走偏
- `v0.6.0` 更适合作为“扩大推广”节点：
  在试点验证通过后，再补日志、配置、企业微信等外围能力，并逐步扩到更多部门

试点边界建议：

- 试点优先验证“能不能用”，不是一次性验证所有后台能力
- 试点用户以普通员工和部门管理员为主，系统管理员只保留少量内部账号
- 试点成功标准应至少包含：
  能登录、能看到本部门内容、能完成检索问答、能查看下载 SOP、能基于文档直接生成并下载 SOP 草稿、权限不串部门

全量组织与全员导入时机建议：

- 全公司部门结构：
  可以在 `v0.3.0` 阶段尽早一次性导入，因为它主要影响权限边界、筛选项和主数据口径
- 全员账号与人数：
  不建议在试点前一次性导入
- 更合理的节奏是：
  `v0.3.0` 导入部门结构 -> `v0.4.0` 只用试点员工跑通业务 -> `v0.5.0` 后半段准备全员导入模板和回滚机制 -> `v0.6.0` 开始前或扩大推广前导入全员
- 全员导入前必须先冻结：
  用户唯一账号规则、初始密码规则、停用规则、批量导入模板、错误回滚和复核流程
- 全员导入应作为独立批处理能力实现，不和登录、问答、SOP 主链路硬耦合

---

## 10. 性能、并发与双卡模型部署补充

这部分不是要现在立刻把基础设施全重做，而是把“什么时候做、做到什么程度、双卡 4090 怎么放模型”提前写清楚，避免后面边做边猜。

### 10.1 什么时候做

- `v0.4.0`：
  先记录真实业务试点的基线数据，不急着为了理论并发先大改架构
- `v0.5.0`：
  落地 `fast / accurate` 两档问答，以及模型级 `rerank`
- `v0.6.0`：
  落地在线并发控制、超时控制、降级策略、参数配置、压力测试与运行手册
- `v0.6.0` 后、扩大推广前：
  再根据试点日志决定是否要进一步上更大模型、双卡张量并行、或更复杂的多路由

一句话：

- 先做“能用”
- 再做“快慢双档”
- 最后做“30 并发、降级、压测、部署收口”

### 10.2 模型 provider 路线怎么定

V1 推荐统一收敛成“两层 provider 边界”：

- 主路径：
  `vLLM(OpenAI-compatible)`
- 备用或后续扩展路径：
  `external_llm_api`

这里的目标不是现在立刻双活，而是先把边界定清：

- 当前默认自建模型服务统一走 `vLLM`
- 不再把 `Ollama` 作为 V1 主路径继续扩展
- 业务层通过统一的 LLM provider 接口调用，不直接写死某家 API 的请求字段
- 外部 LLM API 先作为预留能力：
  用于未来的高质量路由、峰值兜底、外部模型试验或灰度切换

建议时机：

- `v0.5.0`：
  收口统一 provider 抽象，默认只接 `vLLM`
- `v0.6.0`：
  把外部 LLM API provider 正式纳入配置和日志体系

### 10.3 `30` 并发要求怎么理解

这里建议把“30 并发”定义成：

- 系统能同时接入 `30` 个在线请求
- 忙时允许排队、限流、降级
- 但不能出现整条问答 / SOP 生成链路整体卡死

不建议把它定义成：

- `30` 个“精准档”长回答同时满配运行、且每个都保持最高质量

对当前 V1，更合理的容量拆分是：

- `fast` 问答通道：
  `20~24` 并发
- `accurate` 问答通道：
  `4~6` 并发
- SOP 生成通道：
  `2~4` 并发
- 异步入库 worker：
  单独控制，不和在线问答抢同一组高成本生成资源

### 10.4 `fast / accurate` 两档怎么做

当前建议先不做两套 chunk 索引，而是先共享一套 chunk 配置，降低耦合和重建成本。

V1 推荐先冻结一套全局 chunk 基线：

- `chunk_size`：
  约 `500~700` 中文字
- `chunk_overlap`：
  约 `80~120`

原因：

- 这套范围对当前文档问答、SOP 生成、下载引用已经够用
- 如果一开始为了快慢双档维护两套 chunk 规则，会直接把入库、回填、压测都复杂化

`fast` 档建议：

- 默认面向员工端问答
- 目标是“快、有引用、质量够用”
- 推荐参数口径：
  `top_k = 8~12`
- `rerank_top_n = 3~5`
- 引用展示：
  `3~4` 条
- 超时预算：
  `8~12s`
- 不额外增加 query rewrite / multi-query

`accurate` 档建议：

- 默认面向高质量问答与 SOP 生成
- 目标是“慢一点，但证据更稳、上下文更完整”
- 推荐参数口径：
  `top_k = 20~30`
- `rerank_top_n = 6~8`
- 引用展示：
  `5~8` 条
- 超时预算：
  `15~25s`

对这两档，V1 的建议优先级是：

1. 先调 `top_k / rerank_top_n / timeout`
2. 再调模型路由
3. 如果还不够，再考虑二次切块或更复杂的检索重写

不要在 `v0.5.0` 之前就把“双索引 / 双 chunk 规则 / 多阶段检索”一起塞进来。

### 10.5 轻记忆、多轮上下文和 Query Rewrite 什么时候加

当前状态判断：

- 当前代码已经有多轮问答页面和问答链路，但还没有正式的“按用户/会话保存轻记忆”能力
- 当前代码也还没有正式的 Query Rewrite 服务，只是在规划里明确了“不要过早塞进主链路”

V1 建议这样拆：

- `v0.5.0`：
  先加轻记忆，多轮上下文只保留最近窗口
- `v0.5.0` 后半段到 `v0.6.0`：
  再加轻量 Query Rewrite，并且先作为可开关增强能力，不默认对所有请求强制启用

轻记忆建议口径：

- 按“用户 + 会话”保存
- 默认保留最近 `6~8` 轮用户/助手消息
- 先解决连续追问，不做长期记忆知识化
- 记忆对象和知识库 chunk、SOP 版本、日志对象分层管理，避免后面数据互相污染

Query Rewrite 建议口径：

- 只作为独立服务层能力加入，不散落在页面里或每个 endpoint 各写一套
- 先对这些场景启用：
  检索结果过少、问题过短、指代不清、上一轮上下文依赖明显
- 不建议对每个请求都先 rewrite，一方面会拖慢时延，另一方面会增加不可控改写风险
- 忙时降级顺序里，应该优先关闭 Rewrite，再减少证据量，最后再考虑 `accurate -> fast`

### 10.6 tokenizer、上下文预算和 chunk 策略怎么做

V1 不建议一开始就把 chunk 切分、上下文打包、模型路由全部混在一起做。更合理的做法是：

- 入库阶段继续保持一套全局 chunk 基线
- 在线阶段新增 tokenizer-aware 的上下文预算控制
- 两层能力分开，保证 chunk 调整不会直接改坏在线打包逻辑

chunk 策略建议：

- `v0.5.0` 之前继续沿用统一基线：
  `chunk_size = 500~700` 中文字
- `chunk_overlap = 80~120`
- 不为 `fast / accurate` 维护两套离线 chunk
- 文档类型差异化 chunk 规则放到 `v0.6.0` 之后再评估

tokenizer 与上下文预算建议：

- `v0.5.0`：
  仍允许继续用字符级 chunk 作为入库基线
- `v0.6.0`：
  必须新增 tokenizer-aware 的上下文预算服务

建议把单次请求上下文预算拆成 4 段：

- 输出保留预算：
  先留 `20%~30%` 给回答本身
- 系统与指令预算：
  约 `10%`
- 轻记忆预算：
  约 `10%~20%`
- 检索证据预算：
  剩余 `40%~55%`

在线打包顺序建议固定为：

1. 先保留输出预算
2. 再放系统指令
3. 再放最近多轮记忆
4. 最后按得分装入证据 chunk

这样做的好处是：

- 高并发或长上下文时，不会因为塞满证据导致模型没空间回答
- 后续切换 `vLLM` 模型或外部 API provider 时，只要 tokenizer 适配层一致，业务层不用重写

### 10.7 高并发下的上下文控制怎么做

高并发时，不能只做“排队”，还要做上下文成本控制。建议的在线收缩顺序是：

1. 先关 Query Rewrite
2. 再缩轻记忆窗口：
  `6~8` 轮 -> `4` 轮 -> `2` 轮
3. 再减少证据量：
  降 `rerank_top_n`，再降 `top_k`
4. 再收敛引用展示条数
5. 最后再触发：
  `accurate -> fast`

对 SOP 生成的特殊建议：

- SOP 生成忙时不应该直接无响应
- 先缩证据包，再走 retrieval fallback 草稿
- 仍要明确标记“已降级生成”

### 10.8 降级策略怎么定

降级策略建议在 `v0.6.0` 统一落地，不要在各模块里零散硬编码。

推荐的降级顺序：

1. `rerank` 服务不可用

- 直接降级到当前 `heuristic rerank`
- 问答和 SOP 生成都复用同一条降级逻辑

2. `accurate` 通道超时或排队过长

- 如果是普通问答：
  可自动降级到 `fast`
- 如果是 SOP 生成：
  优先等待短队列；超过阈值后再提示“稍后重试”或走 retrieval fallback

3. LLM 不可用或超时

- 问答：
  返回带引用的检索摘要，而不是空白失败
- SOP：
  返回 retrieval fallback 草稿，并允许直接下载到本地改

4. Embedding 不可用

- 直接失败并提示依赖异常
- 不做“伪答案”降级

5. Qdrant 延迟过高

- 优先把请求收敛到 `fast` 安全参数
- 减少 `top_k`
- 保留明确的“已降级”标记

6. 异步入库 backlog 过高

- 限制 worker 并发
- 不让大批量入库把在线问答 / SOP 生成拖垮

### 10.9 双卡 `4090` 的模型怎么放

当前是双卡 `4090`，每张 `24GB`。对这类机器，V1 更推荐“一张卡一个主模型”，而不是一开始就把一个更大的模型硬拆到两张卡上。

原因：

- `4090` 没有 NVLink
- 双卡张量并行能跑，但跨卡同步延迟不适合先追求稳定的在线服务
- 你现在更需要的是：
  稳定、可控、可分流，而不是一开始就把最大模型堆上去

V1 推荐部署口径：

- `GPU0`：
  `fast` 问答模型
- `GPU1`：
  `accurate` 问答模型

模型大小建议：

- `fast`：
  先用 `7B` 指令模型
- `accurate`：
  先用 `14B` 指令模型的量化版本（如 `AWQ / INT4`）

不建议当前就把 `32B` 当成 V1 默认主力模型，原因是：

- 你现在的核心目标是业务试点和 `30` 并发可接入
- `32B` 即使能在双卡上跑，也会更明显地挤压并发和时延预算
- 更适合作为后续评估路线，而不是 V1 默认口径

更具体的建议是：

- 员工默认问答：
  `7B`
- 高质量 `accurate` 问答：
  `14B quantized`
- SOP 生成：
  默认复用 `accurate` 档

Embedding / Rerank / 外部 API 建议：

- 如果当前远端 Embedding 服务稳定，V1 可以继续复用，不强制现在全迁本机
- 如果后面要本机化，优先上轻量 Embedding / Rerank，不要先和 `fast` 主模型抢同一张卡的预算
- 外部 LLM API 不建议在 V1 一开始就作为默认主路径，但应在 provider 抽象里预留：
  作为后续高质量模型、溢出流量、灰度实验和外部服务接入点

### 10.10 并发控制怎么落地

推荐在 `v0.6.0` 把并发控制做成统一服务层能力：

- API 层加 semaphore / queue
- 按通道分别限流：
  `fast / accurate / sop_generate / ingest`
- 单用户并发再做一层保护：
  例如同一用户同时 `2~3` 个在线请求上限

前端配合策略：

- 明确告诉用户当前是 `fast` 还是 `accurate`
- 如果请求被降级，要在返回中明确标注
- 如果系统忙，不要无限转圈，要给出“忙时提示 / 可重试 / 已降级”状态

### 10.11 压测与验收怎么做

建议拆成两段，不要一开始就追 `30` 并发满配：

第一段：

- 在 `v0.5.0` 完成后做 `10~15` 并发冒烟压测
- 目标是验证双档逻辑、降级逻辑、日志字段是否打通

第二段：

- 在 `v0.6.0` 完成后做 `30` 并发接入压测
- 重点不是“每个请求都最优质量”
- 而是验证：
  有限流、有排队、有降级、无整体雪崩

压测验收至少记录：

- `P50 / P95 / timeout rate`
- `fast / accurate` 各自成功率
- `rerank` 降级次数
- `accurate -> fast` 降级次数
- SOP 生成平均耗时
- queue wait time

### 10.12 可观测、可控、可复现怎么补

这部分的目标不是“把系统监控做得很大”，而是先做到三件事：

- 能看到：
  系统从什么时候开始变坏
- 能动：
  不改代码也能验证关键假设
- 能复现：
  遇到偶发 bug 时，至少能把请求、上下文和运行版本重放出来

指标（metrics）建议最少覆盖：

- `QPS`
- 延迟：
  `p50 / p95 / p99`
- 错误率
- 超时率
- 队列积压：
  `Celery / Redis`
- 资源使用：
  `GPU / CPU / memory`

trace 建议最少覆盖这条链路：

- `query -> rewrite -> retrieval -> rerank -> llm -> answer`

每一步至少记录：

- 耗时
- 输入输出大小
- 命中 chunk 数
- 是否命中缓存
- 是否发生降级

运行控制面建议至少支持这些控制位：

- `debug` 开关
- `top_k`
- `rerank` 开关
- 模型切换 / provider route
- 降级开关：
  `LLM -> extractive/retrieval fallback`
- 限流参数
- 重试策略开关
- worker 并发参数

补充说明：

- worker 容器副本数本身仍属于部署层，不建议伪装成普通业务按钮
- V1 更合理的是：
  应用内先支持 worker 并发和通道配额调节；worker 副本数调整走部署脚本和 runbook

请求快照与重放建议最少保存：

- 原始请求输入
- 会话记忆摘要
- Query Rewrite 前后内容
- 检索命中的 chunk / citation
- prompt 模板版本
- 模型版本 / provider route
- embedding / rerank 版本
- 关键参数：
  `mode / top_k / rerank_top_n / timeout / memory_window`

重放能力建议支持两种模式：

- 原样重放：
  使用原始快照和原始参数重跑
- 对比重放：
  使用原始输入和原始上下文，但按当前配置重跑

这样可以解决的核心问题是：

- “刚刚有 bug，现在没了”

最低目标不是百分百复现线上所有瞬时状态，而是做到：

- 能定位是 `rewrite / retrieval / rerank / llm / answer` 哪一步变坏
- 能知道当时看到的证据是什么
- 能知道当时用的是哪版 prompt、哪路模型、哪组参数
- 能把这次请求再次重放出来做验证

### 10.13 这部分对应到版本路线

为了避免后面忘掉，明确挂到版本里：

- `v0.4.0`：
  只做基线记录，不抢先做大规模并发优化
- `v0.5.0`：
  加 `fast / accurate` 两档、SOP 默认走 `accurate`、轻记忆
- `v0.6.0`：
  加外部 LLM API provider、Query Rewrite、tokenizer-aware 上下文预算、并发控制、降级策略、日志字段、参数配置、压测和 runbook

也就是说：

- `OCR + 轻量 hybrid retrieval + 模型级 rerank` 属于 `v0.4.5`
- 当前代码里 `轻量 hybrid retrieval` 已先行落地，后续以验证、治理和配置收口为主
- `双档质量` 属于 `v0.5.0`
- `轻记忆` 属于 `v0.5.0`
- `Query Rewrite / tokenizer 预算 / 外部 API provider / 并发与降级收口` 属于 `v0.6.0`
- `更大模型 / 更复杂检索集群形态` 放到 `v0.6.0` 之后再评估

---

## 11. `v0.6.0` 开始前建议先做的 3 个小重构

这 3 个重构不是为了“把架构重做一遍”，而是为了避免后面做并发、降级、日志、配置时，把逻辑继续堆进现有热点文件。

目标：

- 不推翻当前代码
- 不阻塞 `v0.5.0` 的继续实现
- 只做对 `v0.6.0` 影响最大的低成本收口

### 11.1 把 `fast / accurate / degrade` 收成统一查询配置

当前风险：

- 现在问答、检索、SOP 生成都已经开始共享检索链路
- 但后面如果直接在 [chat_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/chat_service.py)、[retrieval_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/retrieval_service.py)、[sop_generation_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/sop_generation_service.py) 各自塞 `top_k / rerank_top_n / timeout / mode / downgrade`，很快就会打架

建议重构：

- 新增一层统一的“查询档位配置”对象
- 至少统一这些字段：
  `mode / top_k / rerank_top_n / timeout_budget / fallback_mode / memory_window / rewrite_enabled / output_token_budget`
- 问答和 SOP 生成都只拿这层配置，不自己散写参数
- 后面做系统配置页时，也只改这一层，不直接改 service 里的硬编码

建议落点：

- 新增：
  `backend/app/schemas/query_profile.py`
- 新增：
  `backend/app/services/query_profile_service.py`
- 现有：
  [chat_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/chat_service.py)
- 现有：
  [sop_generation_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/sop_generation_service.py)
- 现有：
  [retrieval_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/retrieval_service.py)

明确不做：

- 不在这一步就上复杂策略引擎
- 不做多阶段 query rewrite 编排器
- 不做双索引 / 双 chunk

验收标准：

- `fast / accurate` 的参数差异只在统一配置层定义一次
- `accurate -> fast`、`rerank -> heuristic` 的降级入口也统一复用
- 轻记忆窗口、Rewrite 开关、输出预算也统一从这一层展开
- 前端只需要传 `mode=fast|accurate`，后端自己展开参数

### 11.2 把 SOP 持久化从 service 直写文件收成 repository

当前风险：

- 当前 SOP 当前版本和历史版本还是由 service 直接读写本地 JSON
- 这对现在开发够用，但后面一旦加日志、配置、发布态、查询筛选，就会让 [sop_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/sop_service.py) 和 [sop_version_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/sop_version_service.py) 同时膨胀

建议重构：

- 增加 SOP repository 边界，把“读 bootstrap / 读 managed records / 写 current / 写 version”统一收口
- 先保留文件系统实现，不强制现在切 PostgreSQL
- 后面如果真要进数据库或对象存储，只替换 repository 层

建议落点：

- 新增：
  `backend/app/db/sop_repository.py`
- 可选实现命名：
  `filesystem_sop_repository.py`
- 现有 service 只保留业务规则、权限判断、视图拼装

明确不做：

- 现在不把 SOP 全迁 PostgreSQL
- 不做复杂 ORM / Prisma 双写
- 不做审批流数据建模

验收标准：

- [sop_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/sop_service.py) 不再直接自己扫目录和写 JSON
- [sop_version_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/sop_version_service.py) 不再直接拼路径写文件
- 现有列表、详情、预览、下载、版本查询行为不变

### 11.3 把员工端 SOP 页拆成“文档驱动生成流”，工作台不再当主入口

当前风险：

- 现在如果继续把 SOP 生成功能主要放在工作台页面，员工真实使用路径会和产品目标错位
- [SopPage.tsx](/home/reggie/vscode_folder/Enterprise-grade_RAG/frontend/src/pages/SopPage.tsx) 现在已经开始承担：
  上传、目录、生成、编辑、保存、版本查看、下载
- 员工端真正需要的主流程其实更短：
  上传文档 -> 生成 SOP -> 下载本地修改

建议重构：

- 把员工端 SOP 生成页明确拆成 3 个区域组件：
  `SourceDocumentPanel / SopDraftPreview / CitationSidebar`
- 页面主流程固定成：
  `上传或选中文档 -> 根据当前文档生成 SOP -> 预览 -> 下载`
- `topic/scenario` 生成保留为次入口，不再当主入口
- 共享状态继续走 [UploadWorkspaceContext.tsx](/home/reggie/vscode_folder/Enterprise-grade_RAG/frontend/src/app/UploadWorkspaceContext.tsx)，不要重新回退到页面内多层 state 传递
- 工作台页若保留，只承接内部调试和高级操作，不再作为员工主路径

建议落点：

- 优先拆分：
  员工端 SOP 页
- 同时收口：
  [SopPage.tsx](/home/reggie/vscode_folder/Enterprise-grade_RAG/frontend/src/pages/SopPage.tsx)
- 新增：
  `frontend/src/features/sop-workspace/*`

明确不做：

- 不重做整套设计系统
- 不在这一步就把 portal 和 workspace 的 SOP 页合并
- 不做复杂富文本编辑器替换

验收标准：

- 员工端页面主按钮明确变成“根据当前文档生成 SOP”
- 没选中文档时，不允许误触发主生成流程
- 员工无需进入工作台，也能完成“上传 -> 生成 -> 下载”
- 后续加忙时提示或轻量归档时，不需要继续把逻辑都堆回一个页面文件

### 11.4 这 3 个重构放在什么时间做

建议节奏：

1. `v0.5.0` 后半段

- 先做 `11.1 查询配置收口`
- 因为它直接影响双档问答和 SOP 生成的继续演进

2. `v0.6.0` 开始前

- 做 `11.2 SOP repository 收口`
- 做 `11.3 员工端 SOP 页拆分`

一句话：

- `11.1` 是为了防止参数和降级逻辑开始散
- `11.2` 是为了防止 SOP 数据层开始散
- `11.3` 是为了防止员工端主流程继续被工作台页面绑架

---

## 12. 计划治理与上线收口

这部分不是新增功能，而是为了避免后面进入 `v0.5.0 / v0.6.0` 后，计划里“做了很多事”，但没有统一的状态、上线边界、治理与回滚口径。

### 12.1 版本状态总览怎么维护

建议在 `V1_PLAN` 文件顶部或单独附录维护一张轻量状态表，至少包含：

- `模块`
- `计划版本`
- `当前状态`
- `代码状态`
- `联调状态`
- `阻塞项`
- `下一步`

推荐状态值统一为：

- `planned`
- `in_progress`
- `blocked`
- `done`
- `verified`

建议首批纳入状态看板的模块：

- 文档上传与异步入库
- 文档管理
- 登录与权限
- 员工端问答
- 员工端 SOP 查看下载
- 员工端 SOP 文档直生
- 轻记忆
- Query Rewrite
- 配置与日志
- 企业微信机器人
- 企业微信通讯录同步

低耦合要求：

- 状态看板只反映交付状态，不和数据库表、接口枚举、前端页面状态耦合
- 代码完成不等于 `verified`
- `verified` 至少要求：
  定向 API 验证 + 本地页面 smoke test 或人工业务链验证

### 12.2 V1 上线切线怎么定

当前建议把“V1 可上线”定义成“可试点扩大推广”，而不是“所有规划能力都做完”。

建议的 V1 上线必备项：

- 稳定的文档上传、异步入库、检索、问答
- 部门级权限隔离
- 员工端 SOP 查看、预览、下载
- 员工端基于当前文档生成并下载 SOP 草稿
- `fast / accurate` 两档问答
- 轻记忆
- 基本日志、基本配置
- 并发控制、超时、降级、忙时提示
- `vLLM` 主路径稳定

建议延期到 `V1+1` 也可接受的项：

- 复杂审批流
- 高级富文本在线编辑
- 跨部门协同编辑
- 双索引 / 双 chunk 规则
- 更大模型默认主力化
- 企业微信侧边栏 / 工作台深度集成
- 高级 BI 化日志分析

一句话切线：

- `V1` 目标是“企业试点和首轮推广可用”
- 不是“把所有设想中的产品化细节一次性做完”

### 12.3 数据治理与保留策略

后面一旦加轻记忆、日志、企业微信同步，就必须把“存多久、谁能看、能不能删”写清楚。

建议先冻结最小治理口径：

- 轻记忆消息：
  默认只保留最近窗口用于在线上下文，不长期累积；持久化保留期建议 `7~30` 天，可配置
- 问答与 SOP 日志：
  用于排障与审计，保留期建议 `90~180` 天，可配置
- 请求快照与重放对象：
  仅用于问题复现和参数对比，保留期建议 `7~30` 天，可配置；不建议默认永久保存完整上下文
- 企业微信同步数据：
  以当前有效组织关系为主，保留变更时间和停用状态，不要求永久保存完整历史快照
- 下载草稿：
  默认视为用户本地文件，不把每次导出结果都作为系统长期资产保存

权限治理建议：

- 普通员工只能看自己的会话与自己的操作结果
- 普通员工不默认查看自己的原始重放快照明细，除非系统明确开放“问题反馈回放”能力
- 部门管理员不默认查看本部门所有员工会话正文，只查看必要的统计或审批结果
- 系统管理员有排障权限，但敏感日志建议支持脱敏展示

脱敏建议：

- 日志里不直接落完整长文本时，优先保留摘要、引用、错误码、耗时、模式和降级信息
- 企业微信外部身份字段通过映射表管理，不直接在业务日志里大面积暴露

### 12.4 迁移与回滚策略

V1 后半段至少有 4 类迁移，不能等到上线时再想：

1. 身份主数据：
`identity_bootstrap.json -> 数据库`

2. SOP 持久化：
`filesystem repository -> 数据库 repository`

3. 配置主数据：
`.env / 本地默认值 -> 系统配置表`

4. 组织同步：
`手工导入 / CSV -> 企业微信通讯录同步`

每类迁移都建议固定 4 个动作：

- 导入前校验
- 影子写入或预演
- 切换开关
- 可逆回滚

建议最低要求：

- 任何新真源切换前，都要保留旧来源的只读回退能力一个阶段
- 不允许“一次切换后无法回退”
- 数据迁移脚本和回滚脚本要作为 runbook 一部分，不只写在口头说明里

### 12.5 兼容与废弃策略

当前计划里已经有一些“先兼容、后收口”的东西，最好提前写清废弃时机。

建议明确的废弃对象：

- `Ollama` 兼容口径：
  V1 不再继续扩展；保留短期兼容读取，但在 `v0.6.0` 后进入废弃状态
- `identity_bootstrap.json` 作为唯一真源：
  只保留初始化和开发兜底用途；进入数据库真源后不再作为正式生产主源
- `workspace/sop` 员工主入口定位：
  已经降级为内部调试/高级入口，后续不再承接员工主流程
- 本地 JSON 直写的 SOP 持久化：
  在 repository 收口并完成数据库版后进入废弃候选

废弃策略建议：

- 先“标记 deprecated”
- 再“停新功能接入”
- 最后“移除默认路径”

不要直接一步删除。至少要经过：

1. 文档标记废弃
2. 配置警告或运行告警
3. 替代方案稳定
4. 再做最终移除

---

## 13. 当前建议输出物

按这版小版本路线推进，建议当前先产出：

- 一份更新后的 [RAG架构.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/RAG架构.md)
- 一份更新后的 [V1_PLAN.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/V1_PLAN.md)
- 一份同步当前代码现实的 [V1_RELEASE.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/V1_RELEASE.md)
- 一份运行侧最小验证清单 [OPS_SMOKE_TEST.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/OPS_SMOKE_TEST.md)
- 一份 `DOCX` 嵌图 OCR 的最小回归清单
- 一个后续版本的接口和数据模型待办表

一句话总结：

**需求文档是目标，当前实现必须拆成小版本逐步靠近；先稳现有代码，再低耦合扩功能。**

---

## 14. 并行切片：模型级 Rerank

如果 `OCR` 和 `rerank` 需要分人并行推进，当前代码现实更适合把 `rerank` 单独拆成一个并行切片，而不是和 `OCR` 绑成同一批开发任务。

原因：

- 当前代码已经有 `RerankerClient` 抽象，并已支持 `heuristic + openai-compatible provider`
- 当前代码已经有 `QueryProfileService`
  其中已冻结 `top_k / candidate_top_k / rerank_top_n / timeout / fallback_mode`
- `ChatService` 和 `SopGenerationService` 已经统一走同一套 rerank 调用与降级逻辑
- `rerank` 不进入异步入库链路，不依赖 OCR 完成后才能先做收益验证和默认路由收口

代码现实锚点：

- `backend/app/rag/rerankers/client.py`
- `backend/app/services/query_profile_service.py`
- `backend/app/services/chat_service.py`
- `backend/app/services/sop_generation_service.py`
- `backend/app/core/config.py`
- `backend/app/services/system_config_service.py`

目标：

- 在不改动异步入库主链路的前提下，把当前“模型级 provider + 启发式兜底”的代码路径收口成可默认启用、可观测、可回滚的正式在线重排能力

当前代码已完成：

- 在现有 `RerankerClient` 上接入可配置 provider
- 保留 `heuristic` 作为统一降级路径
- 统一 `fast / accurate` 两档的 `candidate_top_k / rerank_top_n / timeout_budget`
- 问答与 SOP 生成复用同一套 rerank 输出
- trace / snapshot / event log 中保留 `rerank_strategy` 和降级信息

剩余缺口：

- provider 收益验证和默认路由收口
- 系统配置页和运行态对 rerank provider 的可见性进一步增强
- `openai-compatible` provider 在真实生产服务上的 timeout / 429 / 回退回归

明确不做：

- 不重跑历史 embedding
- 不改 chunk 规则
- 不进入异步入库 worker
- 不为了 rerank 单独新造一套 query profile 体系
- 不在问答和 SOP 各写一份独立重排逻辑

低耦合要求：

- `rerank` 只放在在线链路：
  `retrieval -> rerank -> llm`
- provider 接入优先复用现有 `RerankerClient.rerank()`
- 降级统一走 `QueryProfileService.rerank_with_fallback()`
- 配置入口统一复用当前 `Settings + SystemConfigService`

验收标准：

- `fast` 与 `accurate` 都能走统一 rerank 入口
- provider 正常时返回 `provider` 策略
- provider 不可用时自动降级到 `heuristic`
- 问答与 SOP 生成拿到同一批 rerank 后证据
- 不需要改异步入库链路也能上线

建议按 issue 拆分：

1. 参数与配置收口

- 收口 `candidate_top_k / rerank_top_n / timeout_budget`
- 校验 `fast / accurate` 两档参数边界
- 保持 `accurate -> fast` 的降级路径不变

2. 问答链路验证

- 验证 `ChatService` 走 provider 成功路径
- 验证 provider 不可用后走 `heuristic`
- 验证 trace / snapshot / event log 字段一致

3. SOP 链路验证

- 验证 `SopGenerationService` 复用同一套 rerank 输出
- 验证和问答链路的降级语义一致
- 验证 `accurate` 档默认行为符合预期

4. 默认路由与回滚策略

- 明确什么时候从 `heuristic` 切到 provider 默认
- 明确收益不达标时如何回滚到 `heuristic`
- 保证配置页、日志、运行态同步反映当前默认路径

5. 回归测试

- 覆盖 provider 成功
- 覆盖 provider 超时
- 覆盖 provider 不可用
- 覆盖 `heuristic` 降级
- 覆盖问答 / SOP 双链路一致性

建议执行顺序：

1. 先做 `参数与配置收口`
2. 再做 `问答链路验证`
3. 然后做 `SOP 链路验证`
4. 再做 `默认路由与回滚策略`
5. 最后做 `回归测试`

---

## 15. 并行切片：Hybrid Retrieval（主干已完成，后续以验证与治理为主）

当前代码现实里，`hybrid retrieval` 已经不是待启动切片，而是已落地的能力，需要决定是否继续扩，以及后续收口放在哪一层。

原因：

- 当前在线主检索已经是：
  `query -> embedding -> Qdrant vector recall + lexical recall -> weighted RRF fusion`
- 当前代码已经具备轻量 lexical retriever、BM25-like 关键词召回、`vector_only` fallback
- 当前 `heuristic rerank` 里的 token overlap 仍只能重排已有候选，不能替代第一阶段关键词召回
- `document_id` 过滤、问答、SOP 生成已经复用统一检索入口，继续做验证与治理也适合在入口层统一收口，不必分别侵入多个业务服务

代码现实锚点：

- `backend/app/services/retrieval_service.py`
- `backend/app/rag/vectorstores/qdrant_store.py`
- `backend/app/schemas/retrieval.py`
- `backend/app/services/chat_service.py`
- `backend/app/services/sop_generation_service.py`
- `backend/app/services/query_profile_service.py`
- `backend/app/core/config.py`

目标：

- 在不替换当前 Qdrant 主链路的前提下，把已落地的 hybrid retrieval 从“功能可用”推进到“可观测、可配置、可验证”的可降级能力

必须完成：

- 保持统一的在线检索策略：
  `vector_only | hybrid`
- 保持 lexical retriever、hybrid fusion、`vector_only` fallback 都只收口在统一检索入口层
- `document_id` 过滤在两条召回分支上都语义一致
- 规则式 dynamic weighting 默认关闭，不破坏现有 fixed fallback 行为
- 日志里能看到：
  `query_type / vector_weight / lexical_weight`
- trace / snapshot / debug 信息后续补齐：
  `retrieval_strategy / vector_score / lexical_score / fused_score / query_type / vector_weight / lexical_weight`

明确不做：

- 不切 `pgvector`
- 不重做 chunk 规则
- 不为了 V1 单独引入 `Elasticsearch / OpenSearch` 集群
- 不把关键词索引当系统主数据真源
- 不在前端暴露一堆实验性检索策略按钮
- 不急着把规则分类换成模型分类
- 不在这一阶段继续扩更复杂检索集群形态

低耦合要求：

- hybrid retrieval 只放在在线链路：
  `query -> vector recall + lexical recall -> fusion -> rerank -> llm`
- 关键词索引优先复用当前 chunk 文本和元数据构建轻量副本
- 问答和 SOP 生成只消费统一检索结果，不自行再补一层关键词匹配
- 配置入口统一复用当前 `Settings + SystemConfigService + QueryProfileService`
- dynamic weighting 只放在 fusion 层，不污染 lexical retriever，也不把 branch 融合职责丢给 rerank

验收标准：

- 对专有名词、设备名、料号、工序名类查询，hybrid 检索结果优于当前 vector-only 基线
- `document_id` 限定下，hybrid 不会串文档
- 关键词分支不可用时，系统自动退回 vector-only，不影响主流程可用性
- 问答与 SOP 生成拿到同一批 fusion 后证据
- dynamic weighting 关闭时不破坏当前排序基线
- dynamic weighting 开启后，`exact / semantic / mixed` 能切换分支权重，且日志可解释

建议按剩余 issue 拆分：

1. Trace / snapshot / debug 字段补齐

- 把 `query_type / vector_weight / lexical_weight` 收进 trace/snapshot/debug
- 保持和现有 `retrieval_strategy / vector_score / lexical_score / fused_score` 口径一致

2. Dynamic weighting 配置收口

- 把当前 `Settings` 上的动态权重参数按需要接入系统配置真源
- 明确默认关闭、灰度开启、回退 fixed fallback 的口径

3. 真实 query 样本校准

- 用真实业务 query 样本校准 `exact / semantic / mixed` 规则阈值和权重
- 重点看专有名词类 query 的收益，以及 mixed query 的误判率

4. 问答与 SOP 链路验证

- 验证 `ChatService` 和 `SopGenerationService` 看到同一批 fusion 后证据
- 验证 `document_id` 过滤和权限语义不变
- 验证 debug / trace / snapshot 字段一致

5. 回归测试

- 覆盖 fixed fallback
- 覆盖 dynamic weighting 的 `exact / semantic / mixed`
- 覆盖 lexical 分支失败后退回 vector-only
- 覆盖专有名词类查询的改进样例

建议执行顺序：

1. 先做 `真实 query 样本校准`
2. 再做 `Trace / snapshot / debug 字段补齐`
3. 然后做 `配置与档位收口`
4. 再做 `问答与 SOP 链路验证`
5. 最后做 `回归测试`

验证后如何扩展：

1. 如果验证结果明确为“专有名词类 query 收益稳定，误判率可接受”

- 先把 dynamic weighting 从 `Settings` 收口到系统配置真源
- 保持默认关闭，只允许灰度开启
- 先按租户 / 部门 /环境做小范围放量，不直接全量打开

2. 如果验证结果是“exact query 收益明显，但 mixed query 误判偏多”

- 优先继续调规则阈值、词项特征和权重
- 仍保持规则分类，不急着上模型分类
- 先把 query 样本和 trace 证据收够，再决定是否进入下一阶段

3. 如果验证结果是“规则分类已经到瓶颈，但 hybrid 主干本身有效”

- 放到 `v0.6.0` 之后再评估更高成本扩展：
  `模型分类`、`query rewrite`、更细粒度 query intent、字段级 lexical boosting
- 这类扩展仍应复用当前 fusion 层插槽，不推翻 lexical retriever / RetrievalService 主结构

4. 如果验证结果是“dynamic weighting 收益不稳定，甚至破坏基线”

- 直接回退 fixed fallback
- 保留 hybrid retrieval 主干，不把失败结论扩大成“关键词召回无价值”
- 优先保留 lexical retriever + RRF 主干，只关闭动态权重

5. 在 `v0.6.0` 前不建议提前做的扩展

- 不把规则分类直接替换成模型分类
- 不做多阶段 query rewrite 编排
- 不做多索引、多 chunk 策略并行维护
- 不引入更复杂检索集群形态

也就是说，hybrid retrieval 这条线在当前阶段的正确节奏是：

- 先验证
- 再收口可观测性和配置
- 再决定是否灰度放量
- 最后才评估更高成本扩展
