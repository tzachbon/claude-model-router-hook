# Design: Stage Manual Variant Installation

## Target Files

- `plugins/claude-model-router-hook/install.sh` — stage variant generation before publishing any live installer output.
- `tests/test_variants.py` — cover the full failure invariant and successful preservation in `TestInstallScript`.

## Installer Data Flow

Keep the existing strict shell mode. Before any operation on `$HOME/.claude`, create an external staging directory and register cleanup:

```bash
STAGE="$(mktemp -d)"
trap 'rm -rf -- "$STAGE"' EXIT
STAGED_AGENTS="$STAGE/agents"
mkdir -p "$STAGED_AGENTS"
if [ -d "$AGENTS_DIR" ]; then
    cp -R "$AGENTS_DIR/." "$STAGED_AGENTS/"
fi
```

The `source/.` form copies the agents directory's contents, including dotfiles, nested files, and unrelated user agents, without creating an `agents/agents` subtree. All paths remain quoted. Run the existing generator unchanged against `"$STAGED_AGENTS"` with `--use-user-config`; it continues to resolve user configuration normally while writing only staging.

Only after the generator exits zero, publish in this order:

1. Create live hooks and schema directories, replace the router package, and copy the four entrypoints.
2. Copy the schema.
3. Replace the live agents directory last with the complete staged tree: `rm -rf -- "$AGENTS_DIR"` followed by `cp -R "$STAGED_AGENTS" "$AGENTS_DIR"`.

Using a copy rather than `mv` avoids assuming the temporary directory shares a filesystem with the live install. No new helper, dependency, generator change, or rollback framework is introduced.

## Failure and Publishing Semantics

If staging copy or generation fails, `set -e` exits non-zero and the EXIT trap removes staging. Because no live `mkdir`, `rm`, or `cp` has run, the live hooks, entrypoints, schema, and complete agents tree stay byte-for-byte and existence-for-existence unchanged, including paths that were initially absent. The success report is not printed.

After generation succeeds, live copies remain deliberately sequential. A later publish failure has no new all-or-nothing or rollback guarantee; this change scopes atomicity only to variant-generation failure.

## Test Strategy

In `TestInstallScript`, upgrade the conflict regression to the validated full-tree snapshot: seed router and entrypoint sentinels, a schema sentinel, an unrelated user agent, hidden or nested unrelated agent content, a handwritten `routed-haiku.md` conflict, and a stale generated variant. Snapshot every relative directory and every file's binary content under `.claude`, run the manual installer, require a non-zero conflict result, and assert exact snapshot equality.

Extend the existing successful-install case by pre-seeding unrelated agent content (including a hidden-path sentinel) and asserting its path and bytes remain after generated variants are promoted. Retain the configured generated-agent assertion. Run `python3 tests/test_variants.py`.
