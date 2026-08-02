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

_SELECTION_BODY = (
    "When calling the Agent tool, set the model parameter to match the task "
    "class above. Never default all sub-agents to {architecture}. Match the "
    "model to the work: mechanical work goes to {mechanical}, standard coding "
    "to {implementation}, deep analysis to {architecture}, and only "
    "platform-scale efforts to {extreme}."
)


def resolved_targets(cfg=None):
    """Map class name -> (model, effort) for every advisory row.

    Resolution goes through policy.target_for_class so the advertised table and
    the router's actual choice cannot drift. Never raises: cfg None, a config
    missing a class, or a class whose target is unusable all fall back to the
    shipped DEFAULTS target for that class.
    """
    targets = {}
    for klass, _when in CLASS_ROWS:
        decision = None
        if isinstance(cfg, dict):
            try:
                decision = target_for_class(klass, cfg)
            except Exception:
                decision = None
        if decision is None:
            default = DEFAULTS["classes"][klass]["target"]
            targets[klass] = (default["model"], default.get("effort"))
        else:
            targets[klass] = (decision.model, decision.effort)
    return targets


def render_advisory(cfg=None):
    """Render the advisory markdown for a resolved config (DEFAULTS when None)."""
    targets = resolved_targets(cfg)

    rows = [
        "| {klass} | {model} | {effort} | {when} |".format(
            klass=klass,
            model=targets[klass][0],
            effort=targets[klass][1] or "none",
            when=when,
        )
        for klass, when in CLASS_ROWS
    ]
    rows.append(ABSTAIN_ROW)

    body = _SELECTION_BODY.format(
        **{klass: target[0] for klass, target in targets.items()}
    )
    return (
        _HEADER
        + "\n".join(rows)
        + "\n"
        + _SELECTION_HEADER
        + textwrap.fill(body, width=WRAP_WIDTH)
        + "\n"
    )


# Committed-doc form: the table exactly as the shipped defaults describe it.
ADVISORY_MD = render_advisory()


def render_session_context(current_model, cfg=None):
    """Return SessionStart additionalContext text for the resolved config."""
    targets = resolved_targets(cfg)
    mechanical = targets["mechanical"][0]
    implementation = targets["implementation"][0]
    architecture = targets["architecture"][0]

    model = str(current_model or "unknown")
    lower = model.lower()
    if "fable" in lower:
        hint = (
            "You are currently on fable. Reserve it for extreme, "
            "platform-scale work; route everything lighter down the ladder."
        )
    elif "opus" in lower:
        hint = (
            "You are currently on opus. For mechanical tasks "
            + mechanical
            + " is cheaper; for standard implementation "
            + implementation
            + " suffices."
        )
    elif "sonnet" in lower:
        hint = (
            "You are currently on sonnet. For mechanical tasks "
            + mechanical
            + " is cheaper; for architecture or deep analysis "
            + architecture
            + " is better."
        )
    elif "haiku" in lower:
        hint = (
            "You are currently on haiku. For implementation work prefer "
            + implementation
            + "; for deep analysis or architecture prefer "
            + architecture
            + "."
        )
    else:
        hint = "Current model: " + model + "."
    return render_advisory(cfg) + "\n### Your own tier\n\n" + hint + "\n"
