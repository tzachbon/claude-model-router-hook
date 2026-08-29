"""PostToolUse telemetry stays fail-open and records actual model resolution."""

import json
import os
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POST_HOOK = os.path.join(
    REPO_ROOT, "plugins", "claude-model-router-hook", "hooks", "post_tool_use.py"
)


class TestPostToolUseTelemetry(unittest.TestCase):

    def _run(self, home, payload):
        env = dict(os.environ)
        env["HOME"] = home
        env.pop("CLAUDE_MODEL_ROUTER_CHILD", None)
        return subprocess.run(
            [sys.executable, POST_HOOK],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            cwd=home,
        )

    def test_completed_agent_logs_requested_and_resolved_models(self):
        with tempfile.TemporaryDirectory() as home:
            prompt = "implement the requested feature " + ("without leakage " * 10)
            proc = self._run(home, {
                "tool_name": "Agent",
                "tool_input": {"model": "opus", "prompt": prompt},
                "tool_response": {
                    "status": "completed",
                    "resolvedModel": "claude-opus-5",
                    "modelsUsed": ["claude-opus-5", "claude-haiku-4-5"],
                    "totalDurationMs": 123,
                    "totalTokens": 456,
                },
            })
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout, "")
            with open(os.path.join(home, ".claude", "hooks", "model-router-hook.log")) as fh:
                line = fh.read()
            self.assertIn("action=SUBAGENT-COMPLETE", line)
            self.assertIn("requested_model=opus", line)
            self.assertIn("resolved_model=claude-opus-5", line)
            self.assertIn("models_used=claude-opus-5,claude-haiku-4-5", line)
            self.assertIn("duration_ms=123", line)
            self.assertIn("tokens=456", line)
            self.assertNotIn("without leakage without leakage", line)

    def test_non_string_models_used_are_ignored(self):
        with tempfile.TemporaryDirectory() as home:
            proc = self._run(home, {
                "tool_name": "Agent",
                "tool_input": {"model": "opus", "prompt": "implement this"},
                "tool_response": {"modelsUsed": ["claude-opus-5", 7]},
            })
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout, "")
            with open(os.path.join(home, ".claude", "hooks", "model-router-hook.log")) as fh:
                self.assertIn("models_used=claude-opus-5", fh.read())
