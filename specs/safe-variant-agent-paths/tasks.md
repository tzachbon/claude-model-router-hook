# Tasks: Safe Routed-Agent Paths

Actionable implementation tasks: 4. Final verification checkpoint: 1 (Task 5; not an implementation task).

Only these implementation files are in scope: `tests/test_variants.py`, `plugins/claude-model-router-hook/hooks/router/variants.py`, and `scripts/generate_variants.py`.

- [ ] 1. Port the retained all-or-nothing symlink regression
  - **Files**: `tests/test_variants.py`
  - **Do**: Port the retained `preflight-all-or-nothing` regression into `TestVariantGenerator`: make a wanted `routed-opus-high.md` a symlink to a regular outside file; keep a drifting safe wanted sibling and a safe generated stale sibling that would otherwise be pruned. Snapshot both safe siblings, then assert the generator fails, reports the unsafe candidate, leaves both snapshots unchanged, and leaves the symlink intact.
  - **Done when**: The focused test is red on the current generator, proving the exact sibling-mutation regression before production changes.
  - **Verify**: `python3 tests/test_variants.py TestVariantGenerator.test_unsafe_wanted_symlink_leaves_safe_sibling_unchanged` (expects non-zero before Task 3)
  - **Commit**: `test(variants): add all-or-nothing symlink regression`

- [ ] 2. Add the shared routed-agent inspector and use it for installed-ness
  - **Files**: `plugins/claude-model-router-hook/hooks/router/variants.py`, `tests/test_variants.py`
  - **Do**: Add one small stdlib-only inspector returning absent, safe decoded text, or unsafe reason. Use `os.lstat` plus `stat.S_ISLNK`/`stat.S_ISREG`; only `FileNotFoundError` is absent, and every other inspect/read/decode failure is unsafe. Make `is_installed()` use it before `is_generated()`. Add the missing regular-file-symlink regression while retaining normal generated-file coverage and the existing permission skip.
  - **Done when**: `is_installed()` returns `False` for a symlink to an otherwise valid generated file, and still returns `True` for a safe ordinary generated file.
  - **Verify**: `python3 tests/test_variants.py TestInstalledMeansUsable`
  - **Commit**: `fix(variants): reject unsafe routed-agent paths`

- [ ] 3. Preflight every generator candidate before mutation
  - **Files**: `scripts/generate_variants.py`
  - **Do**: Remove the conflating `_read()` path. Distinguish a missing agents directory from listing failures, inspect the sorted `wanted ∪ existing` set through the shared helper, and retain safe text while building the full action plan. On any unsafe candidate, emit deterministic `UNSAFE` diagnostics and return `1` before `makedirs`, writes, or removals. Apply the existing ownership, conflict, update, prune, `--force`, and `--check` behavior only to the fully safe plan.
  - **Done when**: An unsafe wanted or stale routed file cannot update, remove, replace, or create any sibling; safe ordinary generated and foreign-file semantics remain unchanged.
  - **Verify**: `python3 tests/test_variants.py TestVariantGenerator.test_unsafe_wanted_symlink_leaves_safe_sibling_unchanged`
  - **Commit**: `fix(generator): preflight routed-agent mutations`

- [ ] 4. Cover the remaining unsafe-path and mode matrix
  - **Files**: `tests/test_variants.py`
  - **Do**: Add compact `subTest` coverage for regular-file symlinks, directories/non-regular paths, unreadable ordinary files (using the existing non-root skip), and invalid UTF-8 in both wanted and stale positions. Run each applicable generator case normally and with `--force`; assert rejected `--check` plans do not create, write, remove, or replace paths, and safe `--check` drift does not create a missing agents directory. Keep the ordinary generated update/prune/`--force` cases and the full `is_installed()` unsafe matrix passing.
  - **Done when**: Every unsafe case fails closed in the generator and yields `is_installed() == False`; ordinary safe-file update, prune, force, and check behavior remains green.
  - **Verify**: `python3 tests/test_variants.py TestVariantGenerator TestInstalledMeansUsable`
  - **Commit**: `test(variants): cover unsafe routed-agent paths`

- [ ] 5. [VERIFY] Run the focused variants suite
  - **Files**: none
  - **Do**: Run the complete focused regression suite from the primary worktree.
  - **Done when**: The suite exits 0; only the existing permission-dependent unreadable-file skips may remain when tests run as root.
  - **Verify**: `python3 tests/test_variants.py`
  - **Commit**: none (verification only; use `fix(variants): ...` if remediation is needed)
