# Vercel Deployment Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the duplicate GitHub Actions Production deployment while preserving Vercel Preview, Production, and the hosted demo domain.

**Architecture:** Vercel Git integration remains the sole deployment controller. Repository tests and documentation describe and enforce that deployment shape; the obsolete GitHub `demo` Environment is deleted only after the repository change reaches `main`.

**Tech Stack:** GitHub Actions, Vercel Git integration, pytest, Markdown

---

### Task 1: Replace the duplicate-workflow contract

**Files:**
- Modify: `tests/test_vercel_preview_deployment.py`
- Delete: `.github/workflows/vercel-demo-deploy.yml`

- [ ] **Step 1: Change the workflow test to reject the duplicate workflow**

Replace `test_vercel_demo_workflow_deploys_main_and_aliases_custom_domain` with:

```python
def test_vercel_git_integration_is_the_only_production_deployment_path() -> None:
    assert not (REPO_ROOT / ".github" / "workflows" / "vercel-demo-deploy.yml").exists()
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `uv run pytest tests/test_vercel_preview_deployment.py::test_vercel_git_integration_is_the_only_production_deployment_path -q`

Expected: FAIL because `.github/workflows/vercel-demo-deploy.yml` still exists.

- [ ] **Step 3: Delete the duplicate workflow**

Delete `.github/workflows/vercel-demo-deploy.yml`.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `uv run pytest tests/test_vercel_preview_deployment.py::test_vercel_git_integration_is_the_only_production_deployment_path -q`

Expected: PASS.

### Task 2: Document the deployment shape

**Files:**
- Modify: `docs/specs/EVI-130-vercel-preview-supabase.md`

- [ ] **Step 1: Document Preview and Production ownership**

Add a deployment lifecycle section stating:

```markdown
## Deployment Lifecycle

- Pull requests and non-production branches create Vercel Preview deployments.
- Pushes to `main` create Vercel Production deployments through Vercel Git integration.
- `demo.ragrig.dev` is a Production Domain attached to the Vercel project.
- Do not add a second GitHub Actions workflow that runs `vercel deploy --prod`.
```

- [ ] **Step 2: Run deployment-focused tests**

Run: `uv run pytest tests/test_vercel_preview_deployment.py -q`

Expected: PASS.

### Task 3: Verify and publish

**Files:**
- Verify all modified files

- [ ] **Step 1: Run formatting and lint**

Run: `uvx ruff format --check . && uvx ruff check . && git diff --check`

Expected: all checks pass.

- [ ] **Step 2: Commit and push**

```bash
git add .github/workflows/vercel-demo-deploy.yml tests/test_vercel_preview_deployment.py docs/specs/EVI-130-vercel-preview-supabase.md docs/superpowers/specs/2026-06-04-vercel-deployment-simplification-design.md docs/superpowers/plans/2026-06-04-vercel-deployment-simplification.md
git commit -m "Simplify Vercel deployment environments"
git push -u origin codex/simplify-vercel-deployments
```

- [ ] **Step 3: Create and merge the pull request after CI passes**

Create a pull request against `main`, wait for required checks, then squash merge.

- [ ] **Step 4: Delete the obsolete GitHub Environment**

Run after the change reaches `main`:

```bash
gh api --method DELETE repos/evilgaoshu/ragrig/environments/demo
```

- [ ] **Step 5: Verify the final deployment state**

Verify `https://demo.ragrig.dev/health` returns HTTP 200 and GitHub environments
contain only `Preview` and `Production`.
