# Superpowers Working Notes

This directory stores agent planning artifacts, not product-facing user docs.

## Contents

- `plans/` contains implementation plans used during agent-assisted work.
- `specs/` contains short design notes that explain a chosen implementation
  approach before code changes.

## When To Read This

Most contributors can ignore this directory. Use it when:

- reviewing why an agent-made branch touched a particular set of files,
- reconstructing the intended execution order for a multi-step change,
- checking whether a design decision was scoped as implementation-only rather
  than a durable architecture decision.

Durable product and architecture decisions should live elsewhere:

- Product specs: [docs/specs](../specs/README.md)
- Architecture overview: [docs/architecture.md](../architecture.md)
- ADRs: [docs/adr](../adr/README.md)

## Maintenance

Do not put required setup instructions only in this directory. Anything a human
newcomer needs for onboarding belongs in README, Getting Started, Architecture,
Operations, or Specs.
