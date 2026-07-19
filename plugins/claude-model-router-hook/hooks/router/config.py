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
        key in raw for key in ("opus", "sonnet", "haiku", "thresholds")
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


def load_config(global_path=None, cwd=None):
    """Load global + project configs, shallow-merged onto DEFAULTS.

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
        for key, value in _read_json(global_path).items():
            if key == "$schema":
                continue
            config[key] = value

    # Project config (walk up from CWD to find .claude/model-router.json)
    search_root = pathlib.Path(cwd) if cwd else pathlib.Path.cwd()
    for parent in [search_root, *search_root.parents]:
        project_path = parent / ".claude" / "model-router.json"
        if project_path.exists():
            for key, value in _read_json(project_path).items():
                if key == "$schema":
                    continue
                config[key] = value
            break

    return config


def safe_regex_match(patterns, text):
    """Test if any pattern matches text, silently skipping invalid regexes."""
    for p in patterns:
        try:
            if re.search(p, text):
                return True
        except re.error:
            pass
    return False
