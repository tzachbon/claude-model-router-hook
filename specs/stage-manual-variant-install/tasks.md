# Tasks: Stage Manual Variant Installation

## Execution Rules

- Scope is limited to `plugins/claude-model-router-hook/install.sh` and `tests/test_variants.py`; do not touch `tests/test-install.sh`, the generator, or dependencies.
- Assign a separate executor to each implementation task (1–3). Task 4 is the shared verification checkpoint.
- Keep the guarantee narrow: generation failure is all-or-nothing; post-generation publish failures get no new rollback behavior.

- [x] 1. Add the red full-tree failure regression

**Executor:** dedicated test executor  
**Files:** `tests/test_variants.py` (`TestInstallScript`)

- Replace/upgrade the conflict regression with `test_generator_failure_leaves_the_live_tree_unchanged` at the direct manual-installer seam.
- Seed `.claude` with byte-distinct sentinels for `hooks/router`, all four hook entrypoints, `schema/model-router.schema.json`, an unrelated agent plus hidden/nested unrelated-agent content, a handwritten `agents/routed-haiku.md` conflict, and a stale generated `routed-fable-high.md`.
- Add a small class-local snapshot that records every relative directory and every file's binary bytes beneath `.claude`. Snapshot before running `bash MANUAL_INSTALLER`; require a non-zero result with `CONFLICT`, no success footer, and exact snapshot equality afterward.

**Done when:** this command is red against the current installer because it has already changed live `.claude` content before the generator reports the conflict:

```bash
python3 tests/test_variants.py TestInstallScript.test_generator_failure_leaves_the_live_tree_unchanged
```

**Commit:** `test(variants): cover atomic manual installer failure`

- [ ] 2. Stage generation before live publication

**Executor:** dedicated installer executor  
**Files:** `plugins/claude-model-router-hook/install.sh`

- Before any live `mkdir`, `rm`, or `cp`, create an external `mktemp -d` stage, install an `EXIT` cleanup trap, create its `agents` directory, and copy existing `"$AGENTS_DIR/."` contents into it only when the live directory exists.
- Run the existing `generate_variants.py --use-user-config` command unchanged against the staged agents directory.
- Only after that command succeeds, retain the current hook/router, entrypoint, and schema copies, then replace live agents last with the complete staged tree (`rm -rf -- "$AGENTS_DIR"`; `cp -R "$STAGED_AGENTS" "$AGENTS_DIR"`). Keep quoted paths and strict shell mode.

**Done when:** a generator conflict exits non-zero before any live Claude path changes, staging is removed by the trap, and the regression from task 1 is green:

```bash
bash -n plugins/claude-model-router-hook/install.sh
python3 tests/test_variants.py TestInstallScript.test_generator_failure_leaves_the_live_tree_unchanged
```

**Commit:** `fix(install): stage variants before publishing`

- [ ] 3. Cover successful preservation of unrelated agents

**Executor:** dedicated test executor  
**Files:** `tests/test_variants.py` (`TestInstallScript`)

- Extend `test_sonnet_free_config_installs_no_sonnet_agent` rather than adding another installer harness.
- Pre-seed ordinary and hidden/nested unrelated agent files with known binary content. After a successful install, assert each original relative path and bytes remain, while the configured generated-agent assertions still pass.

**Done when:** the focused success case proves promotion preserves unrelated agents:

```bash
python3 tests/test_variants.py TestInstallScript.test_sonnet_free_config_installs_no_sonnet_agent
```

**Commit:** `test(variants): preserve unrelated manual-install agents`

- [ ] 4. [VERIFY] Verify the completed boundary

**Executor:** verification runner  
**Files:** none

Run the direct installer suite, then the repository regression suite and whitespace check:

```bash
bash -n plugins/claude-model-router-hook/install.sh
python3 tests/test_variants.py TestInstallScript
python3 tests/test_variants.py
git diff --check
```

**Done when:** all commands pass; the only implementation changes are the staged installer and its focused `TestInstallScript` coverage.

**Commit:** none — verification checkpoint.
