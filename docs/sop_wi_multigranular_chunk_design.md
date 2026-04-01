# SOP / WI 文档多粒度 Chunk 设计方案

日期：2026-04-01

适用对象：

- SOP
- WI
- 设备操作规范
- 设备保养规范
- 检验规范
- 安全操作规范

本文是面向当前仓库实现的升级设计，不是泛化讨论。当前代码里的主切块器仍是固定字符切分，见 [backend/app/rag/chunkers/text_chunker.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/chunkers/text_chunker.py)；本文目标是把这类强结构化文档升级为“结构化多粒度 chunk + 检索适配”的方案。

## 1. 结论

你的方向是对的，而且很适合这类文档做 RAG。

对于 SOP / WI / 安全规范，单一粒度切块几乎一定会出现下面的问题：

- 整篇一个 chunk：文档级问题能答，但条款级问题不准。
- 全部按固定 token 切块：条款会被切断，引用不稳定。
- 全部只按条款切：细节问题很准，但“这份文件主要讲什么”这类问题召回不稳。

因此，这类文档最合适的做法就是：

1. 同一份文档生成多类 chunk。
2. 检索时按问题类型做轻量路由。
3. 命中细粒度条款后，再回补父章节摘要和文档摘要。

如果只做“多粒度 chunk”而不做“检索路由 + 结构回溯”，效果会比单一粒度好，但还不够稳。

## 2. 设计目标

系统需要同时稳定支持四类问题：

### 2.1 文档级问题

例如：

- “摇臂钻床安全操作规范是什么？”
- “这份 SOP 主要讲什么？”
- “给我总结一下 WI-SJ-052”

### 2.2 章节级问题

例如：

- “这份文档的职责部分讲了什么？”
- “作业前检查要求有哪些？”
- “异常处理怎么规定的？”

### 2.3 条款级问题

例如：

- “铁屑怎么清理？”
- “能不能手拿工件钻孔？”
- “4.17 说了什么？”

### 2.4 元数据问题

例如：

- “WI-SJ-052 的版本号是什么？”
- “这份规范什么时候生效？”

## 3. 总体原则

### 3.1 不采用单一粒度 chunk

禁止只使用以下任一单一方案：

- 整篇文档一个 chunk
- 所有内容全部按固定 token 长度切块
- 仅按条款切分但没有摘要块

原因不是“理论上不好”，而是这会直接影响线上稳定性：

- 文档级问题无法稳定召回整体信息
- 章节级问题容易只召回局部细节
- 条款级问题容易被大块无关文本稀释
- rerank 很难区分“整体问法”和“细节问法”
- LLM 上下文被低相关长文本浪费

### 3.2 同一文档生成多类 chunk

每份 SOP / WI 文档至少生成以下三类 chunk：

- `doc_summary`
- `section_summary`
- `clause`

建议补充一类可选低权重块：

- `metadata`

其中：

- `doc_summary` 负责回答整份文档讲什么
- `section_summary` 负责回答某一章节或主题范围讲什么
- `clause` 负责回答具体要求、禁令、步骤、条件、例外、异常处理
- `metadata` 负责回答版本号、生效日期、文件编号等显式元数据

### 3.3 保留结构信息

每个 chunk 都必须保留足够的结构语义，至少包括：

- 文档标题
- 文件编号
- 版本号
- 生效日期
- 章节号
- 条款号
- 父子关系
- chunk 类型

这样做的目的是：

- 支持精确引用
- 支持“先命中条款，再回溯父章节”
- 支持 chunk_type 过滤和融合
- 支持答案引用定位
- 支持后续做权限、文档版本和可见性治理

### 3.4 摘要块和原文块分离

摘要块不应直接替代原文块。

推荐做法是：

- `doc_summary`、`section_summary` 用于召回“范围”和“主题”
- `clause` 用于提供最终事实依据和引用原文

换句话说，摘要块负责“找到方向”，原文块负责“落到证据”。

### 3.5 对修订页、目录页、页眉页脚做降权处理

像“修订页”“版本记录”“页眉页脚”这类内容，不应与正文同权参与主检索。

推荐做法：

- 进入 `metadata` 或 `appendix` 低权重块
- 仅在元数据问题时参与检索
- 默认不进入主回答证据上下文

