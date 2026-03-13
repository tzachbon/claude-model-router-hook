#!/bin/bash
# Session init hook: injects model-tier guidance into every conversation,
# including mandatory rules for sub-agent model selection.
# Adapted from model-matchmaker (https://github.com/coyvalyss1/model-matchmaker)

INPUT=$(cat)

MODEL=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('model', 'unknown'))
except:
    print('unknown')
" 2>/dev/null)

MODEL_LOWER=$(echo "$MODEL" | tr '[:upper:]' '[:lower:]')
TIER_HINT=""
if echo "$MODEL_LOWER" | grep -q "opus"; then
    TIER_HINT=" You are currently on Opus. For simple tasks (git ops, renames, formatting), mention that Haiku or Sonnet would be cheaper."
elif echo "$MODEL_LOWER" | grep -q "haiku"; then
    TIER_HINT=" You are currently on Haiku. For deep analysis or architecture work, mention that Opus would produce better results."
elif echo "$MODEL_LOWER" | grep -q "sonnet"; then
    TIER_HINT=" You are currently on Sonnet. For simple mechanical tasks Haiku is cheaper; for architecture or deep analysis Opus is better."
fi

cat << EOF
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "## Model Tier Rules\n\nThese rules apply to YOU and to every sub-agent you spawn.\n\n### Sub-agent model selection (MANDATORY)\nWhen calling the Agent tool, you MUST set the model parameter based on task complexity:\n- **haiku** — simple mechanical tasks: file searches, grep, glob, reading a handful of files, git status/log, listing directories, quick lookups. Default for Explore agents unless deep reasoning is required.\n- **sonnet** — standard implementation: writing/editing code, debugging, creating components, running tests, most general-purpose agents.\n- **opus** — architecture decisions, deep multi-file analysis, complex refactors, plan-mode agents, anything requiring sustained reasoning across large context.\n\nNever default all sub-agents to Opus. Match the model to the work.\n\n### Your own tier${TIER_HINT}\n- Haiku: git ops, renames, formatting, simple edits.\n- Sonnet: feature work, debugging, planning.\n- Opus: architecture, deep analysis, multi-system reasoning.\n\n### Configuration\nIf the user wants to customize routing (keywords, patterns, thresholds), offer to create a config file at \`~/.claude/model-router.json\` (global) or \`.claude/model-router.json\` (project-level). Project config overrides global.\n- **thresholds**: \`opus_word_count\` (default 200), \`opus_question_word_count\` (default 100), \`haiku_max_word_count\` (default 60)\n- **Per tier** (opus/sonnet/haiku): \`mode\` (extend|replace), \`keywords\`, \`patterns\`, \`remove_keywords\`, \`remove_patterns\`\n- Mode \`extend\` (default) merges with built-ins; \`replace\` discards them.\n- **action**: \`warn\` (default) shows a recommendation without switching; \`autoswitch\` changes settings.json automatically.\n- Add \`\"\$schema\": \"https://raw.githubusercontent.com/tzachbon/claude-model-router-hook/main/schema/model-router.schema.json\"\` for IDE validation."
  }
}
EOF

exit 0
