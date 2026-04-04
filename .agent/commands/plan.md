# `/plan`

用于复杂改动的实现规划命令。

这份命令只保留 ECC 的核心思路：

- 先重述需求
- 先读代码和现有文档
- 先评估风险和影响面
- 复杂改动先写 spec
- plan 完成后再进入编码
- 未确认前禁止改代码

## 1. 什么时候必须先 `/plan`

满足以下任一条件时，不要直接写代码：

- 新功能或明显的新流程
- 可能触碰稳定主契约
- 改 `retrieval / chat / system-config / ingestion / auth / scope`
- 改 chunk、rerank、router、hybrid、supplemental 判定
- 横跨前后端、worker、脚本或评估体系
- 需要数据迁移、backfill、重建、回滚预案

简单单点修复可直接实现，但仍要先读相关代码。

## 2. 默认读取顺序

1. `MAIN_CONTRACT_MATRIX.md`
2. `RETRIEVAL_OPTIMIZATION_PLAN.md`
3. `RETRIEVAL_OPTIMIZATION_BACKLOG.md`
4. `.agent/context/repo-map.md`
5. 相关实现文件
6. 相关测试文件

如果任务与 retrieval 优化相关，再补读：

- `eval/README.md`
- `eval/retrieval_samples.yaml`
- `scripts/eval_retrieval.py`
- `eval/results/` 最新结果

## 3. `/plan` 的输出要求

先给“基于现有代码的计划”，不要写成泛化提纲。

输出里至少包含：

### 目标

- 要解决什么问题
- 不解决什么问题

### 现状与证据

- 当前链路在哪里
- 相关文件有哪些
- 已有实现能复用什么

### 约束检查

- 是否触碰稳定契约
- 是否影响 retrieval 顺序约束
- 是否需要样本、baseline、重建或回滚

### 影响文件

- 明确列出将修改的文件
- 如果还不确定，要先写“待确认”

### 方案

- 后端怎么改
- 前端怎么改
- 配置 / 数据 / 脚本怎么改
- 哪些地方坚持最小必要改动

### 原子步骤

每一步都应可单独验证，并尽量控制在少量相关文件内。

### 验证计划

- 单元测试
- 集成测试
- smoke
- eval
- 手工验证

### 风险与回滚

- 哪些地方最容易引发行为回归
- 如果效果不对，怎么回退

### 确认门槛

- 计划输出后，默认等待用户确认
- **在用户明确确认前，不进入代码修改阶段**

## 4. 复杂改动必须先写 spec

如果属于复杂改动，在 plan 里直接说明使用哪种模板：

- feature：`.agent/specs/feature-template.md`
- bug：`.agent/specs/bug-template.md`

spec 不要求套上游多阶段目录，但至少要把下面几点写清楚：

- 现状
- 目标
- 受影响文件
- 契约影响
- 实施步骤
- 验证
- 风险

## 5. Retrieval 专项规划要求

如果计划涉及 retrieval 优化，必须额外回答：

- 当前样本是否已有 verified 样本
- baseline 是否真实可用，还是 placeholder
- 这次改动属于：
  - supplemental 阈值
  - chunk
  - router / hybrid
  - rerank
- 是否符合既定优先级顺序

如果样本仍不成熟，要把“缺口”写进计划，而不是直接开始阈值调优。

## 6. 推荐输出模板

```markdown
# Plan: [任务名]

## 目标
- 

## 当前结论
- 为什么需要先 plan：
- 当前不直接写代码的原因：

## 现状与证据
- 文件：
- 现有行为：
- 可复用实现：

## 约束检查
- [ ] 涉及稳定契约
- [ ] 涉及 retrieval 优化顺序
- [ ] 需要数据重建 / backfill / 回滚

## 方案
- 后端：
- 前端：
- 配置 / 数据：

## 影响文件
- `path/to/file`

## 原子步骤
1. 
2. 
3. 

## 验证计划
- 

## 风险与回滚
- 风险：
- 回滚：

## Spec
- [ ] 不需要完整 spec，可直接做最小改动
- [ ] 需要 feature spec
- [ ] 需要 bug spec

## 待确认
- [ ] 用户已确认可以按此计划推进
```
