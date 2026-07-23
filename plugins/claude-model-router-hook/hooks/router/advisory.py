"""Single canonical taxonomy/advisory text (FR-17, FR-42, AC-11.1).

ADVISORY_MD is the only source of the taxonomy table. Every other surface
(session-init additionalContext, prompt.md, README) is generated from it by
scripts/sync_docs.py via <!-- advisory:start/end --> markers or asserted
equal by tests. Edit the table here, nowhere else.
"""

ADVISORY_MD = """\
## Model Tier Rules

These rules apply to YOU and to every sub-agent you spawn.

### Task classes and default targets

| Class | Target model | Effort | When to use |
|---|---|---|---|
| mechanical | haiku | none | Git ops, renames, formatting, lint, file moves, version bumps, quick lookups, short imperative tasks. |
| implementation | sonnet | medium | Writing or editing code, building features, creating components or APIs, writing tests, standard feature work. |
| debugging | sonnet | high | Diagnosing failures, flaky tests, races, regressions, stack traces, bisecting, reproducing bugs. |
| architecture | opus | high | Architecture decisions, tradeoff analysis, redesigns, deep multi-file analysis, sustained reasoning over large context. |
| extreme | fable | high | Multi-system migrations, codebase-wide rewrites, long-horizon plans, RFCs and design docs, platform-scale work. |
| abstain | (no routing) | - | Prompt does not clearly match any class; current model and effort pass through unmodified. |

### Sub-agent model selection (MANDATORY)

When calling the Agent tool, set the model parameter to match the task class
above. Never default all sub-agents to opus. Match the model to the work:
mechanical work goes to haiku, standard coding to sonnet, deep analysis to
opus, and only platform-scale efforts to fable.
"""


def render_session_context(current_model):
    """Return SessionStart additionalContext text embedding ADVISORY_MD."""
    model = str(current_model or "unknown")
    lower = model.lower()
    if "fable" in lower:
        hint = (
            "You are currently on fable. Reserve it for extreme, "
            "platform-scale work; route everything lighter down the ladder."
        )
    elif "opus" in lower:
        hint = (
            "You are currently on opus. For mechanical tasks haiku is "
            "cheaper; for standard implementation sonnet suffices."
        )
    elif "sonnet" in lower:
        hint = (
            "You are currently on sonnet. For mechanical tasks haiku is "
            "cheaper; for architecture or deep analysis opus is better."
        )
    elif "haiku" in lower:
        hint = (
            "You are currently on haiku. For implementation work prefer "
            "sonnet; for deep analysis or architecture prefer opus."
        )
    else:
        hint = "Current model: " + model + "."
    return ADVISORY_MD + "\n### Your own tier\n\n" + hint + "\n"
