# Retrieval Optimization Plan

## 0. 编写依据

这份计划基于以下现实约束整理：

- 当前仓库的主契约以 [MAIN_CONTRACT_MATRIX.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/MAIN_CONTRACT_MATRIX.md) 为硬约束
- 当前版本边界以 [V1_PLAN.md](/home/reggie/vscode_folder/Enterprise-grade_RAG/V1_PLAN.md) 为主
- 当前代码已经具备：
  - `vector + lexical + weighted RRF` 混合检索
  - `department first + supplemental recall` 两阶段召回
  - `retrieval / chat / SOP` 共用 retrieval 底层
  - heuristic / provider rerank 插槽
  - 结构化 retrieval diagnostic、trace、ops summary

这意味着检索优化的重点不再是“补第一版 retrieval”，而是：

- 校准
- 收口
- 配置真源
- 样本驱动评估
- 在必要时再推进更重的结构改造

---

## 1. 总体原则

### 1.1 主契约优先

- 不主动扩 `retrieval/search`、`chat/ask`、`system-config` 的稳定 public contract
- 所有 retrieval 优化默认先走内部实现、诊断字段和测试收口
- 只有当确实需要暴露新的主配置或主字段时，才允许同步更新 contract matrix

### 1.2 先调在线策略，再动入库底座

- 能通过 supplemental 阈值、query 样本、router 权重解决的问题，先不要动 chunk
- `chunk` 优化属于更重的入库侧改造，会影响：
  - parsed 结果
  - chunk 文件
  - embedding
  - index
  - 部分 retrieval / citation 质量基线

### 1.3 retrieval / chat / SOP 一致

- 这三条链路继续共用同一个 retrieval 判定逻辑
- 不允许出现：
  - `retrieval/search` 一套 supplemental 规则
  - `chat` 一套规则
  - `SOP` 再单独分叉一套规则

### 1.4 样本驱动，而不是感觉驱动

- 每一轮优化前先准备 query 样本
- 每一轮优化后都用同一批样本复跑
- 决策依据优先看：
  - 命中文档是否对
  - top chunk 是否对
  - citation 是否更稳
  - supplemental 触发是否更合理

---

## 2. 当前问题分层

当前 retrieval 质量问题，建议分成 4 层看：

### 2.1 在线召回与补充召回层

典型问题：

- 本部门结果明明够，但 supplemental 触发过早
- 本部门结果明显不足，但 supplemental 触发过晚
- fine-grained query 对缩写、编号、条款号不够稳

优先手段：

- supplemental 阈值校准
- query 样本分类
- diagnostics 复盘

### 2.2 候选质量层

典型问题：

- 检索到的文档是对的，但排前面的 chunk 不对
- 命中是“差不多相关”，不是“真正该引用的块”

优先手段：

- lexical / vector 权重校准
- query router 分类阈值校准
- rerank 前候选质量检查

### 2.3 chunk 层

典型问题：

- 命中文档正确，但 chunk 太大、太碎或边界不对
- 条款问句总命中章节摘要，而不是具体条款
- 引用片段总是半截、混段、跨主题

优先手段：

- chunk 参数优化
- 结构化 chunk 规则增强
- 代表性文档重建索引对比

### 2.4 rerank 层

典型问题：

- 候选本身已经不错，但排序最后一公里不稳
- heuristic 和 provider 在真实样本上差异明显

优先手段：

- rerank canary 样本复盘
- 默认路由切换评估

---

## 3. 优先级与顺序

建议执行顺序固定为：

### Phase 1：补充召回与阈值收口

目标：

- 把 `department_sufficient / department_insufficient / department_low_quality` 三类判定调稳
- 保持 `retrieval / chat / SOP` 行为一致

已完成基础：

- supplemental 质量阈值已经进入内部真源
- public contract 未扩张

下一步要做：

- 准备一批真实 query 样本
- 按 query 类型标记：
  - exact / code-like
  - fine-grained
  - semantic
  - broad summary
- 记录每条样本的：
  - 期望主文档
  - 期望 top chunk
  - 是否应该触发 supplemental
- 用固定样本复跑，校准内部阈值：
  - `top1_threshold`
  - `avg_top_n_threshold`
  - `fine_query_top1_threshold`
  - `fine_query_avg_top_n_threshold`

验收标准：

- 本部门结果够好时，supplemental 不滥触发
- 本部门结果明显不足或低质时，supplemental 能稳定触发
- diagnostics 与实际行为一致

### Phase 2：chunk 优化

这是下一优先级，不建议早于 Phase 1。

原因：

- chunk 改动会触发重建索引
- 它会改变 retrieval 候选本身
- 如果先动 chunk，再校准 supplemental，很难判断问题究竟来自召回逻辑还是切块逻辑

本阶段目标：

- 解决“命中文档正确，但 chunk 不对”的问题

