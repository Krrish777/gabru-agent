"""Tester agent — writes unit tests against the Coder's output.

The Tester is the second station. It receives the Coder's summary
(file list + description of the change) and writes pytest tests that
actually exercise the behavior, then runs them to confirm pass/fail.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

TESTER_SYSTEM_PROMPT = """\
You are the TESTER agent in the Gabru-Agent autonomous-dev pipeline.

You receive the Coder's summary of a change (files modified, behavior
intended). Your job: write unit tests that actually exercise that
behavior, then run them.

Operating principles:
- Read the Coder's files before writing tests. The docstrings, type
  hints, and edge cases are your spec.
- Write pytest tests. Use fixtures for setup. Keep each test focused
  on one behavior.
- Cover the happy path first. Then one or two edge cases per function
  (empty input, boundary values, type errors where relevant).
- Never mock what you can run for real. Integration beats mock —
  particularly for filesystem operations, where mocked tests have a
  bad track record of passing while prod breaks.
- Run pytest with ``terminal`` and report the exact pass/fail counts.
- If tests fail because your tests are wrong, fix the tests. If tests
  fail because the Coder's code is wrong, stop and say so clearly —
  do NOT patch the Coder's code yourself.
- Your final output must name every test file you created and the
  last pytest line ("N passed, M failed in X.XXs").

Do NOT write new production code. That's the Coder's job.

Do NOT perform security analysis. That's the Hunter's job.
"""


TESTER_TOOLS: List[str] = [
    "read_file",
    "write_file",
    "patch",
    "search_files",
    "terminal",
    "process",
    "clarify",
    "todo",
]


@dataclass
class TesterAgent:
    """Factory for a Tester AIAgent instance."""

    base_url: str
    api_key: str
    model: Optional[str] = None
    max_iterations: int = 40
    quiet_mode: bool = True

    def build(self, extra_prompt: str = "", **kwargs):
        from run_agent import AIAgent

        prompt = TESTER_SYSTEM_PROMPT
        if extra_prompt:
            prompt = prompt + "\n\n" + extra_prompt

        return AIAgent(
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.model or "anthropic/claude-sonnet-4.5",
            max_iterations=self.max_iterations,
            ephemeral_system_prompt=prompt,
            quiet_mode=self.quiet_mode,
            skip_memory=True,
            skip_context_files=True,
            **kwargs,
        )

    def run(self, context: str, extra_prompt: str = "") -> str:
        """Run a single Tester turn on the Coder's context, return the reply."""
        agent = self.build(extra_prompt=extra_prompt)
        return agent.chat(context)
