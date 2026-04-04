# Feature Spec Template

> 用于复杂功能、跨模块改动或高风险流程变更。  
> 简单单点修复不必强行套用。  
> 目标是让实现前先把“现状、方案、验证、风险”写清楚，而不是把上游 spec workflow 原样搬进仓库。

# Feature: [功能名称]

## 1. 背景

- 业务目标：
- 当前痛点：
- 为什么现在要做：

## 2. 本次范围

### In Scope

- 

### Out of Scope

- 

## 3. 必读文件

- [ ] `MAIN_CONTRACT_MATRIX.md`
- [ ] `RETRIEVAL_OPTIMIZATION_PLAN.md`
- [ ] `RETRIEVAL_OPTIMIZATION_BACKLOG.md`
- [ ] `.agent/context/repo-map.md`
- [ ] 相关实现文件：
- [ ] 相关测试文件：
- [ ] 相关 runbook / eval 文档：

## 4. 当前现状与证据

### 当前行为

- 

### 现有代码落点

- `path/to/file`：
- `path/to/file`：

### 可复用实现

- 

### 当前缺口

- 

## 5. 契约与兼容性检查

- [ ] 不涉及稳定主契约
- [ ] 涉及稳定主契约，已明确受影响字段 / 语义
- [ ] 需要同步更新主契约测试
- [ ] 需要同步更新前端 API 类型 / client
- [ ] 需要同步更新文档 / runbook

如果涉及稳定接口，明确写出：

- 受影响接口：
- 受影响字段：
- 兼容策略：

## 6. 方案设计

### 后端

- endpoint：
- schema：
- service：
- db / config / worker：

### 前端

- 页面 / panel：
- API client / types：
- 权限 / 路由：

### 数据 / 脚本 / 运维

- 是否需要 backfill：
- 是否需要 rebuild：
- 是否需要新增或调整脚本：

## 7. Retrieval 专项补充

如果本次功能与 retrieval 相关，必须补完：

- 当前样本状态：
  - [ ] verified 样本足够
  - [ ] 仍有 `draft / synthetic / placeholder`
- baseline 状态：
  - [ ] 真实可复跑
  - [ ] 仍有 placeholder / 结构模板成分
- 本次变更所属阶段：
  - [ ] supplemental 阈值
  - [ ] chunk
  - [ ] router / hybrid
  - [ ] rerank
- 是否符合既定优先级顺序：

如果样本或 baseline 不成熟，要直接写清楚缺口，不要把缺口留到编码阶段再解释。

## 8. 影响文件

- `path/to/file`
- `path/to/file`
- `path/to/file`

## 9. 实施步骤

要求：

- 每一步尽量控制在少量相关文件内
- 每一步都能单独验证
- 不做无关重构

1. 步骤 1
   - 文件：
   - 动作：
   - 为什么：
   - 验证：

2. 步骤 2
   - 文件：
   - 动作：
   - 为什么：
   - 验证：

3. 步骤 3
   - 文件：
   - 动作：
   - 为什么：
   - 验证：

## 10. 验证计划

### 自动化验证

- 后端：
- 前端：
- smoke：
- eval：

### 手工验证

- 

### 不验证的部分

- 

## 11. 风险与回滚

### 主要风险

- 

### 回滚方案

- 

### 监控点

- 

## 12. 交付要求

实现完成后，结论必须包含：

- 改了什么
- 验证了什么
- 还有什么风险或缺口
