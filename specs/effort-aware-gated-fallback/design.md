# Design: Effort-aware gated fallback

## Decision

Change only `min_gated_target()` in
`plugins/claude-model-router-hook/hooks/router/policy.py`.  Keep its valid,
non-haiku implementation-target early return unchanged.  In the existing
fallback loop, compare candidates with a strict lexicographic inline key:

```python
(
    TIERS.index(pair[0]),
    pair[1] is None,
    EFFORTS.index(pair[1] or EFFORTS[0]),
)
```

The update remains a strict `<` comparison.  It selects the lowest tier,
then an explicit effort before a missing effort, then the lowest explicit
effort.  Equal keys do not replace `best`, so the existing `CLASSES` iteration
order remains the deterministic exact-tie rule.

## Boundaries and error handling

No helper, new policy, config normalization, class reordering, or routing/gate
branch is needed.  `target_for_class()` can return a direct raw non-haiku
target whose effort is `None`; the middle boolean ranks it after an explicit
effort and the final `or EFFORTS[0]` prevents `EFFORTS.index(None)` from
raising.  When it is the only legal fallback, its original `(model, None)`
pair is retained.  All-haiku, unusable, and malformed configurations continue
to return `None` through the existing filtering.

## Tests

Add three focused tests to `TestMinGatedTarget` in
`tests/test_variants.py`, beside the existing fallback-order test:

- haiku implementation with `opus/max` before `opus/low` returns
  `("opus", "low")`;
- a raw `opus` target with missing effort loses to a later `opus/max` target
  without raising;
- that same raw missing-effort target alone returns `("opus", None)` without
  raising.

Existing designated-implementation, all-haiku, invalid, and malformed-config
tests cover the unchanged behavior and exact ties remain covered by the strict
comparison rule.

## Verification

```bash
python3 -m unittest tests.test_variants.TestMinGatedTarget
python3 -m unittest tests.test_variants
git diff --check
```
