"""Single canonical taxonomy/advisory text (FR-17, FR-42, AC-11.1).

The advisory table is rendered from the resolved class targets, through the
same policy.target_for_class the router itself uses to pick a model. A session
is therefore never told a model the config does not declare.

ADVISORY_MD is that same table rendered from DEFAULTS. It is the committed-doc
form that scripts/sync_docs.py injects between the <!-- advisory:start --> /
<!-- advisory:end --> markers, so the checked-in docs never depend on a local
config. Edit the row copy in CLASS_ROWS here, nowhere else.
"""

import textwrap

from .config import DEFAULTS
from .policy import target_for_class

# Per-class "When to use" copy; tuple order is the table row order. The model
# and effort columns are not copy: they come from the resolved config target.
CLASS_ROWS = (
    (
        "mechanical",
        "Git ops, renames, formatting, lint, file moves, version bumps, "
        "quick lookups, short imperative tasks.",
    ),
    (
        "implementation",
        "Writing or editing code, building features, creating components or "
        "APIs, writing tests, standard feature work.",
    ),
    (
        "debugging",
        "Diagnosing failures, flaky tests, races, regressions, stack traces, "
        "bisecting, reproducing bugs.",
    ),
    (
        "architecture",
        "Architecture decisions, tradeoff analysis, redesigns, deep multi-file "
        "analysis, sustained reasoning over large context.",
    ),
    (
        "extreme",
        "Multi-system migrations, codebase-wide rewrites, long-horizon plans, "
        "RFCs and design docs, platform-scale work.",
    ),
)

# abstain is not a routable class, so it carries no configurable target.
ABSTAIN_ROW = (
    "| abstain | (no routing) | - | Prompt does not clearly match any class; "
    "current model and effort pass through unmodified. |"
)

# Wrap width for the closing paragraph, chosen so the DEFAULTS rendering
# reproduces the previously hard-coded line breaks byte for byte.
WRAP_WIDTH = 79

_HEADER = (
    "## Model Tier Rules\n"
    "\n"
    "These rules apply to YOU and to every sub-agent you spawn.\n"
    "\n"
    "### Task classes and default targets\n"
    "\n"
    "| Class | Target model | Effort | When to use |\n"
    "|---|---|---|---|\n"
)

_SELECTION_HEADER = "\n### Sub-agent model selection (MANDATORY)\n\n"

_SELECTION_LEAD = (
    "When calling the Agent tool, set the model parameter to match the task "
    "class above."
)

# Clause per class for the closing sentence. A class the router will not route
# contributes no clause, so the prose never names a model for it.
_SELECTION_CLAUSES = (
    ("mechanical", "mechanical work goes to "),
    ("implementation", "implementation to "),
    ("debugging", "debugging to "),
    ("architecture", "deep analysis to "),
    ("extreme", "platform-scale work to "),
)

_SELECTION_NONE = (
    " No class is routable under this config, so the current model and effort "
    "pass through unmodified."
)

# Rendered in the model and effort columns for a class the router refuses to
# route. Matches the abstain row, which describes the same outcome.
UNROUTABLE_MODEL = "(no routing)"
UNROUTABLE_EFFORT = "-"


def resolved_targets(cfg=None):
    """Map class name -> (model, effort), or None where the class is unroutable.

    Resolution goes through policy.target_for_class, the same function
    enforcement calls, so the advertised table and the routing decision cannot
    disagree. A target enforcement refuses is reported as unroutable rather
    than quietly replaced by a shipped default: substituting one would
    advertise a model the config does not declare and a decision the hook will
    never make, which is the exact split this module exists to close.

    cfg None or not a dict renders the shipped defaults, which is the
    committed-doc form. Never raises.
    """
    if not isinstance(cfg, dict):
        cfg = DEFAULTS
    targets = {}
    for klass, _when in CLASS_ROWS:
        try:
            decision = target_for_class(klass, cfg)
        except Exception:
            decision = None
        targets[klass] = None if decision is None else (decision.model, decision.effort)
    return targets


