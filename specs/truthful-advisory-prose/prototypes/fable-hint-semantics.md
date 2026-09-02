---
spec: "truthful-advisory-prose"
phase: "prototype"
id: "fable-hint-semantics"
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
created: "2026-08-31T12:26:33Z"
completed: "2026-08-31T12:29:55Z"
sourceDisposition: "retained"
evidenceHash: "8a717f62871d13031b4b11cb52f1a5ee35e8dc24f01f754e9c9e4b09889189f7"
cleanupReceiptHash: null
staleArtifacts: []
staleTaskIndexes: []
supersedes: []
conflictsWith: []
resolves: []
resolvedAt: "2026-08-31T12:29:55Z"
isolationBranch: "prototype/truthful-advisory-prose/fable-hint-semantics"
isolationPath: "/root/.codex/worktrees/fad3/prototype-truthful-advisory-prose-fable-hint-semantics"
sourcePointers: ["tests/test_variants.py"]
---

## Question

Can the existing advisory test seam distinguish all-unroutable Fable prose from partially routable Fable prose while retaining debugging-only consistency?

## Blocking Declaration

Design needed a direct regression shape that distinguishes the false all-unroutable instruction from valid partially-routable Fable guidance.

## Isolation

Retained isolated worktree on local branch `prototype/truthful-advisory-prose/fable-hint-semantics`, based on `e02f329db146691f928bbefe6e74d3955bed4ea5`; no dirty primary-worktree paths were transferred.

## Run Instructions

From the isolated worktree, run the three new `TestAdvisoryMatchesEnforcement` tests, then `python3 tests/test_variants.py`.

## Cases Or Variants

Use a debugging-only config, all-unroutable `classes: null` Fable context, and partially routable debugging-only Fable context.

## Evidence And Observations

The all-unroutable Fable test fails on current code because the static lead directs lighter work down the ladder. Debugging-only and partially routable Fable checks pass. Full suite has 122 tests with exactly the intentional failure and 3 permission-related skips. `git diff --check` passes. The isolated source diff SHA-256 is `8a717f62871d13031b4b11cb52f1a5ee35e8dc24f01f754e9c9e4b09889189f7`.

## Verdict

Validated. Existing advisory tests express the exact predicate boundary without a new framework.

## Downstream Handoff

Port the three regressions. In `_tier_hint()`, suppress only the static Fable routing directive when no resolved target exists; retain factual Fable identification and retain existing guidance when any target resolves.

## Conflict Resolution

No competing prototype record affects this blocker.

## Staleness

No upstream artifact is stale.

## Source Disposition

Retained locally in the recorded worktree and local branch; no remote pointer was created or authorized.
