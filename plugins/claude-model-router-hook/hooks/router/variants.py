"""Routed subagent variants, derived from the configured class targets (FR-14).

The PreToolUse hook and scripts/generate_variants.py both build their variant
set here, so the variants a session can be rewritten to and the agent files on
disk are always the same set. Nothing names a model literally: a config that
never targets a tier produces no variant for it, and the generator writes no
agent file for it.

The set is the closure of the class targets under the gates, not the raw
targets: policy.gate_outcomes reports every (model, effort) apply_gates can
synthesize, so a gate bump or an effort floor never lands on a pair with no
agent file behind it.

Ownership of a generated file is declared, not inferred. Files carry a
`router-generated: true` frontmatter key, and only files carrying it (or byte
matching a pre-key rendering) are ever overwritten or pruned.
"""

import os
import re

from .ladder import EFFORTS, TIERS
from .policy import gate_outcomes, target_for_class
from .taxonomy import CLASSES

AGENT_PREFIX = "routed-"

OWNERSHIP_KEY = "router-generated"

AGENT_DESCRIPTION = (
    "Router-managed variant for {classes} tasks. "
    "Spawned by the model router hook; do not invoke directly."
)

# A variant no class targets directly, reachable only by a gate bump or an
# effort floor. Naming the reaching classes would list nearly all of them.
AGENT_DESCRIPTION_ESCALATED = (
    "Router-managed variant for gate-escalated tasks. "
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

    Ordered by taxonomy.CLASSES. `classes` names the classes whose declared
    target is this pair, and is empty for a variant that exists only as a gate
    escalation. Never raises: an unroutable class contributes nothing, exactly
    as the router routes nothing for it.
    """
    ordered = []
    declared_by = {}
    for klass in CLASSES:
        declared = None
        try:
            target = target_for_class(klass, cfg)
            if target is not None:
                declared = (target.model, target.effort)
        except Exception:
            declared = None
        for pair in gate_outcomes(klass, cfg):
            if pair not in declared_by:
                declared_by[pair] = []
                ordered.append(pair)
            if pair == declared and klass not in declared_by[pair]:
                declared_by[pair].append(klass)
    return [
        (variant_name(model, effort), model, effort, tuple(declared_by[(model, effort)]))
        for model, effort in ordered
    ]


def variant_map(cfg):
    """(model, effort) -> agent name for every variant the config declares."""
    return {
        (model, effort): name for name, model, effort, _classes in target_variants(cfg)
    }


def agent_markdown(name, model, effort, classes):
    """Full agent file content for one variant."""
    if classes:
        description = AGENT_DESCRIPTION.format(classes=_join(list(classes)))
    else:
        description = AGENT_DESCRIPTION_ESCALATED
    lines = [
        "---",
        "name: " + name,
        "description: " + description,
        "model: " + model,
    ]
    if effort is not None:
        lines.append("effort: " + effort)
    lines += [OWNERSHIP_KEY + ": true", "---", "", AGENT_BODY, ""]
    return "\n".join(lines)


def _legacy_markdown(name, model, effort, classes):
    """The rendering shipped before the ownership key existed."""
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


# Shape of the pre-key rendering. Used only to recover the (name, model,
# effort, classes) tuple a candidate file claims; the claim is then re-rendered
# and compared byte for byte, so matching this pattern proves nothing on its own.
_LEGACY_RE = re.compile(
    r"^---\n"
    r"name: (?P<name>[^\n]+)\n"
    r"description: Router-managed variant for (?P<classes>[^\n]+) tasks\. "
    r"Spawned by the model router hook; do not invoke directly\.\n"
    r"model: (?P<model>[^\n]+)\n"
    r"(?:effort: (?P<effort>[^\n]+)\n)?"
    r"---\n\n" + re.escape(AGENT_BODY) + r"\n$"
)


def _split_classes(joined):
    """Reverse _join, or None when the text is not a list of routable classes."""
    if " and " not in joined:
        parts = [joined]
    else:
        head, _sep, last = joined.rpartition(" and ")
        parts = ([p for p in head.split(", ")] if head else []) + [last]
    parts = [p for p in parts if p]
    if not parts or any(p not in CLASSES for p in parts):
        return None
    return tuple(parts)


def is_generated(text, filename=None):
    """True when this generator wrote the file, by declaration or byte equality.

    Two accepted proofs:
      - a `router-generated: true` key in the frontmatter block
      - byte equality with the pre-key rendering of the exact variant the file
        claims to be, for files written before the key existed (upgrade path)

    The second proof reads the claimed (name, model, effort, classes) out of
    the file, rejects any tuple this generator could not have emitted (a model
    outside the ladder, an effort outside the scale, an effort on haiku, a
    class list that is not routable classes, a name that is not the variant
    name for that pair or does not match the filename), re-renders it, and
    compares the whole file. Matching the shape is not enough: a hand-written
    agent that keeps the boilerplate body but names its own model is foreign,
    and is never overwritten or pruned.
    """
    if not isinstance(text, str):
        return False
    if _frontmatter_flag(text):
        return True

    match = _LEGACY_RE.match(text)
    if match is None:
        return False
    model = match.group("model")
    effort = match.group("effort")
    if model not in TIERS:
        return False
    if model == "haiku":
        if effort is not None:
            return False
    elif effort not in EFFORTS:
        return False
    classes = _split_classes(match.group("classes"))
    if classes is None:
        return False

    name = match.group("name")
    if name != variant_name(model, effort):
        return False
    if filename is not None:
        if name != os.path.splitext(os.path.basename(filename))[0]:
            return False
    return text == _legacy_markdown(name, model, effort, classes)


def _frontmatter_flag(text):
    """True when the leading frontmatter block declares the ownership key."""
    if not text.startswith("---\n"):
        return False
    end = text.find("\n---", 3)
    if end == -1:
        return False
    for line in text[4:end].split("\n"):
        key, _sep, value = line.partition(":")
        if key.strip() == OWNERSHIP_KEY and value.strip().lower() == "true":
            return True
    return False


def installed_names(agent_dirs):
    """Variant names present as agent files across the given directories."""
    found = set()
    for directory in agent_dirs:
        if not directory:
            continue
        try:
            entries = os.listdir(directory)
        except OSError:
            continue
        for entry in entries:
            if entry.startswith(AGENT_PREFIX) and entry.endswith(".md"):
                found.add(entry[:-3])
    return found


def missing_variants(cfg, agent_dirs):
    """Declared variant names with no agent file in any of agent_dirs.

    Non-empty means the installed set is behind the config: the config was
    edited after install, or a project config declares a target the global
    install never saw.
    """
    installed = installed_names(agent_dirs)
    return [
        name for name, _m, _e, _c in target_variants(cfg) if name not in installed
    ]