def _closing_paragraph(targets):
    """The MANDATORY paragraph, naming only classes the router will route."""
    clauses = [
        prefix + targets[klass][0]
        for klass, prefix in _SELECTION_CLAUSES
        if targets.get(klass)
    ]
    if not clauses:
        return _SELECTION_LEAD + _SELECTION_NONE

    if len(clauses) == 1:
        joined = clauses[0]
    elif len(clauses) == 2:
        joined = clauses[0] + " and " + clauses[1]
    else:
        joined = ", ".join(clauses[:-1]) + ", and " + clauses[-1]
    return (
        _SELECTION_LEAD
        + " Do not default every sub-agent to the highest effort. Match the "
        + "model and effort to the work: "
        + joined
        + "."
    )


def render_advisory(cfg=None):
    """Render the advisory markdown for a resolved config (DEFAULTS when None)."""
    targets = resolved_targets(cfg)

    rows = []
    for klass, when in CLASS_ROWS:
        target = targets[klass]
        model = target[0] if target else UNROUTABLE_MODEL
        effort = (target[1] or "none") if target else UNROUTABLE_EFFORT
        rows.append(
            "| {klass} | {model} | {effort} | {when} |".format(
                klass=klass, model=model, effort=effort, when=when
            )
        )
    rows.append(ABSTAIN_ROW)

    return (
        _HEADER
        + "\n".join(rows)
        + "\n"
        + _SELECTION_HEADER
        + textwrap.fill(_closing_paragraph(targets), width=WRAP_WIDTH)
        + "\n"
    )


# Committed-doc form: the table exactly as the shipped defaults describe it.
ADVISORY_MD = render_advisory()


# Per-tier hint: a lead sentence plus clauses that each name one class target.
# A clause whose class is unroutable is dropped rather than rendered with a
# substituted default, for the same reason the table reports it unroutable.
_TIER_HINTS = (
    (
        "fable",
        "You are currently on fable. Reserve it for extreme, platform-scale "
        "work; route everything lighter down the ladder.",
        (),
    ),
    (
        "opus",
        "You are currently on opus.",
        (
            ("mechanical", "for mechanical tasks {model} is cheaper"),
            ("implementation", "for standard implementation {model} suffices"),
        ),
    ),
    (
        "sonnet",
        "You are currently on sonnet.",
        (
            ("mechanical", "for mechanical tasks {model} is cheaper"),
            ("architecture", "for architecture or deep analysis {model} is better"),
        ),
    ),
    (
        "haiku",
        "You are currently on haiku.",
        (
            ("implementation", "for implementation work prefer {model}"),
            ("architecture", "for deep analysis or architecture prefer {model}"),
        ),
    ),
)

DIVERGENCE_HEADER = "\n### Routed variants out of date\n\n"

DIVERGENCE_BODY = (
    "This config declares routed subagent variants with no agent file "
    "installed: {names}. Spawns that would use them fall back to injecting the "
    "model alone, which leaves their effort advisory only. Re-run install.sh "
    "to generate the missing variants."
)


def _tier_hint(current_model, targets):
    """The "Your own tier" sentence for the session's current model."""
    model = str(current_model or "unknown")
    lower = model.lower()
    for tier, lead, clauses in _TIER_HINTS:
        if tier not in lower:
            continue
        if tier == "fable" and not any(targets.values()):
            return "You are currently on fable."
        rendered = [
            template.format(model=targets[klass][0])
            for klass, template in clauses
            if targets.get(klass)
        ]
        if not rendered:
            return lead
        rendered[0] = rendered[0][0].upper() + rendered[0][1:]
        return lead + " " + "; ".join(rendered) + "."
    return "Current model: " + model + "."


def render_session_context(current_model, cfg=None, missing_variants=()):
    """Return SessionStart additionalContext text for the resolved config.

    missing_variants names declared variants with no agent file installed; a
    non-empty list appends a section telling the user how to fix it, rather
    than letting spawns degrade to model-only injection silently.
    """
    targets = resolved_targets(cfg)
    context = (
        render_advisory(cfg)
        + "\n### Your own tier\n\n"
        + _tier_hint(current_model, targets)
        + "\n"
    )
    if missing_variants:
        context += (
            DIVERGENCE_HEADER
            + textwrap.fill(
                DIVERGENCE_BODY.format(names=", ".join(sorted(missing_variants))),
                width=WRAP_WIDTH,
            )
            + "\n"
        )
    return context
