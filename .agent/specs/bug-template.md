# Bug: [Bug 名称]

## 1. Report

### 症状

- 问题概述：
- 影响范围：
- 严重级别：`Critical / High / Medium / Low`
- 受影响角色 / 页面 / 接口：

### 复现信息

- 分支 / commit：
- 本地配置：
- 数据前提：

### 复现步骤

1. 
2. 
3. 

### 期望行为

- 

### 实际行为

- 

### 当前证据

```text
[日志 / 返回 / 截图说明]
```

## 2. Analyze

### 当前代码链路

- `path/to/file`：
- `path/to/file`：
- `path/to/file`：

### 相关测试

- 

### 已确认根因

- 

### 促成因素

- 

### 为什么之前没被发现

- 

### Retrieval / Eval 专项分析

- 样本是否 verified：
- baseline 是否真实：
- 问题属于样本、eval 脚本，还是 retrieval 逻辑：
- 是否涉及 baseline / supplemental / chunk / router / rerank 顺序误判：

## 3. Fix Plan

### 修复边界

#### In Scope

- 

#### Out of Scope

- 

### 契约检查

- [ ] 不涉及稳定主契约
- [ ] 涉及稳定主契约，已列出受影响字段 / 语义
- [ ] 需要同步更新测试 / frontend API / 文档

### 修复步骤

1. 
   - 文件：
   - 改动：
   - 为什么这是最小修复：

2. 
   - 文件：
   - 改动：
   - 为什么这是最小修复：

### 风险与回滚

- 修复风险：
- 回滚方案：

## 4. Verify

### 复现验证

- [ ] 修复前已确认能复现
- [ ] 修复后原始路径不再出现问题

### 回归验证

- 

### 自动化验证

- pytest：
- lint / build：
- smoke：
- eval：

### 无法验证的部分

- 

### 收尾输出

- [ ] 说明改了什么
- [ ] 说明验证了什么
- [ ] 说明风险是什么