## 4. 推荐 Chunk 类型

## 4.1 `doc_summary`

用途：

- 回答整份文档的总体问题
- 在 clause 命中后，给 LLM 一个整体语境

建议内容来源：

- 规则抽取
- 可选 LLM 摘要生成

建议覆盖：

- 文档用途
- 适用范围
- 责任部门
- 操作规范主题概览
- 高风险行为概览
- 异常处理与停机收尾概览

示例：

```json
{
  "chunk_id": "WI-SJ-052::doc_summary",
  "doc_id": "WI-SJ-052",
  "doc_title": "摇臂钻床安全操作规范",
  "chunk_type": "doc_summary",
  "parent_id": null,
  "section": "ALL",
  "section_label": "整份文档摘要",
  "content": "本文件规定了摇臂钻床的安全操作要求，适用于公司摇臂钻设备的操作与安全管理，内容包括作业前检查、防护穿戴、工件装夹、钻削进给、清屑、异常处理、停机收尾和运行保养记录等要求。",
  "keywords": ["摇臂钻床", "安全操作", "作业前检查", "装夹", "清屑", "异常处理", "停机收尾"],
  "version": "A/0",
  "effective_date": "2022-12-05",
  "is_generated_summary": true
}
```

## 4.2 `section_summary`

用途：

- 回答局部主题问题
- 给条款级检索提供语义锚点
- 在文档较长时避免直接把大量条款全塞给模型

推荐拆法：

不要机械地每个一级标题一个 summary，而是按“用户会怎么问”来分组。

对于 SOP / WI 文档，通常推荐按语义章节拆：

- 目的 / 适用范围 / 职责
- 作业前准备
- 加工作业要求
- 禁令和工具要求
- 异常、停机和保养

示例：

```json
{
  "chunk_id": "WI-SJ-052::section_summary::machining_operation",
  "doc_id": "WI-SJ-052",
  "doc_title": "摇臂钻床安全操作规范",
  "chunk_type": "section_summary",
  "parent_id": "WI-SJ-052::doc_summary",
  "section": "4.5-4.18",
  "section_label": "加工作业要求",
  "content": "本部分规定了钻削过程中的进给控制、工件装夹、摇臂与主轴箱夹紧、钻头及锥面要求、钻透孔操作、装卸工件、清屑、异常响声处理、攻螺纹、变速与停车要求等内容。",
  "keywords": ["钻削", "进给", "装夹", "清屑", "攻螺纹", "变速", "停车"],
  "is_generated_summary": true
}
```

## 4.3 `clause`

用途：

- 回答明确细节
- 作为最终引用和证据
- 支持条款号直接定位

粒度要求：

- 一条一块
- 不要把 `4.1 ~ 4.5` 合成一个条款块
- 对无编号但语义独立的“目的”“适用范围”也建议保留原子块

示例：

```json
{
  "chunk_id": "WI-SJ-052::clause::4.13",
  "doc_id": "WI-SJ-052",
  "doc_title": "摇臂钻床安全操作规范",
  "chunk_type": "clause",
  "parent_id": "WI-SJ-052::section_summary::chip_and_stop",
  "section": "4.13",
  "section_label": "清屑要求",
  "content": "钻孔时必须经常注意清除铁屑，钻头上有长屑时要停车清除，禁止用风吹手拉，要用刷子或铁钩清除。在扩孔时不得用偏刃钻具。",
  "keywords": ["铁屑", "长屑", "停车清除", "刷子", "铁钩", "扩孔"],
  "risk_level": "high"
}
```

## 4.4 `metadata`

用途：

- 回答文件编号、版本号、生效日期、标题等问题

建议：

- 可以入库
- 但默认检索权重应低于正文 chunk
- 最好主要参与 lexical / filter，不要让它在普通语义问答里压过正文

示例：

```json
{
  "chunk_id": "WI-SJ-052::metadata",
  "doc_id": "WI-SJ-052",
  "doc_title": "摇臂钻床安全操作规范",
  "chunk_type": "metadata",
  "parent_id": null,
  "section": "META",
  "section_label": "文档元数据",
  "content": "文件编号 WI-SJ-052，版本 A/0，生效日期 2022-12-05，文档名称为摇臂钻床安全操作规范。",
  "keywords": ["WI-SJ-052", "A/0", "2022-12-05", "文件编号", "版本号", "生效日期"]
}
```

