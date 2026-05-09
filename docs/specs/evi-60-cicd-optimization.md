# EVI-60: ragrig CI/CD 优化 SPEC

## 目标

重构 CI/CD pipeline，将现有重复的 baseline/checks 双 job 拆分为职责清晰的独立 job，补齐 pytest markers、DB migration CI 测试、Docker build 验证，降低不必要阻塞。

## 变更清单

### 1. pytest markers

`pyproject.toml` 注册以下六个 marker：

- `unit`：纯逻辑单元测试，无外部依赖
- `integration`：使用 SQLite 或 mock 的集成测试
- `smoke`：系统级冒烟测试
- `live`：需要真实外部服务的测试
- `slow`：计算量大或耗时较长的测试
- `optional`：需要可选依赖的测试

### 2. Makefile targets

新增：

- `make test-unit`：运行 `pytest -m unit`
- `make test-integration`：运行 `pytest -m integration`
- `make test-smoke`：运行 `pytest -m smoke`
- `make test-live`：运行 `pytest -m live`
- `make test-fast`：运行 `pytest -m "not live and not slow"`

### 3. GitHub Actions CI workflow

`.github/workflows/ci.yml` 包含：

- `permissions: contents: read`
- `concurrency` 设置
- `checks` job：Python 3.11/3.12 matrix，执行 format / lint / test-fast / coverage / web-check
- `db-smoke` job：使用 `pgvector/pgvector:pg16` service，执行 `make migrate && make db-check && make migrate-down && make migrate && make db-check`
- `docker-build` job：执行 `docker build -t ragrig:ci .`

已删除旧的冗余 `baseline` job。

### 4. 测试文件 marker 映射（至少）

- `test_chunkers.py`、`test_embeddings.py`、`test_acl.py` 等纯逻辑测试 → `unit`
- `test_web_console.py`、`test_health.py` → `smoke`
- `test_fileshare_live_smoke.py` → `live`

### 5. 验证命令

DEV 需在 PR 中贴出以下命令的执行结果：

- `uv run ruff format --check .`
- `make lint`
- `make test-fast`
- `make coverage`
- `make web-check`

若 Docker/DB 本地不可用，可贴 GitHub Actions 对应 job 成功链接。

## best-effort 目标

- 添加 `.github/dependabot.yml` 配置（github-actions + pip weekly）
- CI 上传 coverage JSON 和 pip-audit 输出为 artifact
- 新增 nightly/manual workflow 跑 qdrant、s3、fileshare、supply-chain

## 不做边界

- 不接真实云凭证
- 不做 Playwright
- 不做发布、签名镜像或 release SBOM
