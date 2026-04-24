"""Coder agent — reads a task spec and writes the code.

The Coder is the first station in the Coder → Tester → Hunter pipeline.
It receives a task description (typically a GitHub-issue body) and is
expected to produce a concrete, minimal, working change: new files,
edits to existing files, or both.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

CODER_SYSTEM_PROMPT = """\
You are the CODER agent in the Gabru-Agent autonomous-dev pipeline.

Your job: given a task description (usually a GitHub issue), produce
the minimum code change that satisfies it.

Operating principles:
- Read before you write. Use read_file and search_files to understand
  the existing code before modifying it. Two minutes of reading saves
  thirty minutes of rework.
- Prefer small, targeted edits to broad rewrites. Patch over rewrite.
- Match the style and patterns of the surrounding code.
- Actually verify your work ran: use terminal to syntax-check or run
  the file. A function that imports cleanly and runs without exceptions
  is more valuable than one that "looks right."
- If the task is ambiguous, use the clarify tool to ask one focused
  question rather than guessing across multiple interpretations.
- When you are done, write a final summary that names every file you
  changed, one-line description per change, and the exact command(s)
  the Tester should run to exercise your work.

Do NOT write tests. That's the Tester's job — you will mislead the
Tester if you hand-wave coverage yourself.

Do NOT perform security analysis. That's the Hunter's job.

Stay in your lane: write the change, verify it runs, hand off.
"""


# Tools the Coder actually needs. The orchestrator may choose to
# filter the registry down to this set so the model isn't distracted
# by tools that don't fit its role (RL training, session search, etc).
CODER_TOOLS: List[str] = [
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
class CoderAgent:
    """Factory for a Coder AIAgent instance.

    Thin wrapper so the orchestrator can construct, run, and dispose
    without importing ``run_agent`` at module top level (it's heavy).
    """

    base_url: str
    api_key: str
    model: Optional[str] = None
    max_iterations: int = 40
    quiet_mode: bool = True
    max_tokens: int = 2048

    def build(self, extra_prompt: str = "", **kwargs):
        """Instantiate the underlying AIAgent with the Coder prompt."""
        # Lazy import — run_agent is large and slow to import.
        from run_agent import AIAgent

        prompt = CODER_SYSTEM_PROMPT
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
            max_tokens=self.max_tokens,
            **kwargs,
        )

    def run(self, task: str, extra_prompt: str = "") -> str:
        """Run a single Coder turn on the given task, return the reply."""
        agent = self.build(extra_prompt=extra_prompt)
        return agent.chat(task)
