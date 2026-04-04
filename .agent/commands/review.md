# `/review`

用于代码审查和变更评审。

## 1. 审查动作

必须完成：

1. diff 检查
2. 全文件回读
3. 调用链回读
4. schema / API / 边界检查
5. 测试与验证检查

命中 `AGENTS.md` 中的 `Auto Enforcement` / 自动触发规则时，不得跳过 `/review`。

## 2. 审查重点

### schema / API / 边界

- endpoint、schema、service 是否一致
- 稳定字段或稳定语义是否被破坏
- frontend `api/types.ts` / `api/client.ts` 是否同步
- 错误路径和边界条件是否仍成立

### retrieval / RAG

- `retrieval / chat / SOP` 是否仍共用同一套 retrieval 主逻辑
- 是否跳过了 baseline / samples / backlog
- chunk / ingestion 改动是否破坏 retrieval
- rerank 是否被过早改动

### 范围控制

- 是否混入无关重构
- 是否跨模块乱改
- 是否引入新的隐性规则源

### 验证

- 是否有针对性验证
- 是否缺少关键回归测试
- smoke / eval 是否应该补跑却没跑

## 3. 问题分类

- `[阻塞]`
  - 会造成错误行为、契约破坏、严重回归
- `[重要]`
  - 非阻塞，但应在合并前修正

## 4. 输出格式

```md
## 发现的问题

1. [阻塞] 标题
   - 位置：
   - 原因：
   - 影响：
   - 建议：

2. [重要] 标题
   - 位置：
   - 原因：
   - 影响：
   - 建议：

## 结论

- diff 检查：已完成
- 全文件回读：已完成 / 部分完成
- 结论：通过 / 需修改 / 阻塞
- 残余风险：
- 测试缺口：
```

如果没有发现明确问题，也必须输出结论。
