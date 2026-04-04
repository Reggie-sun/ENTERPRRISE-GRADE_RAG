# .agent Workflow Root

`.agent/` 是本仓库唯一的 coding agent workflow 主线。

这里的职责固定为：

- `commands/`
  - 只放 workflow 命令定义：
    - `/plan`
    - `/review`
- `specs/`
  - 只放本仓库使用的 spec 模板：
    - feature
    - bug
- `rules/`
  - 只放项目级硬约束
- `context/`
  - 只放项目上下文，例如 repo map

优先级说明：

1. `AGENTS.md`
2. `.agent/rules/coding-rules.md`
3. `.agent/context/repo-map.md`
4. `.agent/commands/*.md`
5. `.agent/specs/*.md`

其他目录的定位：

- `.claude/`
  - 只保留本地运行时配置，不再承载独立 workflow 主线
- `.codex/`
  - 只保留工具配置、MCP 启动脚本、正式 skill，不再承载项目规则主线

如果后续发现 `.claude/`、`.codex/` 与 `.agent/` 内容重复或冲突，默认继续收口到 `.agent/`，而不是新增第三套规则。
