"""Config defaults, loading, and merging for the model router (v2 schema)."""

import copy
import json
import pathlib
import re

DEFAULTS = {
    "version": 2,
    "apply_mode": "warn",
    "allow_fable_autoswitch": False,
    "subagent_enforcement": "on",
    "classifier": {
        "cli_fallback": True,
        "cli_timeout_seconds": 8,
        "cache_max_entries": 1000,
    },
    "thresholds": {
        "confident_margin": 3,
        "downroute_margin": 4,
        "effort_warn_distance": 2,
        "mechanical_max_words": 60,
        "long_prompt_words": 200,
        "question_words": 100,
    },
    "classes": {
        "mechanical": {
            "mode": "extend",
            "keywords": [],
            "patterns": [],
            "remove_keywords": [],
            "remove_patterns": [],
            "target": {"model": "haiku"},
        },
        "implementation": {
            "mode": "extend",
            "keywords": [],
            "patterns": [],
            "remove_keywords": [],
            "remove_patterns": [],
            "target": {"model": "sonnet", "effort": "medium"},
        },
        "debugging": {
            "mode": "extend",
            "keywords": [],
            "patterns": [],
            "remove_keywords": [],
            "remove_patterns": [],
            "target": {"model": "sonnet", "effort": "high"},
        },
        "architecture": {
            "mode": "extend",
            "keywords": [],
            "patterns": [],
            "remove_keywords": [],
            "remove_patterns": [],
            "target": {"model": "opus", "effort": "high"},
        },
        "extreme": {
            "mode": "extend",
            "keywords": [],
            "patterns": [],
            "remove_keywords": [],
            "remove_patterns": [],
            "target": {"model": "fable", "effort": "high"},
        },
    },
    "capability_gates": {"mode": "extend", "patterns": [], "remove_patterns": []},
    "effort_floors": {
        "mode": "extend",
        "patterns": [],
        "remove_patterns": [],
        "floor": "high",
    },
}


def _read_json(path):
    """Read a JSON file; any failure returns {} (fail-open, AC-8.5)."""
    try:
        with open(path) as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


_V1_TIER_TO_CLASS = {
    "opus": "architecture",
    "sonnet": "implementation",
    "haiku": "mechanical",
}

_V1_THRESHOLD_RENAMES = {
    "opus_word_count": "long_prompt_words",
    "opus_question_word_count": "question_words",
    "haiku_max_word_count": "mechanical_max_words",
}


def detect_version(raw):
    """Structural version detection (FR-31).

    version == 2 -> 2; version absent with any v1 top-level key present -> 1;
    otherwise 2 (defaults).
    """
    if raw.get("version") == 2:
        return 2
    if "version" not in raw and any(
        key in raw for key in ("opus", "sonnet", "haiku", "thresholds", "action")
    ):
        return 1
    return 2


def migrate_v1(raw):
    """Migrate a v1-shaped config dict to v2 shape, in memory only (AC-8.2).

    Pure function: never writes files. Tier configs map to classes
    (opus->architecture, sonnet->implementation, haiku->mechanical),
    threshold keys are renamed, and v1's implicit warn-only behavior
    becomes an explicit apply_mode.
    """
    migrated = {"version": 2, "apply_mode": "warn"}

    # main's v1 "action" field (warn|autoswitch) maps to v2 apply_mode so
    # users who adopted it do not silently lose the setting on migration.
    if raw.get("action") in ("warn", "autoswitch"):
        migrated["apply_mode"] = raw["action"]

    classes = {}
    for tier, class_name in _V1_TIER_TO_CLASS.items():
        tier_config = raw.get(tier)
        if isinstance(tier_config, dict):
            classes[class_name] = {
                key: value
                for key, value in tier_config.items()
                if key in ("mode", "keywords", "patterns", "remove_keywords", "remove_patterns")
            }
    if classes:
        migrated["classes"] = classes

    thresholds = raw.get("thresholds")
    if isinstance(thresholds, dict):
        migrated["thresholds"] = {
            _V1_THRESHOLD_RENAMES.get(key, key): value
            for key, value in thresholds.items()
        }

    return migrated


