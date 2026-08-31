# Plan: Truthful advisory prose

## Scope

Keep advisory prose derived from resolved routable targets. Retain the already-correct `debugging` selection clause from `f687111` and add its regression. Suppress the Fable down-ladder instruction when no resolved target is routable.

## Excluded scope

- Reworking the advisory table or routing policy.
- A separate debugging-clause implementation fix.

## Target files

- `plugins/claude-model-router-hook/hooks/router/advisory.py`
- `tests/test_variants.py`

## Minimal approach

Gate the static Fable tier hint on the resolved target set rather than raw configuration. Add focused table/prose assertions; leave `_SELECTION_CLAUSES` unchanged unless evidence shows the existing `debugging` clause regressed.

## Acceptance checks

- A debugging-only routable configuration renders `debugging to opus` consistently with its table.
- An all-unroutable configuration emits no Fable routing/down-ladder instruction.
- `python3 -m unittest tests.test_variants` passes.

## Ordering and dependencies

Independent; it can ship at any point.
