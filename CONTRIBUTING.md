# Contributing to KernelLens

欢迎提交问题、文档改进和代码贡献。

## 环境与检查

需要 **Node.js 20+** 和 **pnpm**。

```bash
pnpm install
pnpm lint          # Biome 代码规范
pnpm typecheck     # TypeScript 类型检查
pnpm test          # 单元测试
pnpm build         # 构建
```

或一次性运行全部检查：

```bash
pnpm ci
```

实际使用 Agent 时，将 `.env.example` 复制为 `.env`，填写自己的 API 配置。

## 提交改动

1. 从 `main` 创建功能分支，一次 PR 解决一个明确问题。
2. 修改相关实现和使用说明，附上最小复现输入、预期行为和实际结果。
3. 运行 `pnpm ci` 确保通过。
4. PR 说明验证命令及未验证的范围。

提交前用 `git diff --cached --stat`、`git diff --cached` 核对实际上传内容。`.gitignore` 不会清除已提交的历史内容。