## 5. 推荐 JSON 结构

下面这套结构已经可以直接支撑企业 RAG 的主流程。

## 5.1 通用字段

```json
{
  "chunk_id": "唯一 chunk 编号",
  "doc_id": "文件编号，如 WI-SJ-052",
  "doc_title": "文档标题",
  "chunk_type": "doc_summary | section_summary | clause | metadata",
  "parent_id": "父级 chunk id，没有则为 null",
  "section": "章节号或范围",
  "section_label": "章节语义标签",
  "content": "chunk 正文",
  "keywords": ["关键词1", "关键词2"],
  "version": "A/0",
  "effective_date": "2022-12-05",
  "page_no": null,
  "source_file_name": "原始文件名",
  "department_scope": "global 或具体部门",
  "visibility": "internal",
  "risk_level": "low | medium | high"
}
```

说明：

- `page_no` 对 PDF OCR 往往有意义，但对 DOCX 往往不可靠，因此应允许为 `null`
- `risk_level` 很适合安全规范类文档，后续可给 rerank 和答案模板提供先验

## 5.2 建议增加的检索辅助字段

```json
{
  "retrieval_text": "用于 embedding / BM25 的拼接文本",
  "display_text": "用于最终展示与引用的原文",
  "summary_text": "可选，简短概述",
  "section_path": ["内容", "4.13"],
  "clause_no": "4.13",
  "clause_no_normalized": "4.13",
  "is_generated_summary": true
}
```

其中：

- `retrieval_text` 负责提升召回稳定性
- `display_text` 保留原文，避免摘要内容直接充当引用
- `section_path` 方便父子回溯和前端展示
- `clause_no_normalized` 方便处理 `4.17`、`4 17`、`第4.17条` 这类变体

## 5.3 `retrieval_text` 推荐拼法

不要只把原文拿去做 embedding。

推荐拼接：

- 标题
- 文件编号
- chunk 类型
- 章节号
- 章节语义标签
- 关键词
- 正文

例如：

```text
摇臂钻床安全操作规范 WI-SJ-052 clause 4.13 清屑要求 铁屑 长屑 停车清除 刷子 铁钩
钻孔时必须经常注意清除铁屑，钻头上有长屑时要停车清除，禁止用风吹手拉，要用刷子或铁钩清除。在扩孔时不得用偏刃钻具。
```

这样做通常比“只塞正文”更稳定，尤其对以下问题更明显：

- 按条款号查找
- 按主题短语查找
- 用户只记得文档编号或规范名称

## 6. 对 WI-SJ-052 的实际拆分建议

我核对了原始 DOCX，正文结构如下：

- 文档标题：摇臂钻床安全操作规范
- 文件编号：WI-SJ-052
- 版本号：A/0
- 生效日期：2022-12-05
- 基础章节：目的、适用范围、职责
- 操作正文：`4.1 ~ 4.27`
- 附页：修订页

这个文档非常适合做“1 个文档摘要 + 6 个章节摘要 + 33 个原子条款块 + 1 个元数据块”。

## 6.1 推荐 chunk 清单

### A. `metadata`

1 个。

建议承接：

- 文件编号
- 版本号
- 生效日期
- 文档标题

### B. `doc_summary`

1 个。

### C. `section_summary`

建议 6 个。

1. `basic_info_summary`
   覆盖：目的、适用范围、职责 `3.1 ~ 3.4`

2. `pre_operation_summary`
   覆盖：`4.1 ~ 4.4`

3. `machining_and_clamping_summary`
   覆盖：`4.5 ~ 4.12`

4. `chip_and_stop_summary`
   覆盖：`4.13 ~ 4.18`

5. `prohibition_and_tool_summary`
   覆盖：`4.19 ~ 4.21`

6. `abnormal_shutdown_maintenance_summary`
   覆盖：`4.22 ~ 4.27`

### D. `clause`

建议 33 个原子块：

- 目的：1 个
- 适用范围：1 个
- 职责：`3.1 ~ 3.4` 共 4 个
- 内容：`4.1 ~ 4.27` 共 27 个

