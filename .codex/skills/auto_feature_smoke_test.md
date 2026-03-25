这个文件不是 Codex 可发现的 skill。

真正可触发的版本在：

- `.codex/skills/auto-feature-smoke-test/SKILL.md`

原因：

- Codex skill 需要使用“技能目录 + `SKILL.md`”结构
- `SKILL.md` 必须包含 YAML frontmatter，其中至少有 `name` 和 `description`
- 仅放一个普通 `.md` 文件不会被当成 skill 自动加载

如果你的目标是“每完成一个功能就先跑 API + Chrome MCP 冒烟测试”，请维护上面的 `SKILL.md`，不要继续改这个文件。
