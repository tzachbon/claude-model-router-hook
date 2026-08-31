# Tasks: Truthful advisory prose

Actionable implementation tasks: 2. Final verification checkpoint: 1 (Task 3).

Only `plugins/claude-model-router-hook/hooks/router/advisory.py` and
`tests/test_variants.py` are in scope. Keep the existing debugging clause and
partially-routable Fable behavior; do not redesign routing policy, the advisory
table, or the tier-hint structure.

- [ ] 1. Port the direct advisory regressions
  - **Files**: `tests/test_variants.py` (`TestAdvisoryMatchesEnforcement`)
  - **Do**: Add the retained prototype's three cases at the enforcement/advisory seam: a debugging-only `opus`/`high` config must render both `| debugging | opus | high |` and `debugging to opus` without the no-routable text; `render_session_context("claude-fable-5", {"classes": None})` must keep `You are currently on fable.` while omitting `Reserve it for extreme` and `down the ladder`; a Fable session with the debugging-only resolved target must retain both existing Fable routing phrases. Name the focused tests for these three boundaries.
  - **Done when**: The debugging-only and partially-routable Fable tests are green on current code, and the all-unroutable Fable test is the one intentional red failure because the static directive is still rendered.
  - **Verify**: `python3 -m unittest tests.test_variants.TestAdvisoryMatchesEnforcement` (expects exactly the all-unroutable Fable regression to fail before Task 2)
  - **Commit**: `test(advisory): cover truthful fable guidance`

- [ ] 2. Suppress only the all-unroutable Fable directive
  - **Files**: `plugins/claude-model-router-hook/hooks/router/advisory.py`
  - **Do**: In `_tier_hint()`, after matching `fable` and before clause rendering, return `You are currently on fable.` when `not any(targets.values())`. Base the guard only on the existing resolved-target map. Leave `_SELECTION_CLAUSES`, `resolved_targets()`, routing policy, the advisory table, and the current Fable lead untouched for any config with at least one resolved target.
  - **Done when**: The all-unroutable Fable regression turns green; the debugging-only table/prose regression and partially-routable Fable directive remain green.
  - **Verify**: `python3 -m unittest tests.test_variants.TestAdvisoryMatchesEnforcement`
  - **Commit**: `fix(advisory): suppress unroutable fable routing hint`

- [ ] 3. [VERIFY] Run the focused variants suite
  - **Files**: none
  - **Do**: Run the complete variants suite and whitespace check from the primary worktree.
  - **Done when**: The suite exits successfully, including the three advisory boundaries; only the existing root-environment permission skips may remain, and the diff is whitespace-clean.
  - **Verify**: `python3 -m unittest tests.test_variants && git diff --check`
  - **Commit**: none (verification only)
