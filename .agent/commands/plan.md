# `/plan`

用于中大改动的实现规划。

## 1. 使用原则

满足以下任一条件时，必须先 `/plan`，未确认前禁止改代码：

- 新功能或明显新流程
- 多文件联动
- 影响稳定契约
- 影响 `retrieval / chat / system-config / ingestion / auth`
- 影响 chunk / rerank / router / hybrid / supplemental
- 需要 backfill / rebuild / rollback

## 2. 输出要求

### 重述目标

- 这次要解决什么问题
- 这次不解决什么问题

### 涉及文件

- 明确列出准备修改的文件
- 如果不确定，先写待确认

### 修改步骤

1. 
2. 
3. 

### 风险点

- 行为回归风险
- 契约兼容风险
- 数据 / 重建 / 回滚风险

### 验证计划

- pytest：
- lint / build：
- smoke：
- eval：
- 手工验证：

## 3. 强约束

- plan 输出后默认等待确认
- 未确认前禁止改代码
- 命中 `AGENTS.md` 中的 `Auto Enforcement` / 自动触发规则时，不得跳过 `/plan`
- retrieval 改动必须说明当前处于：
  - baseline
  - supplemental
  - chunk
  - router
  - rerank
  中的哪一层
- 如果样本或 baseline 不成熟，必须先写缺口，不能跳过
