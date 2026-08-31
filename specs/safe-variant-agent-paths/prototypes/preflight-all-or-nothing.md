---
spec: "safe-variant-agent-paths"
phase: "prototype"
id: "preflight-all-or-nothing"
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
created: "2026-08-31T10:32:11Z"
completed: "2026-08-31T10:38:36Z"
sourceDisposition: "retained"
evidenceHash: "844d10bac63d13f60b7849386f193736995e72116318892d1cee969d769b6c68"
cleanupReceiptHash: null
staleArtifacts: []
staleTaskIndexes: []
supersedes: []
conflictsWith: []
resolves: []
resolvedAt: "2026-08-31T10:38:36Z"
isolationBranch: "prototype/safe-variant-agent-paths/preflight-all-or-nothing"
isolationPath: "/root/.codex/worktrees/fad3/prototype-safe-variant-agent-paths-preflight-all-or-nothing"
sourcePointers: ["tests/test_variants.py"]
---

## Question

Can the existing variants test seam prove that an unsafe routed-agent candidate prevents every sibling mutation?

## Blocking Declaration

Design needs a concrete, framework-free regression seam for the all-or-nothing preflight rule before it can prescribe the smallest safe implementation.

## Isolation

Retained isolated worktree on a local prototype branch based on the recorded HEAD; no dirty primary-worktree path was transferred.

## Run Instructions

Run the focused TestVariantGenerator symlink regression, then python3 tests/test_variants.py, from the isolated worktree.

## Cases Or Variants

A stale safe routed-haiku.md sits beside a wanted routed-opus-high.md symlink to a regular outside file. The safe sibling must remain byte-for-byte unchanged, the command must fail, and the symlink must remain a symlink.

## Evidence And Observations

The focused regression fails on the current implementation with unsafe wanted symlink changed safe sibling. The full test command reports 114 tests with that one expected pre-fix failure and two skips. The retained source diff SHA-256 is recorded in evidenceHash; git diff --check passes.

## Verdict

Validated. The existing subprocess unittest seam precisely expresses all-or-nothing preflight behavior; no test framework or production abstraction is needed.

## Downstream Handoff

Include this evidence in design. Preflight all wanted and stale routed candidates with non-following inspection, build actions only after every candidate passes, then apply updates/removals. Port the retained regression into implementation.

## Conflict Resolution

No competing live or terminal prototype record affects this blocker.

## Staleness

No upstream artifact is stale. The retained test is evidence only and is not merged into the primary worktree.

## Source Disposition

Retained locally in the recorded isolated worktree and local branch; no remote pointer was created or authorized.