说明：

- 如果你坚持只把编号条款做原子块，那也至少要保留 `3.1 ~ 3.4` 和 `4.1 ~ 4.27`
- 但从问答体验看，“适用范围是什么”“目的是什么”出现频率很高，建议保留原子块

## 6.2 推荐 section_summary 示例

### `basic_info_summary`

```json
{
  "chunk_id": "WI-SJ-052::section_summary::basic_info",
  "doc_id": "WI-SJ-052",
  "chunk_type": "section_summary",
  "parent_id": "WI-SJ-052::doc_summary",
  "section": "purpose+scope+3.1-3.4",
  "section_label": "基础信息与职责",
  "content": "本部分说明了文件用于指导操作者正确操作和使用摇臂钻设备，适用于公司摇臂钻的操作与安全操作，并明确生产管理部、生产技术部、采购管理部和财务部分别承担设备保养维修确认、故障分析和维修方案、维修物料采购以及价格核查职责。"
}
```

### `pre_operation_summary`

```json
{
  "chunk_id": "WI-SJ-052::section_summary::pre_operation",
  "doc_id": "WI-SJ-052",
  "chunk_type": "section_summary",
  "parent_id": "WI-SJ-052::doc_summary",
  "section": "4.1-4.4",
  "section_label": "作业前准备与防护要求",
  "content": "本部分要求摇臂钻床由专人操作和保养，开机前检查电器、机械、工具和夹具状态，操作前规范穿戴紧身防护服，并确保摇臂回转范围内无障碍且在钻削前锁紧摇臂。"
}
```

### `abnormal_shutdown_maintenance_summary`

```json
{
  "chunk_id": "WI-SJ-052::section_summary::abnormal_shutdown_maintenance",
  "doc_id": "WI-SJ-052",
  "chunk_type": "section_summary",
  "parent_id": "WI-SJ-052::doc_summary",
  "section": "4.22-4.27",
  "section_label": "异常处理、停机和保养记录",
  "content": "本部分规定了设备异常时不得强行使用，应通知维修人员处理；发生事故要保持现场并上报；设备开动时不得离岗；工作结束后需卸下钻头、调整手柄位置、切断电源，并按规定停机清扫和做好运行保养记录。"
}
```

## 6.3 推荐 clause 示例

### `4.6`

```json
{
  "chunk_id": "WI-SJ-052::clause::4.6",
  "doc_id": "WI-SJ-052",
  "chunk_type": "clause",
  "parent_id": "WI-SJ-052::section_summary::machining_and_clamping",
  "section": "4.6",
  "section_label": "工件装夹要求",
  "content": "工具必须装夹牢固可靠，小件必须用夹具装夹钻孔，严禁手拿工件钻孔。",
  "keywords": ["装夹", "夹具", "小件", "手拿工件钻孔"],
  "risk_level": "high"
}
```

### `4.13`

```json
{
  "chunk_id": "WI-SJ-052::clause::4.13",
  "doc_id": "WI-SJ-052",
  "chunk_type": "clause",
  "parent_id": "WI-SJ-052::section_summary::chip_and_stop",
  "section": "4.13",
  "section_label": "清屑要求",
  "content": "钻孔时必须经常注意清除铁屑，钻头上有长屑时要停车清除，禁止用风吹手拉，要用刷子或铁钩清除。在扩孔时不得用偏刃钻具。",
  "keywords": ["铁屑", "长屑", "停车清除", "刷子", "铁钩", "扩孔"],
  "risk_level": "high"
}
```

### `4.17`

```json
{
  "chunk_id": "WI-SJ-052::clause::4.17",
  "doc_id": "WI-SJ-052",
  "chunk_type": "clause",
  "parent_id": "WI-SJ-052::section_summary::chip_and_stop",
  "section": "4.17",
  "section_label": "停车与反车要求",
  "content": "钻孔过程中钻头未退离工件前不得停车。严禁用手去停住转动着的钻头，反车时，必须等主轴停止后再开动。",
  "keywords": ["不得停车", "手停钻头", "反车", "主轴停止"],
  "risk_level": "high"
}
```

## 7. 检索策略建议

你最关心的问题是：

“用户问整份文档时，不要只掉到第一条。”

