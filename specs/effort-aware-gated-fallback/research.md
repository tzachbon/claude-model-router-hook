# Research: Effort-aware gated fallback

## Executive Summary

`min_gated_target()` already keeps a valid non-haiku implementation target as
the designated gate target. Its fallback is the only defect: when that target
is haiku or unusable, it walks the other configured targets but compares model
tier only. Rank fallback candidates by the existing `(TIERS, EFFORTS)` order,
leaving `CLASSES` iteration order as the stable tie-breaker. No new helper,
configuration field, or routing branch is needed.

## Current-State Evidence

- `plugins/claude-model-router-hook/hooks/router/policy.py:141-177` obtains
  the implementation pair first and returns it unchanged when it is a valid
  non-haiku target. Otherwise it walks `CLASSES`, skips `implementation`,
  unusable targets, and haiku targets, and updates `best` only when
  `TIERS.index(other[0]) < TIERS.index(best[0])`.
- With implementation `haiku`, debugging `opus/max`, architecture `opus/low`,
  and extreme `fable/high`, the current function deterministically returns
  `('opus', 'max')`: debugging is the first Opus candidate and the later Opus
  candidate cannot replace it under the tier-only comparison. The requested
  result is `('opus', 'low')`.
- `plugins/claude-model-router-hook/hooks/router/ladder.py:6-13` already
  defines the required order: `TIERS = (haiku, sonnet, opus, fable)` and
  `EFFORTS = (low, medium, high, xhigh, max)`. Every non-haiku fallback target
  produced by the normal merged config has an effort, so the minimal comparison
  is the lexicographic rank tuple `(TIERS.index(model), EFFORTS.index(effort))`.
  Exact tuples retain the first candidate because iteration is in the fixed
  `CLASSES = (mechanical, implementation, debugging, architecture, extreme)`
  order and replacement is strict.
- `min_gated_target()` has one direct production caller: `_gated_pair()`
  (`policy.py:186-208`). `_gated_pair()` is shared by `apply_gates()`
  (`:253-289`) and `gate_outcomes()` (`:231-249`). This reaches the
  UserPromptSubmit path through `main_prompt_decision()` and its explicit
  post-decision gate call, Agent spawning through `pre_tool_use.py:103-106`,
  and variant closure through `router/variants.py:75-108` plus
  `scripts/generate_variants.py:109-113`.

## Regression Seam

`TestMinGatedTarget` in `tests/test_variants.py:1092-1145` is the direct,
deterministic seam. Add the `haiku`/`opus/max`/`opus/low` configuration there
and assert `min_gated_target(cfg) == ('opus', 'low')`; it fails before the
comparison change and avoids unrelated hook setup. Keep the existing tests for
the designated implementation target, all-haiku case, invalid implementation,
and malformed configs.

An exact `(tier, effort)` tie has the same observable returned pair regardless
of its class, but the strict comparison is the required deterministic
implementation rule: the earlier `CLASSES` candidate remains selected.

## Scope, Risk, and Prototype Question

- Do not reorder `CLASSES`, change `target_for_class()`, alter normal routing
  or gating triggers, or synthesize a target absent from the configuration.
- Preserve the valid non-haiku implementation early return exactly; only the
  fallback ordering changes.
- `target_for_class()` can represent a direct raw non-haiku config with
  `effort is None`, while production `load_config()` deep-merges normal user
  configuration over the defaults. Confirm in the quick prototype that the
  tuple rank preserves the existing no-raise behavior for this malformed
  direct-call edge, rather than silently broadening this small ordering fix.

## Verification

Run the focused red/green loop and full suite:

```bash
python3 -m unittest tests.test_variants.TestMinGatedTarget
python3 -m unittest tests.test_variants
git diff --check
```

Baseline before the change: `python3 -m unittest tests.test_variants` passed
122 tests with 3 environment skips; the focused configuration above currently
returns `('opus', 'max')`.
