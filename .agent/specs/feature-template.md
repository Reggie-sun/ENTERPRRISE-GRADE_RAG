# Feature Spec Template

> 用于复杂功能、跨模块改动或高风险流程变更。  
> 结构固定为 `Requirements / Design / Tasks / Implementation Checklist`，避免继续扩成多阶段上游 spec 框架。

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
- [ ] 相关 runbook / eval 文档：

### 需求清单

1. [需求 1]
2. [需求 2]
3. [需求 3]

### 兼容性与契约

- [ ] 不涉及稳定主契约
- [ ] 涉及稳定主契约，已明确受影响接口 / 字段 / 语义
- [ ] 需要同步更新主契约测试
- [ ] 需要同步更新前端 API 类型 / client
- [ ] 需要同步更新文档 / runbook

如果涉及稳定接口，明确写出：

- 受影响接口：
- 受影响字段：
- 兼容策略：

## 2. Design

### 当前现状与证据

- 当前行为：
- 现有代码落点：
  - `path/to/file`：
  - `path/to/file`：
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

#### 数据 / 脚本 / 运维

- 是否需要 backfill：
- 是否需要 rebuild：
- 是否需要新增或调整脚本：

### Retrieval 专项设计

如果功能与 retrieval 相关，必须补完：

- 当前样本状态：
  - [ ] verified 样本足够
  - [ ] 仍有 `draft / synthetic / placeholder`
- baseline 状态：
  - [ ] 真实可复跑
  - [ ] 仍有 placeholder / 模板成分
- 本次变更所属阶段：
  - [ ] supplemental 阈值
  - [ ] chunk
  - [ ] router / hybrid
  - [ ] rerank
- 是否符合既定优先级顺序：

## 3. Tasks

### 影响文件

- `path/to/file`
- `path/to/file`
- `path/to/file`

### 任务拆分

1. 任务 1
   - 文件：
   - 动作：
   - 为什么：
   - 验证：

2. 任务 2
   - 文件：
   - 动作：
   - 为什么：
   - 验证：

3. 任务 3
   - 文件：
   - 动作：
   - 为什么：
   - 验证：

## 4. Implementation Checklist

### 编码前

- [ ] 需求和设计已确认
- [ ] 影响文件已明确
- [ ] 契约影响已确认

### 编码中

- [ ] 只做最小必要改动
- [ ] 不跨模块乱改
- [ ] 不做无关重构

### 验证

- [ ] 后端针对性测试
- [ ] 前端 lint / build
- [ ] smoke（如适用）
- [ ] eval（如适用）
- [ ] 手工验证（如适用）

### 风险与回滚

- 主要风险：
- 回滚方案：
- 监控点：

### 交付要求

- [ ] 结论写清楚改了什么
- [ ] 结论写清楚验证了什么
- [ ] 结论写清楚还有什么风险或缺口
