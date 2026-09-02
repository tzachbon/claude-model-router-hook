# Requirements: Effort-aware gated fallback

## User story

As a Claude hook user, I need gated work to choose the least-capable legal
configured target when the implementation target cannot be used, so fallback
does not spend more effort than necessary.

## Functional requirements

- **FR-1 — Designated implementation:** A valid, non-haiku implementation
  target remains `min_gated_target()`'s result unchanged, regardless of other
  configured class targets.
- **FR-2 — Ordered fallback:** When implementation is haiku or unusable,
  choose from the other usable non-haiku configured targets by lowest model
  tier first, then lowest effort, using the existing `TIERS` and `EFFORTS`
  order.
- **FR-3 — Stable exact ties:** Candidates with the same `(tier, effort)` do
  not replace the earlier candidate; the fixed `CLASSES` iteration order is
  the strict deterministic tie-breaker.
- **FR-4 — No invented target:** An all-haiku or targetless malformed
  configuration returns `None` without raising or selecting a model absent from
  the configuration. A usable non-haiku target with missing effort returns
  `(model, None)` without raising.

## Acceptance criteria

- With implementation `haiku`, debugging `opus/max`, architecture `opus/low`,
  and extreme `fable/high`, `min_gated_target()` returns `('opus', 'low')`.
- A valid non-haiku implementation target is still returned exactly, even if a
  different class declares a lower tier or effort.
- Equal-rank fallback candidates retain the first matching `CLASSES` entry;
  their equality does not trigger replacement.
- Existing all-haiku and malformed-config test cases continue to return
  `None`, without an exception.

## Verification

- Add the red/green regression at the direct deterministic seam:
  `TestMinGatedTarget` in `tests/test_variants.py`.
- Run `python3 -m unittest tests.test_variants.TestMinGatedTarget`, then
  `python3 -m unittest tests.test_variants`, and `git diff --check`.

## Bounded prototype concern

The quick prototype must check the narrow direct-call edge where raw malformed
configuration yields a non-haiku model with missing effort. The ordering change
must preserve the existing no-raise behavior; it must not broaden this fix
into raw-config normalization or a new fallback policy.

## Non-functional requirements

- Limit the change and regression coverage to
  `plugins/claude-model-router-hook/hooks/router/policy.py` and
  `tests/test_variants.py`.
- Reuse the existing order constants; add no dependency, helper abstraction,
  configuration field, routing branch, or class reordering.

## Exclusions

- No change to normal routing, gate triggers, `target_for_class()`, or variant
  generation.
- No synthesis of targets absent from configuration.
