# Design: Truthful advisory prose

## Overview

Make the Fable SessionStart lead truthful when enforcement has no resolved
class target. Keep the existing advisory-table, closing-prose, routing-policy,
and debugging behavior intact.

## Change

Modify only `plugins/claude-model-router-hook/hooks/router/advisory.py` and
`tests/test_variants.py`.

In `_tier_hint(current_model, targets)`, after matching a tier and before
rendering its class clauses, add the exact Fable-only guard:

```python
if tier == "fable" and not any(targets.values()):
    return "You are currently on fable."
```

Do not change `_TIER_HINTS`, `resolved_targets()`, `render_advisory()`,
`_closing_paragraph()`, or policy resolution. The guard is intentionally based
on the already-resolved `{class: (model, effort) | None}` map, not raw config.

## Data flow

`session_init.py` passes the loaded config to `render_session_context()`.
That function obtains `targets = resolved_targets(cfg)`, renders the unchanged
table and closing paragraph, then passes the same map to `_tier_hint()`.

- A Fable session with no truthy target returns only the factual Fable lead.
- A Fable session with one or more resolved targets retains the current static
  extreme-work/down-ladder lead.
- Opus, Sonnet, Haiku, unknown-model, and missing-variant behavior are
  unchanged.

## Errors and compatibility

`resolved_targets()` remains the fail-safe boundary: malformed or unroutable
classes remain `None`, so the new guard adds no config parsing or exception
path. A non-dict config continues to render defaults. The existing
debugging-only table row and `debugging to opus` clause remain untouched; no
policy, table, dependency, or public-function signature changes are needed.

## Verification

Port the prototype's three regressions into
`TestAdvisoryMatchesEnforcement` in `tests/test_variants.py`:

1. A debugging-only `opus`/`high` config renders its table row and
   `debugging to opus`, without the no-routable message.
2. `render_session_context("claude-fable-5", {"classes": None})` retains
   `You are currently on fable.` but contains neither `Reserve it for extreme`
   nor `down the ladder`.
3. A Fable session with the debugging-only resolved target retains the current
   complete extreme-work/down-ladder directive.

Run `python3 -m unittest tests.test_variants`.
