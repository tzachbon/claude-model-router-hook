#!/usr/bin/env python3
"""Eval harness for the v2 router (FR-38, FR-39, AC-10.2/10.4).

Imports the real router.taxonomy + router.policy (no logic reimplementation)
and runs every labeled row in eval_set.jsonl with the CLI fallback forced off,
so the run is deterministic and offline (NFR-10). Reports per-class accuracy,
a confusion matrix, and the tier distribution, then enforces the collapse gates.

Exit 1 (not a crash) is the expected signal when a gate fails; that is how CI
flags a regression. Exit 0 means every gate held.
"""

import collections
import copy
import json
import os
import sys
import time

# Same sys.path bootstrap as tests/test_router.py: make hooks/ importable.
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "..",
        "plugins", "claude-model-router-hook", "hooks",
    ),
)
from router import policy, taxonomy  # noqa: E402
from router.config import DEFAULTS  # noqa: E402
from router.ladder import MODEL_IDS, TIERS  # noqa: E402

# Collapse gates, finalized against the task-4.3 baseline (95% accuracy, 57/60).
# The eval set is deliberately class-balanced (10 rows per class), so tier shares
# reflect class balance, not production traffic: with all 10 extreme rows routed
# correctly, fable is ~19% of the ~52 non-abstain decisions and opus+fable ~40%
# (architecture + extreme = 2 of 6 classes). The provisional 0.10 / 0.40 ceilings
# were pre-baseline guesses below those structural floors and are unreachable on a
# balanced set. Finalized values sit just above the floors: they still catch a real
# regression (architecture leaking into extreme, or over-routing to opus/fable)
# without failing on the set's built-in class balance. Do not tighten blindly.
ACCURACY_MIN = 0.90       # min overall classification accuracy (baseline 0.95)
FABLE_SHARE_MAX = 0.25    # fable share of non-abstain decisions (baseline 0.192)
TOP_SHARE_MAX = 0.45      # opus + fable share of non-abstain decisions (baseline 0.404)
P95_MAX_MS = 200.0        # heuristic classify p95 wall time (NFR-1)

CLASS_ORDER = (
    "mechanical", "implementation", "debugging",
    "architecture", "extreme", "abstain",
)

EVAL_SET = os.path.join(os.path.dirname(__file__), "eval_set.jsonl")


def load_rows(path):
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def deterministic_cfg():
    """DEFAULTS copy with CLI fallback off: fully deterministic, offline."""
    cfg = copy.deepcopy(DEFAULTS)
    cfg.setdefault("classifier", {})["cli_fallback"] = False
    return cfg


def percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(pct * (len(ordered) - 1))
    return ordered[idx]


def run():
    cfg = deterministic_cfg()
    rows = load_rows(EVAL_SET)

    per_class_total = collections.Counter()
    per_class_correct = collections.Counter()
    confusion = collections.Counter()          # (expected, predicted) -> n
    model_counts = collections.Counter()       # decided tier -> n (non-abstain)
    times_ms = []
    mythos_emissions = 0
    non_abstain = 0
    correct = 0

    for row in rows:
        prompt = row.get("prompt", "")
        expected = row["expected_class"]

        start = time.perf_counter()
        predicted, _result = taxonomy.classify(prompt, cfg, "")
        times_ms.append((time.perf_counter() - start) * 1000.0)

        pred_label = predicted or "abstain"
        per_class_total[expected] += 1
        confusion[(expected, pred_label)] += 1
        if pred_label == expected:
            per_class_correct[expected] += 1
            correct += 1

        if predicted is not None:
            decision = policy.apply_gates(
                prompt, policy.target_for_class(predicted, cfg), cfg
            )
            if "mythos" in decision.model:
                mythos_emissions += 1
            model_counts[decision.model] += 1
            non_abstain += 1

    total = len(rows)
    accuracy = correct / total if total else 0.0
    p95_ms = percentile(times_ms, 0.95)
    fable_share = model_counts["fable"] / non_abstain if non_abstain else 0.0
    top_share = (
        (model_counts["opus"] + model_counts["fable"]) / non_abstain
        if non_abstain else 0.0
    )

    # ---- Report ----
    print("=== Router eval ({} rows, cli_fallback=false) ===".format(total))
    print()
    print("Per-class accuracy:")
    for cls in CLASS_ORDER:
        n = per_class_total.get(cls, 0)
        if not n:
            continue
        acc = per_class_correct.get(cls, 0) / n
        print("  {:<14} {:>3}/{:<3}  {:.2%}".format(
            cls, per_class_correct.get(cls, 0), n, acc))
    print("  {:<14} {:>3}/{:<3}  {:.2%}".format("OVERALL", correct, total, accuracy))
    print()

    print("Confusion matrix (row = expected, col = predicted):")
    header = "  {:<14}".format("") + "".join("{:>8}".format(c[:7]) for c in CLASS_ORDER)
    print(header)
    for exp in CLASS_ORDER:
        if not per_class_total.get(exp, 0):
            continue
        cells = "".join(
            "{:>8}".format(confusion.get((exp, pred), 0)) for pred in CLASS_ORDER
        )
        print("  {:<14}".format(exp) + cells)
    print()

    print("Tier distribution (non-abstain decisions = {}):".format(non_abstain))
    for tier in TIERS:
        n = model_counts.get(tier, 0)
        share = n / non_abstain if non_abstain else 0.0
        print("  {:<8} {:>3}  {:.2%}".format(tier, n, share))
    print()

    print("Timing: heuristic classify p95 = {:.2f} ms (max {:.0f})".format(
        p95_ms, P95_MAX_MS))
    print()

    # ---- Mythos invariant (FR-2): zero emissions, ever ----
    for tier in TIERS:
        assert "mythos" not in tier, tier
    for model_id in MODEL_IDS.values():
        assert "mythos" not in model_id, model_id
    assert mythos_emissions == 0, "mythos decision emitted: {}".format(mythos_emissions)

    # ---- Gates ----
    failures = []
    if accuracy < ACCURACY_MIN:
        failures.append(
            "accuracy {:.2%} < ACCURACY_MIN {:.2%}".format(accuracy, ACCURACY_MIN))
    if fable_share > FABLE_SHARE_MAX:
        failures.append(
            "fable share {:.2%} > FABLE_SHARE_MAX {:.2%}".format(
                fable_share, FABLE_SHARE_MAX))
    if top_share > TOP_SHARE_MAX:
        failures.append(
            "opus+fable share {:.2%} > TOP_SHARE_MAX {:.2%}".format(
                top_share, TOP_SHARE_MAX))
    if p95_ms >= P95_MAX_MS:
        failures.append(
            "p95 {:.2f}ms >= P95_MAX_MS {:.0f}ms".format(p95_ms, P95_MAX_MS))

    if failures:
        print("GATES FAILED:")
        for f in failures:
            print("  - " + f)
        return 1

    print("GATES PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