def merge(base, overlay):
    """Merge overlay onto base with v1 semantics (FR-32, AC-8.4).

    Per-key override; dicts merged with a shallow spread; "$schema" skipped.
    "classes" is merged one level deeper so each class merges per class, and a
    class "target" dict is merged one level deeper still so a partial target
    override (e.g. only "effort") never drops the inherited "model".
    Returns a new dict; inputs are not mutated.
    """
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if key == "$schema":
            continue
        if (
            key == "classes"
            and isinstance(value, dict)
            and isinstance(result.get(key), dict)
        ):
            merged_classes = dict(result[key])
            for name, class_cfg in value.items():
                if isinstance(class_cfg, dict) and isinstance(
                    merged_classes.get(name), dict
                ):
                    merged_class = {**merged_classes[name], **class_cfg}
                    base_target = merged_classes[name].get("target")
                    overlay_target = class_cfg.get("target")
                    if isinstance(base_target, dict) and isinstance(
                        overlay_target, dict
                    ):
                        # Deep-merge target so a partial override keeps the base
                        # model/effort it did not explicitly replace.
                        merged_class["target"] = {**base_target, **overlay_target}
                    merged_classes[name] = merged_class
                else:
                    merged_classes[name] = class_cfg
            result[key] = merged_classes
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = {**result[key], **value}
        else:
            result[key] = value
    return result


def _load_file_as_v2(path):
    """Read one config file, detect its version, and migrate v1 to v2 shape."""
    raw = _read_json(path)
    if not raw:
        return {}
    if detect_version(raw) == 1:
        return migrate_v1(raw)
    return raw


def load_config(global_path=None, cwd=None):
    """Load global + project configs, merged onto DEFAULTS (project wins, AC-8.4).

    Each file is version-detected and migrated independently, then merged
    with v1 semantics via merge().

    Args:
        global_path: Override path for the global config file (for testing).
        cwd: Override working directory to search for project config (for testing).
    """
    config = copy.deepcopy(DEFAULTS)

    # Global config
    if global_path is None:
        global_path = pathlib.Path.home() / ".claude" / "model-router.json"
    else:
        global_path = pathlib.Path(global_path)
    if global_path.exists():
        config = merge(config, _load_file_as_v2(global_path))

    # Project config (walk up from CWD to find .claude/model-router.json)
    search_root = pathlib.Path(cwd) if cwd else pathlib.Path.cwd()
    for parent in [search_root, *search_root.parents]:
        project_path = parent / ".claude" / "model-router.json"
        if project_path.exists():
            config = merge(config, _load_file_as_v2(project_path))
            break

    return config


def resolve_list(class_cfg, field, defaults):
    """Resolve final keyword/pattern list for a class (v1 semantics, FR-33).

    mode "replace": use the class list as-is. Otherwise extend defaults with
    the class list, then drop entries named in remove_<field>.
    """
    if not isinstance(class_cfg, dict):
        class_cfg = {}
    mode = class_cfg.get("mode", "extend")

    if mode == "replace":
        return list(class_cfg.get(field) or [])

    # Extend mode
    result = list(defaults)
    result.extend(class_cfg.get(field) or [])

    # Remove specific entries
    for item in class_cfg.get("remove_" + field) or []:
        if item in result:
            result.remove(item)

    return result


def v1_hint_due(data_dir):
    """One-time v1 upgrade hint gate (AC-8.3).

    Returns True exactly once per data_dir, writing a marker file
    <data_dir>/v1-hint-shown. Unwritable or missing data_dir returns
    False (fail-open); user config files are never touched.
    """
    if not data_dir:
        return False
    try:
        marker = pathlib.Path(data_dir) / "v1-hint-shown"
        if marker.exists():
            return False
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("")
        return True
    except Exception:
        return False


def safe_regex_match(patterns, text):
    """Test if any pattern matches text, silently skipping invalid entries.

    Non-string entries (e.g. a numeric or null pattern in user config) are
    skipped rather than raised so one bad list item cannot disable routing.
    """
    for p in patterns:
        if not isinstance(p, str):
            continue
        try:
            if re.search(p, text):
                return True
        except re.error:
            pass
    return False
