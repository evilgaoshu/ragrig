# Local Pilot Demo Kit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Local Pilot easy to demonstrate with a minimal startup preflight, sample documents/questions, and README instructions.

**Architecture:** Add a standalone `scripts.local_pilot_preflight` command that separates required startup checks from optional model/provider readiness. Add checked-in demo fixtures under `examples/local-pilot/` and document a 10-minute demo path that reuses existing Docker, smoke, and Web Console flows.

**Tech Stack:** Python, pytest, FastAPI TestClient, Makefile, Docker Compose, Markdown/JSON fixtures.

---

### Task 1: Minimal Preflight Contract

**Files:**
- Create: `scripts/local_pilot_preflight.py`
- Test: `tests/test_local_pilot_preflight.py`
- Modify: `Makefile`

- [ ] **Step 1: Write failing tests**

Add tests proving that required checks pass without model configuration and that missing optional providers never fail startup.

- [ ] **Step 2: Implement minimal preflight**

Implement required checks for app import, ephemeral SQLite health, artifact directory writability, and optional Docker CLI readiness when `--mode docker` is selected.

- [ ] **Step 3: Expose Make targets**

Add `local-pilot-preflight` and `pilot-docker-preflight` targets.

### Task 2: Demo Fixtures

**Files:**
- Create: `examples/local-pilot/company-handbook.md`
- Create: `examples/local-pilot/support-faq.md`
- Create: `examples/local-pilot/demo-questions.json`
- Create: `tests/test_local_pilot_demo_kit.py`

- [ ] **Step 1: Write fixture contract tests**

Verify demo files exist, are readable, contain citations-friendly facts, and include at least three grounded questions.

- [ ] **Step 2: Add fixtures**

Add small Markdown fixtures and demo questions that work with the existing upload, retrieval, and answer surfaces.

### Task 3: README Demo Path

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Test: `tests/test_pilot_docker_pack.py`

- [ ] **Step 1: Write docs tests**

Verify README files mention the preflight, sample files, model optionality, and existing smoke commands.

- [ ] **Step 2: Update docs**

Add concise 10-minute Local Pilot demo instructions in English and Chinese. Keep project positioning unchanged; Local Pilot remains a roadmap/demo path.

### Task 4: Verification and PR

Run:

```bash
uv run pytest tests/test_local_pilot_preflight.py tests/test_local_pilot_demo_kit.py tests/test_pilot_docker_pack.py
make local-pilot-preflight
git status --short
```

Open a PR with the implementation and verification notes.