这个问题只靠改 chunk 粒度还不够，必须配一个轻量查询路由。

## 7.1 查询路由建议

建议把问题先粗分为 5 类：

- `doc_overview`
- `section_focus`
- `clause_lookup`
- `metadata_lookup`
- `mixed`

可用简单规则先落地，不必一开始就上模型分类。

### `doc_overview`

典型触发词：

- “是什么”
- “主要讲什么”
- “总结一下”
- “概述”
- “这份 SOP / WI”

召回优先级建议：

- `doc_summary`
- `section_summary`
- `clause`

推荐召回配额：

- `doc_summary`：1~2
- `section_summary`：2~4
- `clause`：1~2

### `section_focus`

典型触发词：

- “职责”
- “适用范围”
- “作业前”
- “异常处理”
- “停机”
- “保养”
- “哪一部分”

召回优先级建议：

- `section_summary`
- `clause`
- `doc_summary`

推荐召回配额：

- `section_summary`：2~4
- `clause`：2~5
- `doc_summary`：0~1

### `clause_lookup`

典型触发词：

- “4.17”
- “能不能”
- “是否可以”
- “怎么清理”
- “禁止”
- “必须”
- “钻透孔”
- “手拿工件”

召回优先级建议：

- `clause`
- `section_summary`
- `doc_summary`

推荐召回配额：

- `clause`：5~8
- `section_summary`：1~2
- `doc_summary`：0~1

### `metadata_lookup`

典型触发词：

- “文件编号”
- “版本号”
- “生效日期”
- “A/0”

召回优先级建议：

- `metadata`
- `doc_summary`

### `mixed`

没有明显信号时，做混合召回：

- `section_summary`
- `clause`
- `doc_summary`

## 7.2 结果融合建议

推荐按下面顺序融合，而不是把所有 chunk 混成一个池子直接比相似度：

1. 先按 query 类型决定各 chunk_type 的召回配额。
2. 各类型内部独立召回 topN。
3. 融合时加入 chunk_type 先验分。
4. rerank 时把 `chunk_type`、`section`、`risk_level` 一起喂进去。

建议加入一个简单的类型先验：

- `doc_overview` 时，提高 `doc_summary`、`section_summary` 的 prior
- `clause_lookup` 时，提高 `clause` 的 prior
- `metadata_lookup` 时，提高 `metadata` 的 prior

这一步很关键，因为单纯依赖 embedding 相似度，摘要块和条款块常常会互相干扰。

## 7.3 命中条款后的结构回溯

这是这个方案里最容易被漏掉、但价值很高的一步。

如果最终 top 结果命中了 `clause`，建议自动补回：

- 该 `clause` 的父 `section_summary`
- 该文档的 `doc_summary`

这样做有两个好处：

- 让模型知道这条规定属于哪个主题范围
- 避免模型只根据一条孤立条款做过度泛化

推荐回答上下文拼装顺序：

1. 最相关 `clause`
2. 对应 `section_summary`
3. 必要时补 1 个 `doc_summary`

## 7.4 避免“整份文档问题掉到第一条”的具体做法

当 query 被识别为 `doc_overview` 时：

1. 至少强制召回 1 个 `doc_summary`
2. 至少强制召回 2 个不同 section 的 `section_summary`
3. 对 `clause` 设置最大数量上限，避免细节条款淹没整体摘要
4. 生成答案时优先引用摘要块，再补充 1~2 条关键条款做例证

这比单纯提高 `doc_summary` 分数更稳。

## 8. 结合当前仓库的落地建议

当前代码链路大致是：

- 解析：`DocumentParser`
- 切块：`TextChunker`
- 入库：`DocumentIngestionService`
- 向量存储：`QdrantVectorStore`
- 查询路由：`RetrievalQueryRouter`
- 检索主流程：`RetrievalService`

相关文件：

- [backend/app/rag/chunkers/text_chunker.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/chunkers/text_chunker.py)
- [backend/app/services/ingestion_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/ingestion_service.py)
- [backend/app/services/retrieval_query_router.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/retrieval_query_router.py)
- [backend/app/services/retrieval_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/retrieval_service.py)
- [backend/app/rag/vectorstores/qdrant_store.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/rag/vectorstores/qdrant_store.py)

