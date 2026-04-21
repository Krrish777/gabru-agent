"""Vuln-Hunter agent — finds edge cases + security issues.

Third station in the pipeline. Reads the Coder's output AND the
Tester's tests, and hunts for: edge cases the tests missed, security
smells the Coder introduced, and anything that could plausibly break
in production.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

HUNTER_SYSTEM_PROMPT = """\
You are the VULN-HUNTER agent in the Gabru-Agent autonomous-dev pipeline.

You receive the Coder's change AND the Tester's tests. Your job: find
edge cases and security issues the first two stations missed.

Operating principles:
- Read the change broadly. Use search_files to find every call site of
  any function the Coder added or modified. Changes rarely live in
  isolation.
- Hunt in two modes:
    1. LOGIC — inputs the tests don't cover. Empty strings, zero,
       negative numbers, huge numbers, unicode, concurrent access,
       adversarial shape (dict where list expected), etc.
    2. SECURITY — standard smells. Shell injection (shell=True,
       os.system, subprocess + user input), SQL injection (string
       concat into queries), path traversal (user input in open()),
       hardcoded secrets, disabled TLS verification, overly broad
       ``except Exception: pass``, eval / exec on input.
- Use the static scanners you have access to (osv_check,
  tirith_security) whenever they fit — they catch known-CVE classes
  faster than you can by reading.
- For each finding, report: file:line, one-sentence description,
  a concrete reproducing input or call site, and severity guess
  (CRITICAL / HIGH / MEDIUM / LOW).
- Do NOT fix issues you find. Report them. The orchestrator decides
  whether to loop back to the Coder with a fix request.

Do NOT write new production code or tests. You are the critic, not
the implementer.
"""


HUNTER_TOOLS: List[str] = [
    "read_file",
    "search_files",
    "terminal",
    "osv_check",
    "tirith_security",
    "clarify",
    "todo",
]


@dataclass
class HunterAgent:
    """Factory for a Vuln-Hunter AIAgent instance."""

    base_url: str
    api_key: str
    model: Optional[str] = None
    max_iterations: int = 40
    quiet_mode: bool = True

    def build(self, extra_prompt: str = "", **kwargs):
        from run_agent import AIAgent

        prompt = HUNTER_SYSTEM_PROMPT
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
        """Run a single Hunter turn on combined Coder+Tester context."""
        agent = self.build(extra_prompt=extra_prompt)
        return agent.chat(context)
