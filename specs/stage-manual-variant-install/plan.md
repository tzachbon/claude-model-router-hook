# Plan: Stage manual variant install

## Scope

Make the plugin's manual installer run variant generation against a temporary copy of the agents tree, retaining unrelated user agents. Replace live router/hooks/entrypoints, staged agents, and schema only after generation succeeds.

## Excluded scope

- Atomicity for failures outside variant generation.
- A generic rollback or transaction framework.

## Target files

- `plugins/claude-model-router-hook/install.sh`
- `tests/test_variants.py` (`TestInstallScript`)

## Minimal approach

Use the shell's existing temporary-directory and copy tools to stage the current agents tree, invoke the existing generator there, and discard staging on non-zero exit. Keep the current live replacement path after successful generation.

## Acceptance checks

- A generator conflict leaves live hooks, schema, router files, and agents byte-for-byte unchanged.
- Successful installation promotes the generated staged agents and preserves unrelated user agents.
- `python3 -m unittest tests.test_variants.TestInstallScript` passes.

## Ordering and dependencies

Independently shippable; recommended after `safe-variant-agent-paths` so the staging regression also exercises conservative path rejection.
