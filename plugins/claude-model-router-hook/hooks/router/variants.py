"""Routed subagent variants, derived from the configured class targets (FR-14).

The PreToolUse hook and scripts/generate_variants.py both build their variant
set here, so the variants a session can be rewritten to and the agent files on
disk are always the same set. Nothing names a model literally: a config that
never targets a tier produces no variant for it, and the generator writes no
agent file for it.
"""

from .policy import target_for_class
from .taxonomy import CLASSES

AGENT_PREFIX = "routed-"

AGENT_DESCRIPTION = (
    "Router-managed variant for {classes} tasks. "
    "Spawned by the model router hook; do not invoke directly."
)

AGENT_BODY = "Complete the delegated task exactly as prompted; return a concise report."


def variant_name(model, effort):
    """Agent name for a (model, effort) target. A haiku target carries no effort."""
    if effort is None:
        return AGENT_PREFIX + model
    return AGENT_PREFIX + model + "-" + effort


def _join(classes):
    """'a', 'a and b', or 'a, b and c' for the description line."""
    if len(classes) == 1:
        return classes[0]
    return ", ".join(classes[:-1]) + " and " + classes[-1]


def target_variants(cfg):
    """Variants the config declares, as (name, model, effort, classes) tuples.

    Ordered by taxonomy.CLASSES; two classes sharing one target collapse into a
    single variant carrying both class names. Never raises: a class whose
    target is unusable is skipped, exactly as the router skips it.
    """
    ordered = []
    index = {}
    for klass in CLASSES:
        target = None
        if isinstance(cfg, dict):
            try:
                target = target_for_class(klass, cfg)
            except Exception:
                target = None
        if target is None:
            continue
        key = (target.model, target.effort)
        if key in index:
            index[key].append(klass)
            continue
        index[key] = [klass]
        ordered.append(key)
    return [
        (variant_name(model, effort), model, effort, tuple(index[(model, effort)]))
        for model, effort in ordered
    ]


def variant_map(cfg):
    """(model, effort) -> agent name for every variant the config declares."""
    return {
        (model, effort): name for name, model, effort, _classes in target_variants(cfg)
    }


def agent_markdown(name, model, effort, classes):
    """Full agent file content for one variant, matching the shipped file shape."""
    lines = [
        "---",
        "name: " + name,
        "description: " + AGENT_DESCRIPTION.format(classes=_join(list(classes))),
        "model: " + model,
    ]
    if effort is not None:
        lines.append("effort: " + effort)
    lines += ["---", "", AGENT_BODY, ""]
    return "\n".join(lines)
