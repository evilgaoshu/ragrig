# EVI-64: Dependabot 分组与 chore PR 治理

## 目标

为 `evilgaoshu/ragrig` 仓库配置 Dependabot 分组策略，将零散的依赖/Actions 更新 PR 合并为可审查的分组 PR，消除 #40-#46 模式的散碎 chore PR 堆积。

## 分组策略

Dependabot 按以下四个维度将更新合并为分组 PR：

| 分组名 | 范围 | 风险级别 | 说明 |
|--------|------|----------|------|
| `github-actions` | 所有 GitHub Actions (`actions/*`, `astral-sh/*`) | 低 | Actions 更新独立性强，合并后只需验证 CI 全绿 |
| `python-runtime` | 生产运行时依赖 (`[project].dependencies`) | 高 | 影响核心功能，需仔细审查 breaking changes |
| `python-dev` | 开发工具链 (`[dependency-groups].dev`) | 中 | 影响代码质量和 CI 流程，不影响生产 |
| `python-extras` | 可选依赖组 (`[project.optional-dependencies]`) | 中低 | 各插件独立，影响面隔离 |

### 分组设计原则

1. **actions 独立一组**：Actions 版本号变动频繁（如 checkout 的 major bump），与 Python 依赖无联动，独立分组减少噪声。
2. **runtime 独立一组**：FastAPI、SQLAlchemy、psycopg 等核心运行时依赖变更需严格审查，单独分组确保不被 dev/extras 噪声淹没。
3. **dev 独立一组**：ruff、pytest 等工具链变更不影响运行时行为，分组后可快速合并或回滚。
4. **extras 独立一组**：`cloud-*`、`local-ml`、`s3`、`parquet` 等可选依赖仅在特定 profile 下安装，分组后不会阻塞 runtime 更新。

### Dependabot 配置结构

```yaml
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
    groups:
      github-actions:
        patterns: ["*"]

  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
    groups:
      python-runtime:
        patterns:
          - "alembic"
          - "fastapi"
          - "pgvector"
          - "pydantic-settings"
          - "psycopg*"
          - "sqlalchemy"
          - "uvicorn*"
          - "python-multipart"
          - "pyyaml"
      python-dev:
        patterns:
          - "cyclonedx-bom"
          - "httpx"
          - "lxml"
          - "pip-audit"
          - "pip-licenses"
          - "pytest*"
          - "ruff"
      python-extras:
        patterns:
          - "boto3"
          - "cohere"
          - "google-cloud-aiplatform"
          - "openai"
          - "voyageai"
          - "FlagEmbedding"
          - "ollama"
          - "sentence-transformers"
          - "torch"
          - "pyarrow"
          - "paramiko"
          - "smbprotocol"
          - "qdrant-client"
```

## 风险边界

### 风险 1：分组 PR 中单个依赖更新失败阻塞整组

- **表现**：一个 runtime 依赖的 major bump 引入 breaking change，导致整个 `python-runtime` 组 PR 无法合并。
- **缓解**：
  - runtime 组仅有 9 个直接依赖，问题定位快。
  - CI 矩阵覆盖 Python 3.11/3.12，lint + test + coverage + db-smoke + web-smoke + supply-chain 七道门。
  - 必要时可临时拆分：在 `dependabot.yml` 中为问题依赖新增独立 `allow` 条目排除出组，等待修复后再恢复。

### 风险 2：分组导致审查疲劳

- **表现**：每周一个大的 extras 组 PR 包含 13+ 个可选依赖更新，审查者忽略其中高风险变更。
- **缓解**：
  - extras 组中的依赖仅在特定可选 profile 下安装，风险面天然隔离。
  - 分组 PR 中 Dependabot 仍会逐个列出每个依赖的 changelog/release notes。

### 风险 3：分组 PR 合并后引入隐身回归

- **表现**：分组 PR CI 通过但合并后某个边缘路径因依赖更新而回归。
- **缓解**：
  - CI 已覆盖 lint、format、unit/integration test、coverage (≥90%)、db migration smoke、web console smoke、supply chain audit。
  - 代码覆盖率 fail-under 90%。

## 回滚方式

### 撤销分组 PR

```bash
git revert -m 1 <merge-commit-sha>
```

分组 PR 本质是 Dependabot 生成的多个版本号 bump 的聚合，撤销操作与其他 PR 无异。

### 回滚单个依赖更新

1. 在 `pyproject.toml` 中恢复该依赖的版本上限。
2. 运行 `uv lock` 更新 lockfile。
3. 手动 PR 或等待下一轮 Dependabot 更新覆盖。

### 禁用分组（回退到旧行为）

删除 `.github/dependabot.yml` 中的 `groups` 配置段，保留 `updates` 段。Dependabot 将恢复为每个依赖独立 PR。

## 不做边界

- 不启用自动合并（`auto-merge: true`）
- 不在此 PR 中升级具体依赖版本
- 不修改发布流程（CD pipeline）

## best-effort 补充

### Auto-label

Dependabot 为分组 PR 自动添加标签，便于分类和过滤：

```yaml
# groups 内的每个 group 可配置：
labels:
  - "dependencies"
```

全局配置确保所有 Dependabot PR 带 `dependencies` 标签，已有仓库标签 `dependencies` 可直接使用。

### Auto-close superseded PRs

当分组 PR 创建后，旧的分组 PR 会被 Dependabot 自动关闭（同一分组名）。仅策略变更导致旧独立 PR 仍存在时需手动关闭。

建议 weekly 审查时运行：

```bash
gh pr list --repo evilgaoshu/ragrig --state open --label dependencies \
  --json number,title,createdAt \
  | jq 'sort_by(.createdAt) | .[:-1][] | .number' \
  | xargs -I{} gh pr close {} --repo evilgaoshu/ragrig \
    --comment "Superseded by newer grouped Dependabot PR."
```

（保留最新 PR，关闭同标签旧 PR。）

## 验证

- [ ] `.github/dependabot.yml` 存在 `groups` 配置
- [ ] GitHub Actions 更新合并为一组
- [ ] Python 依赖按 runtime / dev / extras 分组
- [ ] `make lint` 通过
- [ ] `make test-fast` 通过
- [ ] `make web-check` 通过
- [ ] PR CI 全部 SUCCESS
- [ ] 配置生效后不再出现同类散碎依赖更新 PR
