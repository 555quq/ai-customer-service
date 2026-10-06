# CI 说明

`ci-cd.yml` 是纯验证流水线，适用于 `main` 分支和来自 fork 的 Pull Request。它只申请 `contents: read` 权限，不读取部署 Secrets，不推送镜像，不连接生产服务器。

工作流包含 Python/pytest、pnpm/Vitest/TypeScript/构建、Compose 与应用镜像构建、Trivy、Gitleaks 和公开仓库内容门禁。

本地等价命令见根目录 `README.md` 的“验证”章节。`main` 应禁止 force push 和删除，并要求所有工作流通过后才能合并。