切分为两类：

#### A. 通用文档 chunk

关注参数：

- `chunk_size_chars`
- `chunk_overlap_chars`
- `chunk_min_chars`

优先评估文档类型：

- FAQ / 说明类纯文本
- 普通 PDF
- OCR 文档
- DOCX 混合正文与图片 OCR 文档

优化方法：

- 准备一组代表性文档
- 每次只改一组 chunk 参数
- 对比：
  - chunk 数量
  - 平均 chunk 长度
  - top chunk 命中质量
  - citation 可读性

#### B. SOP / WI / 规范类结构化 chunk

当前仓库已经有结构化 chunker：

- [structured_chunker.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/chunkers/structured_chunker.py)

本阶段重点不是重写，而是补规则和样本：

- 文档摘要 chunk 是否太泛
- section summary 是否抢走 clause 命中
- clause chunk 的 retrieval_text 是否足够包含文号、章节号、关键词
- 条款问句能否稳定命中 clause，而不是 doc summary

验收标准：

- 文号 / 条款号 / 规范操作类 query 的 top chunk 更精确
- 引用片段更短、更聚焦、更接近最终回答需要的证据
- 不明显拉高误召回率

### Phase 3：query router 与 hybrid 权重校准

只有在 Phase 1 和 Phase 2 做完后再进入。

目标：

- 解决 exact / semantic / mixed query 的候选质量差异

范围：

- query classifier 阈值
- vector / lexical branch 权重
- fine query 的分类误判

验收标准：

- 编号、代码、缩写、文号类 query 更稳定
- broad semantic query 不因过度 lexical 化而掉召回

### Phase 4：rerank 默认路由决策

最后做。

原因：

- rerank 解决的是“最后排序”
- 如果 chunk 和候选本身不干净，rerank 只是在脏候选上做更贵的排序

范围：

- canary 样本复盘
- provider / heuristic 差异评估
- 默认策略切换决策

---

## 4. chunk 应该排在哪

明确结论：

- `chunk` 优化应该排在 `supplemental 阈值收口之后`
- `chunk` 优化应该排在 `query router / rerank 默认路由之前`

推荐顺序：

1. `supplemental` 阈值和样本校准
2. `chunk` 优化
3. router / hybrid 权重优化
4. rerank 默认路由优化

只有在下面这种情况下，chunk 才可以提前升级为下一阶段第一优先级：

- 命中文档经常是对的
- supplemental 触发也大体合理
- 但 top chunk / citation 质量依然明显不对

也就是说：

- 如果问题是“召回范围不对”，先调 Phase 1
- 如果问题是“证据块不对”，再进 Phase 2

---

## 5. 每一阶段都要保住的东西

### 5.1 不破坏主契约

- 不改 `retrieval/search` 稳定请求字段
- 不改 `chat/ask` 稳定请求字段
- 不改 `results[] / citations[]` 的主字段名

### 5.2 不破坏权限语义

- 直接资源访问权限和 retrieval supplemental 可见范围继续分离
- 不允许为了提升召回率而打穿 tenant / department / retrieval_department_ids 边界

### 5.3 不跳过回归

每次 retrieval 优化至少回归：

- `backend/tests/test_retrieval_chat.py`
- `backend/tests/test_main_contract_endpoints.py`
- `backend/tests/test_main_contract_errors.py`
- 受影响的 `system_config` / `ops` / `diagnostics` 测试

### 5.4 不靠单条 query 下结论

- 至少使用一组固定 query 样本
- 每一轮变更都要做前后对比记录

---

## 6. 当前建议立刻执行的动作

### 6.1 先做样本集

新增一份 retrieval 样本文档，至少覆盖：

- 编号 / 文号类 query
- 缩写 / 术语类 query
- 故障排查类 query
- 解释 / 总结类 query
- SOP / WI 条款定位类 query

每条样本记录：

- query
- 期望文档
- 期望 chunk 或条款
- 是否允许 supplemental
- 当前表现
- 调整后表现

### 6.2 先跑 Phase 1，不先碰 chunk

原因：

- 当前 supplemental 内部真源已经具备
- 这是最轻的一刀
- 它不会触发入库重建

### 6.3 chunk 作为下一阶段单独立项

等 Phase 1 结束后，再单独开一轮：

- 通用 chunk 参数优化
- 结构化 chunk 规则优化
- 重建代表性文档索引
- 对比 top chunk / citation 质量

---

## 7. 最终目标

检索优化的最终目标不是让某一条 query “看起来更聪明”，而是让系统在下面三件事上更稳定：

- 该只看本部门时，别乱补
- 该补充跨部门证据时，能补得及时
- 命中的证据块足够精确，能直接支撑回答和 SOP 生成

如果按这份顺序推进，chunk 会出现在正确的位置：

- 不是第一刀
- 但会是下一阶段最重要的一刀之一
