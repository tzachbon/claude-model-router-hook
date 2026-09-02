# Research: Truthful advisory prose

## Executive Summary

The `debugging` advisory clause is already correct. `advisory.py` includes it
in `_SELECTION_CLAUSES`, and a debugging-only resolved config renders both the
`debugging | opus | high` row and `debugging to opus` closing prose. Retain the
implementation and add the focused regression only.

The remaining defect is limited to the Fable session hint. With every class
unroutable, the table and mandatory paragraph correctly say routing passes
through, but Fable still says to reserve it for extreme work and route lighter
work down the ladder. Gate that static Fable instruction on the already
resolved target set; do not change routing policy or the advisory table.

## Current-State Evidence

- `resolved_targets()` calls `policy.target_for_class()` for every class and
  records `None` when enforcement refuses the target
  (`plugins/claude-model-router-hook/hooks/router/advisory.py:97-119`).
  `target_for_class()` deliberately returns `None` for missing, malformed, or
  invalid class targets (`plugins/claude-model-router-hook/hooks/router/policy.py:38-69`).
- `_closing_paragraph()` filters its clauses with `if targets.get(klass)`
  (`advisory.py:122-144`), so it correctly emits the no-routable-class
  pass-through statement when every target is `None`.
- `_SELECTION_CLAUSES` already includes `("debugging", "debugging to ")`
  (`advisory.py:76-84`). A direct current-config rendering with only
  `debugging: {model: opus, effort: high}` produces the matching table row and
  `debugging to opus`; this is consistent with the default snapshot's debugging
  row and clause (`tests/test_variants.py:63,70-74`). Commit `f687111` added
  that clause, so no separate debugging implementation fix is warranted.
- The Fable `_TIER_HINTS` entry embeds a complete static routing instruction
  and has no class clauses (`advisory.py:177-186`). Once `_tier_hint()` matches
  `fable`, its rendered-clause list is empty and it returns that static lead
  (`advisory.py:223-239`), regardless of whether every target is `None`.
  `render_session_context()` passes the same resolved targets into this call
  (`advisory.py:242-254`), so this is the shared SessionStart advisory path;
  `session_init.py` only wires that renderer (`plugins/claude-model-router-hook/hooks/session_init.py:63-69`).

## Minimal Change

Inside `_tier_hint()`, after a tier match and before rendering tier clauses,
special-case only an all-unroutable Fable session:

```python
if tier == "fable" and not any(targets.values()):
    return "You are currently on fable."
```

This gates the down-ladder instruction on `resolved_targets()` rather than raw
configuration. It preserves Fable's existing hint whenever at least one class
is routable, leaves the other tier leads unchanged, and avoids a policy change.

## Direct Regression Seam

Extend `TestAdvisoryMatchesEnforcement` in `tests/test_variants.py`, next to
the existing unroutable-clause checks at `:221-265`.

1. Debugging-only config:
   `{"classes": {"debugging": {"target": {"model": "opus", "effort": "high"}}}}`.
   Call `render_advisory()` and assert both `| debugging | opus | high |` and
   `debugging to opus`, with no `No class is routable` text.
2. All-unroutable Fable config: call
   `render_session_context("claude-fable-5", {"classes": None})`. Assert the
   factual `You are currently on fable.` lead remains, while neither `Reserve
   it for extreme` nor `down the ladder` appears. The same config already
   establishes no routed rows at `tests/test_variants.py:232-238`; the nearby
   tier test currently covers only Opus at `:263-265`.

The direct Fable call currently reproduces the contradiction deterministically:
all five class rows show `(no routing)`, the closing paragraph says routing
passes through unchanged, then the tier section says `Reserve it for extreme,
platform-scale work; route everything lighter down the ladder.`

## Scope, Risk, and Verification

- Exclude policy/table redesign and a new debugging implementation change, as
  required by `plan.md:5-10`. The policy's `None` result is the desired source
  of truth.
- Risk is over-suppressing the Fable hint for a partially routable config;
  gate only the `not any(targets.values())` case and retain the existing text
  otherwise.
- Run `python3 -m unittest tests.test_variants` after the two focused tests.
  Baseline: `119` tests passed, with `3` root-environment skips.
