---
spec: "stage-manual-variant-install"
phase: "prototype"
id: "staged-tree-promotion"
status: "terminal"
verdict: "validated"
kind: "logic"
captureMode: "retained"
triggerMode: "quick"
triggerPhase: "requirements"
returnPhase: "design"
returnTaskIndex: 0
decisionOwner: "quick"
resolutionMode: "quick"
gateApproved: true
created: "2026-08-31T11:39:58Z"
completed: "2026-08-31T11:43:54Z"
sourceDisposition: "retained"
evidenceHash: "a32aed98c472c67c5f6f8415886fcb9cf3c8dd134d569c22ab22511f3081bfb5"
cleanupReceiptHash: null
staleArtifacts: []
staleTaskIndexes: []
supersedes: []
conflictsWith: []
resolves: []
resolvedAt: "2026-08-31T11:43:54Z"
isolationBranch: "prototype/stage-manual-variant-install/staged-tree-promotion"
isolationPath: "/root/.codex/worktrees/fad3/prototype-stage-manual-variant-install-staged-tree-promotion"
sourcePointers: ["tests/test_variants.py"]
---

## Question

Can a copied full agents tree prove generator failure leaves all live installer paths unchanged while successful promotion preserves an unrelated agent?

## Blocking Declaration

Design needed a concrete, framework-free regression that covers all live installer outputs before selecting staging and promotion commands.

## Isolation

Retained isolated worktree on local branch `prototype/stage-manual-variant-install/staged-tree-promotion`, based on `c4aae854f0eb27c29a774234e8650614f600d26c`; no dirty primary-worktree paths were transferred.

## Run Instructions

From the isolated worktree, run `python3 tests/test_variants.py TestInstallScript.test_generator_failure_leaves_the_live_tree_unchanged`, then `python3 tests/test_variants.py`.

## Cases Or Variants

Seed sentinel router, four entrypoints, schema, unrelated agent, handwritten `routed-haiku.md`, and stale generated `routed-fable-high.md`; snapshot all live `.claude` file bytes; invoke the manual installer and require non-zero plus exact snapshot equality.

## Evidence And Observations

The focused test fails against the current installer because generation conflict happens after live hooks are replaced and later agents are mutated. Full suite: 119 tests with exactly the intentional new failure and 3 permission-related skips. `git diff --check` passes. The isolated source diff SHA-256 is `a32aed98c472c67c5f6f8415886fcb9cf3c8dd134d569c22ab22511f3081bfb5`.

## Verdict

Validated. Existing `TestInstallScript` can prove the full live-tree invariant without a new test framework or production abstraction.

## Downstream Handoff

Add this regression to `tests/test_variants.py`; stage a full copied agents tree before any live mutation, run the existing generator there, and promote it only on success. Add a success case proving an unrelated agent is preserved.

## Conflict Resolution

No competing prototype record affects the design blocker.

## Staleness

No upstream artifact is stale.

## Source Disposition

Retained locally in the recorded worktree and local branch; no remote pointer was created or authorized.
