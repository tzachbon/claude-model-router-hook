# Tasks: Effort-aware gated fallback

Actionable implementation tasks: 2. Final verification checkpoint: 1 (Task 3).

Only `tests/test_variants.py` and
`plugins/claude-model-router-hook/hooks/router/policy.py` are in scope. Keep
the designated implementation early return, existing `CLASSES` order, normal
routing, and gate behavior unchanged.

- [x] 1. Port the focused fallback regressions
  - **Files**: `tests/test_variants.py` (`TestMinGatedTarget`)
  - **Do**: Port the retained prototype's three direct cases: with haiku implementation, debugging `opus/max`, and architecture `opus/low`, require `("opus", "low")`; with a raw non-haiku target whose effort is missing beside a later `opus/max`, require the explicit-effort target without raising; with that missing-effort target alone, require the original `(model, None)` result without raising. Keep the tests at the direct `min_gated_target()` seam.
  - **Done when**: Before the production change, the focused class has the two intentional ordering failures (tier-only `opus/max` selection and missing-effort preference), while the lone missing-effort safety case documents the preserved no-raise behavior.
  - **Verify**: `python3 -m unittest tests.test_variants.TestMinGatedTarget` (expects the two ordering regressions to fail before Task 2)
  - **Commit**: `test(variants): cover effort-aware gated fallback`

- [x] 2. Rank non-haiku fallback candidates by tier and effort
  - **Files**: `plugins/claude-model-router-hook/hooks/router/policy.py`
  - **Do**: Replace only `min_gated_target()`'s tier-only fallback condition with the inline strict key `(TIERS.index(model), effort is None, EFFORTS.index(effort or EFFORTS[0]))` for `other` and `best`. Keep the strict `<` replacement rule so equal keys retain the earlier `CLASSES` candidate; add no helper, normalization, or policy branch.
  - **Done when**: Task 1's three cases are green, a valid non-haiku implementation target still returns unchanged, and raw missing effort remains non-raising.
  - **Verify**: `python3 -m unittest tests.test_variants.TestMinGatedTarget`
  - **Commit**: `fix(policy): rank gated fallback by effort`

- [ ] 3. [VERIFY] Run the complete variants suite and whitespace check
  - **Files**: none
  - **Do**: Run the repository variants suite and confirm the final diff has no whitespace errors.
  - **Done when**: The suite exits 0, including the three fallback regressions; only existing environment-dependent permission skips may remain, and the diff check exits 0.
  - **Verify**: `python3 -m unittest tests.test_variants && git diff --check`
  - **Commit**: none (verification checkpoint)
