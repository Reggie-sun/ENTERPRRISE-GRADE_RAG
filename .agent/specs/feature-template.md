# Feature: [功能名称]

## 1. Requirements

### 背景

- 业务目标：
- 当前痛点：
- 为什么现在做：

### 范围

#### In Scope

- 

#### Out of Scope

- 

### 必读文件

- [ ] `MAIN_CONTRACT_MATRIX.md`
- [ ] `RETRIEVAL_OPTIMIZATION_PLAN.md`
- [ ] `RETRIEVAL_OPTIMIZATION_BACKLOG.md`
- [ ] `.agent/context/repo-map.md`
- [ ] 相关实现文件：
- [ ] 相关测试文件：
- [ ] 相关 eval / runbook：

### 需求清单

1. 
2. 
3. 

### 契约检查

- [ ] 不涉及稳定主契约
- [ ] 涉及稳定主契约，已明确受影响接口 / 字段 / 语义
- [ ] 需要同步更新测试
- [ ] 需要同步更新 frontend API

## 2. Design

### 当前现状与证据

- 当前行为：
- 现有代码落点：
- 可复用实现：
- 当前缺口：

### 设计方案

#### 后端

- endpoint：
- schema：
- service：
- db / config / worker：

#### 前端

- 页面 / panel：
- API client / types：
- 权限 / 路由：

#### 数据 / 运维

- 是否需要 backfill：
- 是否需要 rebuild：
- 是否需要新增或调整脚本：

### Retrieval 专项设计

- 当前样本状态：
  - [ ] verified 样本足够
  - [ ] 仍有 `draft / synthetic / placeholder`
- baseline 状态：
  - [ ] 真实可复跑
  - [ ] 仍有 placeholder
- 本次变更属于：
  - [ ] baseline
  - [ ] supplemental
  - [ ] chunk
  - [ ] router
  - [ ] rerank
- 是否符合既定优先级顺序：

## 3. Tasks

### 影响文件

- `path/to/file`
- `path/to/file`
- `path/to/file`

### 任务拆分

1. 
   - 文件：
   - 动作：
   - 验证：

2. 
   - 文件：
   - 动作：
   - 验证：

3. 
   - 文件：
   - 动作：
   - 验证：

## 4. Implementation Checklist

### 编码前

- [ ] requirements 已确认
- [ ] design 已确认
- [ ] 影响文件已确认
- [ ] 契约影响已确认

### 编码中

- [ ] 只做最小必要改动
- [ ] 不做无关重构
- [ ] 不跨模块乱改

### 验证

- [ ] pytest
- [ ] lint / build
- [ ] smoke
- [ ] eval
- [ ] 手工验证

### 风险与回滚

- 主要风险：
- 回滚方案：
- 监控点：

### 交付要求

- [ ] 说明改了什么
- [ ] 说明验证了什么
- [ ] 说明风险是什么
