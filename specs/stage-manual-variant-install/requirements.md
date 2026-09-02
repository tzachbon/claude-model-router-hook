# Manual Variant Install Staging Requirements

## User Story

As a Claude user running the manual installer, I want variant generation to finish before any live installation files change, so a generation conflict cannot leave my installation partially updated.

## Functional Requirements

1. Before modifying any live Claude path, the manual installer stages a full copy of the existing agents tree and runs the existing variant generator against that staged tree with `--use-user-config`.
2. If variant generation exits non-zero, the installer exits non-zero and discards staging without publishing it.
3. If variant generation exits zero, the installer performs the current live hook, entrypoint, and schema installation, then promotes the staged agents tree. Generated staged variants become live and unrelated user agents remain unchanged.

## Acceptance Criteria

1. A generation failure leaves these live paths byte-for-byte and existence-for-existence unchanged:
   - `$HOME/.claude/hooks/router/`
   - `$HOME/.claude/hooks/session_init.py`
   - `$HOME/.claude/hooks/user_prompt_submit.py`
   - `$HOME/.claude/hooks/pre_tool_use.py`
   - `$HOME/.claude/hooks/post_tool_use.py`
   - `$HOME/.claude/schema/model-router.schema.json`
   - the entire `$HOME/.claude/agents/` tree, including an unrelated user agent, a handwritten routed conflict, and prior generated variants.
2. A successful generation promotes the staged generated agents while preserving every unrelated agent from the original live tree unchanged.
3. The failure regression is added at the direct seam: `tests/test_variants.py::TestInstallScript`. It snapshots the full `.claude` tree after seeding the listed paths, an unrelated agent, and `agents/routed-haiku.md`; the manual installer must fail and leave that snapshot identical.

## Non-Functional Requirements and Constraints

- The generator command, its ownership behavior, and user-config lookup remain unchanged.
- Use the existing shell and standard utilities; add no dependency and no generic transaction or rollback framework.
- Atomicity is required only for generator failure. A later failure while copying/publishing live files after successful generation has no new atomicity or rollback guarantee.

## Exclusions

- `tests/test-install.sh` is outside this change; it exercises the unrelated top-level wizard.

## Success Criteria and Validation

The installer passes the success and failure criteria above, with no partial live mutation caused by a variant-generation failure.

```bash
python3 tests/test_variants.py
```