## 8.1 最小改造路径

推荐按下面顺序落地，不要一次重写：

### 第一步：新增结构化 chunker

保留现有 `TextChunker` 作为通用兜底。

新增一个面向 SOP / WI 的结构化 chunker，例如：

- `StructuredChunk`
- `SOPStructuredChunker`

职责：

- 识别标题、文件编号、版本号、生效日期
- 识别“目的 / 适用范围 / 职责 / 内容”
- 识别 `3.1`、`4.17` 这类条款号
- 生成 `metadata / doc_summary / section_summary / clause`

### 第二步：在入库阶段做文档类型判断

在 [backend/app/services/ingestion_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/ingestion_service.py) 里增加一层判定：

- 如果命中 SOP / WI 结构特征，则走结构化 chunking
- 否则继续走现有固定字符切块

可用的启发式信号：

- 文件名包含 `SOP`、`WI`
- 正文存在“目的 / 适用范围 / 职责 / 内容”
- 存在连续条款号 `3.1`、`4.1`、`4.2`、`4.3`

### 第三步：向量入库改为写 `retrieval_text`

当前 Qdrant payload 主体仍以 `text` 为中心。

升级时建议：

- embedding 输入使用 `retrieval_text`
- payload 同时保存 `display_text`
- payload 新增 `chunk_type`、`parent_id`、`section`、`section_label`、`keywords` 等字段

### 第四步：扩展查询路由

当前 [backend/app/services/retrieval_query_router.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/retrieval_query_router.py) 主要解决的是：

- `exact`
- `semantic`
- `mixed`

它更像“词法召回权重路由”，还不是“chunk 粒度路由”。

建议额外增加一层粒度意图分类，例如：

- `granularity = doc_overview | section_focus | clause_lookup | metadata_lookup | mixed`

然后由 `RetrievalService` 根据该粒度决定各 chunk_type 的召回配额和 prior。

### 第五步：结果后处理做结构回补

在 [backend/app/services/retrieval_service.py](/home/reggie/vscode_folder/Enterprise-grade_RAG/backend/app/services/retrieval_service.py) 的候选融合后加一步：

- 如果前几名命中 `clause`
- 自动补拉 `parent_id` 对应的 `section_summary`
- 必要时补拉 `doc_summary`

这一步可以不重新向量检索，直接按 `chunk_id` / `parent_id` 回取 payload。

## 8.2 对当前实现的一个关键提醒

如果继续沿用固定字符切块，即使你给 rerank 再多规则，效果也会受上限约束。

原因很简单：

- 现有 `TextChunker` 不知道什么是 `4.13`
- 不知道什么是“职责”
- 不知道某条内容是不是禁令
- 也不知道某块文本属于哪个父章节

所以这个方案的核心不是“多存几类摘要”，而是“先恢复文档结构，再把结构带进检索链路”。

## 9. 验收标准

方案落地后，至少要用下面几类问题做回归：

### 文档级

- “摇臂钻床安全操作规范是什么？”
- “WI-SJ-052 主要讲什么？”

期望：

- `doc_summary` 稳定进入前列
- 返回答案覆盖用途、范围、主题，而不是只返回某一条规定

### 章节级

- “职责部分讲了什么？”
- “作业前检查要求有哪些？”

期望：

- `section_summary` 进入前列
- 能列出对应条款作为支撑

### 条款级

- “铁屑怎么清理？”
- “可以手拿工件钻孔吗？”
- “4.17 说了什么？”

期望：

- 对应 `clause` 命中前列
- 返回答案引用原文，不要泛化

### 元数据级

- “这份文件版本号是什么？”
- “这份规范什么时候生效？”

期望：

- `metadata` 直达命中
- 不被正文噪声压制

## 10. 最终建议

如果你的目标是给这类文档做 RAG，这套方案是正确方向，而且应该作为标准方案推进。

最重要的不是再去调 `chunk_size`，而是把下面三件事一起落地：

1. 结构化多粒度 chunk
2. 基于问题类型的轻量检索路由
3. 命中细粒度条款后的父级结构回溯

用一句话概括：

对 SOP / WI 文档，最优解不是“切得更巧”，而是“把文档结构显式建模，再按问题粒度检索”。
