# Enterprise-grade_RAG Agent Guide

本仓库使用一套“最小可用”的本地 coding agent workflow。

目标只有三件事：

- 先读代码和现有文档，再行动。
- 复杂改动先做 `/plan` 和 spec，再编码。
- 改完后按 `/review` 思路自检，并明确说明：
  - 改了什么
  - 验证了什么
  - 还有什么风险

这套 workflow 只保留 ECC 里最核心的 `/plan` 与 `/code-review` 思路，并结合本仓库实际结构重写。**不引入复杂 hooks、MCP、memory、security scanning 体系。**

## 1. 以哪些文件为准

优先级从高到低：

1. `MAIN_CONTRACT_MATRIX.md`
2. `RETRIEVAL_OPTIMIZATION_PLAN.md`
3. `RETRIEVAL_OPTIMIZATION_BACKLOG.md`
4. `.agent/rules/coding-rules.md`
5. `.agent/context/repo-map.md`

如果 `.agent/` 下的模板和其他上游目录写法不一致，以本文件和 `.agent/` 为准，不要照搬外部 workflow 结构。

## 2. 默认工作方式

### 简单改动

适用场景：

- 单文件或少量文件的小修复
- 明确局部行为修正
- 文档更新
- 不涉及契约、核心 retrieval、chunk、rerank、ingestion、auth 边界

默认做法：

1. 先读相关代码和文档。
2. 直接做最小必要改动。
3. 运行最小但真实的验证。
4. 输出变更、验证和风险。

### 复杂改动

满足以下任一情况，默认先 `/plan`，并先写 spec：

- 涉及稳定主契约或可能改动稳定字段语义
- 涉及 `retrieval / chat / system-config / ingestion / auth / scope` 核心链路
- 涉及 chunk、rerank、router、hybrid、supplemental 判定
- 横跨后端、前端、worker、脚本或评估体系
- 需要数据重建、backfill、迁移或回滚预案
- 容易引发“实现 / 测试 / 文档”三者不一致

spec 只保留两种模板：

- `.agent/specs/feature-template.md`
- `.agent/specs/bug-template.md`

不强制引入额外 spec 子目录结构；只要本轮任务先写出完整 spec 内容即可。

## 3. 本仓库硬约束

- `MAIN_CONTRACT_MATRIX.md` 是硬约束。
- 不要擅自扩稳定主契约，不要改稳定字段语义，尤其是：
  - `POST /api/v1/retrieval/search`
  - `POST /api/v1/chat/ask`
  - `GET /api/v1/system-config`
  - `PUT /api/v1/system-config`
- 如果改动可能碰到 contract，先核对 `MAIN_CONTRACT_MATRIX.md`，再行动。
- 如果发现实现、测试、文档三者不一致，要明确指出具体不一致点。
- 不允许大规模无关重构。
- 不要顺手清理无关 warning、搬动无关模块或改命名风格。

## 4. Retrieval 专项约束

默认遵守下面这条顺序：

1. 先评估样本与 baseline
2. 再做 supplemental 阈值校准
3. 再做 chunk 优化
4. 再碰 router / hybrid
5. 最后才动 rerank 默认路由

与 retrieval 优化相关时，默认先看：

- `eval/README.md`
- `eval/retrieval_samples.yaml`
- `scripts/eval_retrieval.py`
- `eval/results/` 下最新结果

额外 guardrails：

- 在样本仍是 `draft`、`synthetic`、`placeholder` 时，不要直接进入 Phase 1B 阈值调优。
- 如果评估结果几乎全 0，先检查：
  - `expected_doc_ids` 是否和真实索引一致
  - 样本是否还是 synthetic placeholder
  - 是样本集问题还是检索逻辑问题
- 不要把启发式字段当成 ground truth。
- 不要把 placeholder baseline 说成真实运行时快照。
- `retrieval / chat / SOP` 默认保持同一套 retrieval 判定逻辑，不要临时分叉。

## 5. 命令与模板

- `/plan` 规则：`.agent/commands/plan.md`
- `/review` 规则：`.agent/commands/review.md`
- feature spec 模板：`.agent/specs/feature-template.md`
- bug spec 模板：`.agent/specs/bug-template.md`
- 仓库结构地图：`.agent/context/repo-map.md`
- 编码规则：`.agent/rules/coding-rules.md`

## 6. 交付要求

任何非纯文档改动，交付时都必须说清楚：

- 改了什么
- 验证了什么
- 还有什么风险或缺口

如果只是文档修改，要明确说明：

- 这次是文档改动
- 没有跑代码测试

如果没有完成某部分验证，也必须直接说明原因，不要把“未验证”写成“已通过”。
