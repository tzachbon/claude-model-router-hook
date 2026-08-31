# Requirements: Truthful advisory prose

## User story

As a Claude hook user, I need advisory prose to describe only routes that are
actually enforceable, so a SessionStart hint never directs work to unavailable
tiers.

## Functional requirements

- **FR-1 — Debugging consistency:** Keep the existing debugging selection
  clause. When debugging alone resolves to `opus` at `high` effort, the
  advisory table and closing prose must both identify that route.
- **FR-2 — All-unroutable Fable:** When no class has a resolved routable
  target, a Fable session must retain factual tier identification (`You are
  currently on fable.`) but must not include an extreme-work or down-ladder
  routing directive.
- **FR-3 — Partially routable Fable:** When at least one class has a resolved
  routable target, retain the current Fable guidance, including its
  extreme-work and down-ladder instruction.

## Acceptance criteria

- A debugging-only configuration with `debugging` routed to `opus`/`high`
  renders both `| debugging | opus | high |` and `debugging to opus`, without
  the no-routable-class message.
- A Fable session with every class unroutable renders factual Fable
  identification and renders neither `Reserve it for extreme` nor `down the
  ladder`.
- A Fable session with one or more resolved targets still renders the existing
  Fable extreme-work/down-ladder guidance.
- `python3 -m unittest tests.test_variants` passes as the full variants
  validation.

## Non-functional requirements

- Limit implementation and regression coverage to
  `plugins/claude-model-router-hook/hooks/router/advisory.py` and
  `tests/test_variants.py`.
- Preserve current routing policy and advisory-table behavior; add no
  dependency.

## Exclusions

- No routing-policy or advisory-table redesign.
- No separate debugging-clause implementation change.
