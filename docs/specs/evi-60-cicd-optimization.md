# EVI-60 — ragrig CI/CD 优化

## 目标

重构 CI/CD pipeline，将现有重复的 baseline/checks 双 job 拆分为职责清晰的独立 job，补齐 pytest markers、DB migration CI 测试、Docker build 验证。

## 验证方式（hard requirements）

1. **CI workflow 重构**：`.github/workflows/ci.yml` 包含以下独立 job：`lint`、`test`（Python 3.11/3.12 matrix）、`coverage`、`db-smoke`、`web-smoke`、`docker-build`、`supply-chain`。删除当前重复的 baseline job。workflow 顶层有 `permissions: contents: read` 和 `concurrency` 设置。
2. **pytest markers**：`pyproject.toml` 注册 `unit`、`integration`、`smoke`、`live`、`slow`、`optional` 六个 marker。现有测试文件按实际类型打上对应 marker（至少：test_chunkers/test_embeddings/test_acl 等纯逻辑测试标 `unit`；test_web_console/test_health 标 `smoke`；test_fileshare_live_smoke 标 `live`）。
3. **Makefile targets**：新增 `test-unit`、`test-integration`、`test-smoke`、`test-fast`（`not live and not slow`）target。
4. **coverage 阈值**：全局 `fail_under` 改为 90。新增 `coverage-strict` target 对 core modules（chunkers, embeddings, retrieval, acl）单独跑 100% 覆盖。
5. **DB migration smoke job**：CI 中使用 `pgvector/pgvector:pg16` service，执行 `make migrate && make db-check && make migrate-down && make migrate && make db-check`。
6. **Docker build job**：CI 中执行 `docker build -t ragrig:ci .` 确认镜像构建成功。
7. **supply-chain job**：CI 中新增 job 执行 `make audit && make licenses`。
8. **验证命令**：`act` 或 `gh workflow run` 能通过，或 push 到 feature branch 后 GitHub Actions 全绿。

## best-effort 目标

- 添加 `.github/dependabot.yml` 配置（github-actions + pip weekly）
- CI 上传 coverage JSON 和 pip-audit 输出为 artifact

## 不做边界

- 不做 nightly workflow（P1）
- 不做 Playwright 测试（P2）
- 不做 RAG regression fixtures（P1）
- 不做 OpenAPI snapshot test（P1）
- 不做 release SBOM artifact（P2）
