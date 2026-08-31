# Plan: Effort-aware gated fallback

## Scope

Change only `min_gated_target`'s non-haiku fallback selection: choose the lowest model tier, then the lowest effort, while preserving `CLASSES` order for exact `(tier, effort)` ties. Keep a valid non-haiku implementation target as the designated target.

## Excluded scope

- Reordering classes or changing normal routing/gate behavior.
- Synthesizing targets absent from configuration.

## Target files

- `plugins/claude-model-router-hook/hooks/router/policy.py`
- `tests/test_variants.py`

## Minimal approach

Replace the tier-only fallback comparison with the existing tier and effort ordering. Preserve the first configured class encountered when both ranks match.

## Acceptance checks

- With implementation `haiku`, debugging `opus/max`, and architecture `opus/low`, the fallback is `opus/low`.
- Equal tier/effort candidates resolve by `CLASSES` order.
- A valid non-haiku implementation target remains selected; configuration-only targets remain configuration-only.
- `python3 -m unittest tests.test_variants` passes.

## Ordering and dependencies

Independent; it can ship at any point.
