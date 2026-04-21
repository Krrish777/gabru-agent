"""Gabru-Agent specialized role agents.

Each module defines one specialized agent — a role-specific system
prompt + tool bundle built on top of the shared ``AIAgent`` runtime.

The three roles map to the hackathon problem statement:

- :mod:`agents.coder`  — writes code from a task description
- :mod:`agents.tester` — writes unit tests against the coder's output
- :mod:`agents.hunter` — hunts edge cases + security issues

All three share the same tool registry; their system prompts and
focus differ. They can be composed via :mod:`orchestrator`.
"""

from agents.coder import CODER_SYSTEM_PROMPT, CoderAgent
from agents.hunter import HUNTER_SYSTEM_PROMPT, HunterAgent
from agents.tester import TESTER_SYSTEM_PROMPT, TesterAgent

__all__ = [
    "CoderAgent",
    "TesterAgent",
    "HunterAgent",
    "CODER_SYSTEM_PROMPT",
    "TESTER_SYSTEM_PROMPT",
    "HUNTER_SYSTEM_PROMPT",
]
