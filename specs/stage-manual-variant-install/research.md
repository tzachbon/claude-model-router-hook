# Manual Variant Install Staging Research

## Executive Summary

`plugins/claude-model-router-hook/install.sh` changes the live Claude install before it asks the variant generator to succeed. Stage a copy of the live agents tree with `mktemp`, `cp -R`, and a cleanup `trap`; run the existing generator against that copy; then perform the current live copies and replace the agents directory only after generation returns zero. This preserves user agents and gives the requested all-or-nothing boundary for generation failures without changing the generator or adding a rollback framework.

## Current Live Mutation Order

1. The installer creates live `hooks`, `agents`, and `schema` directories at `plugins/claude-model-router-hook/install.sh:19`.
2. It deletes and recopies live `hooks/router` at `:22-23`, then overwrites the four live entrypoints at `:26-29`.
3. It invokes `scripts/generate_variants.py --agents-dir "$AGENTS_DIR" --use-user-config` at `:37-38`, so generation currently writes directly to live agents.
4. Only after a successful generator run does it copy the schema at `:40-41`.

The generator is safe for an unsafe routed path before mutation (`scripts/generate_variants.py:121-133`), but a normal ownership conflict is collected and execution continues through the action loop (`:166-200`) before the non-zero result at `:202-213`. Thus a handwritten `routed-haiku.md` stays intact, yet later routed siblings may be created, updated, or removed before the install aborts. `_existing_router_files()` considers only `routed-*.md` (`:68-78`), so unrelated agents are not generator targets but must still be copied into the staged tree before replacing it.

## Minimal Staging Boundary

Before any live `mkdir`, `rm`, or `cp`, create an external temporary directory, register `trap 'rm -rf -- "$STAGE"' EXIT`, create its `agents` child, and copy `"$AGENTS_DIR/."` into it when the live directory exists. Run the unchanged generator command against the staged agents directory; its `--use-user-config` lookup still reads the user's live configuration (`scripts/generate_variants.py:52-65`). A non-zero exit lets `set -e` and the trap discard staging with no persistent live mutation. On success, perform the existing hook/router/entrypoint/schema installation and replace the live agents directory with the staged full-tree copy.

```bash
STAGE="$(mktemp -d)"
trap 'rm -rf -- "$STAGE"' EXIT
STAGED_AGENTS="$STAGE/agents"
mkdir -p "$STAGED_AGENTS"
[ ! -d "$AGENTS_DIR" ] || cp -R "$AGENTS_DIR/." "$STAGED_AGENTS/"
python3 "$REPO_ROOT/scripts/generate_variants.py" \
    --agents-dir "$STAGED_AGENTS" --use-user-config
# Only now create/replace live hooks, schema, and agents.
```

On a generator failure, these paths—and their absence if absent initially—must be byte-for-byte unchanged:

- `$HOME/.claude/agents/` in full, including unrelated user agents, handwritten routed conflicts, and old generated variants.
- `$HOME/.claude/hooks/router/`, plus `session_init.py`, `user_prompt_submit.py`, `pre_tool_use.py`, and `post_tool_use.py`.
- `$HOME/.claude/schema/model-router.schema.json`.

## Narrow Regression Seam

`tests/test-install.sh` drives the unrelated top-level wizard (`:4-5`, `:125-132`). The direct manual-installer suite is `TestInstallScript` in `tests/test_variants.py:840-915`, using `MANUAL_INSTALLER` (`:25`) and a temporary HOME (`:843-858`). Add one all-or-nothing snapshot test to that class: seed `.claude/hooks/router`, the four entrypoint paths, `.claude/schema/model-router.schema.json`, an unrelated agent, and a handwritten `agents/routed-haiku.md`; snapshot the whole `.claude` tree as bytes; run the manual installer; assert non-zero and exact snapshot equality. The current installer fails this because it replaces hooks before the conflict and the generator can create later variants after it encounters the conflict.

## Non-Goals and Recommendation

Do not add dependencies, a generic transaction/rollback framework, generator changes, or a second ownership model. The smallest fix is installer sequencing plus that one shell regression: stage the full agents tree, run the existing stdlib-only generator there, and publish live files only after it succeeds.

## Validation

`python3 tests/test_variants.py` passes 118 tests (3 skipped).
