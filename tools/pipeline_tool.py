#!/usr/bin/env python3
"""Pipeline manifest tool — returns the 3-stage plan for Claude Code to execute.

Gabru owns the decision pipeline (roles, prompts, chaining, remediation
loop). Claude Code is the LLM that executes each stage using gabru's
other MCP tools (read_file, write_file, terminal, patch, etc.).
No OpenRouter key needed.

Design notes (see PIPELINE_PLAN.md + the approved plan file):
  - The manifest is pure data. Execution state (loop counters, stage
    summaries, timings) lives in Claude Code's conversation, not here.
  - The stage ``gabru_tools`` lists are the Coder / Tester / Hunter
    allow-lists lifted directly from ``agents/*.py`` so role isolation
    cannot drift between the pipeline and the CLI orchestrator.
  - ``remediation`` turns the linear pipeline into a bounded loop:
    when Hunter reports HIGH findings, Claude re-runs Coder with the
    ``remediation.context_template`` before a final Tester + Hunter pass.
"""

from __future__ import annotations

import json

from agents.coder import CODER_SYSTEM_PROMPT, CODER_TOOLS
from agents.hunter import HUNTER_SYSTEM_PROMPT, HUNTER_TOOLS
from agents.tester import TESTER_SYSTEM_PROMPT, TESTER_TOOLS
from tools.registry import registry, tool_error

_EXECUTION_GUIDE = """\
Execute the stages in order. For every stage:

  1. Announce it as a Markdown H2 header in the transcript:
        ## Stage N: <Role> — <one-line intent>
  2. Adopt the stage's ``system_prompt`` as your operating principles
     for that stage only.
  3. Use ONLY the gabru MCP tools listed in ``gabru_tools`` for this
     stage (mcp__gabru__<tool>). Do not call tools outside the list —
     that's how role isolation is enforced in this pipeline.
  4. Record the wall-clock seconds each stage takes (start → end).
  5. At the end of the stage, write a 3–4 line summary naming every
     file changed and the stage's outcome. Substitute that summary
     into the next stage's context template where it says
     ``{coder_output}`` / ``{tester_output}``.

Remediation loop (Hunter -> Coder):
  - Initialise ``loop_count = 1`` for the first pass.
  - After Stage 3, PARSE the fenced ```json findings block at the end of
    Hunter's output. Do NOT prose-parse Hunter's narrative — the JSON
    block is the contract. If the block is missing or malformed, halt
    the pipeline with an error (Hunter failed the contract).
  - Count entries where ``severity`` is ``HIGH`` or ``CRITICAL``. If
    that count is > 0 AND ``loop_count < remediation.max_loops``:
      a. Announce: ``## Stage 1 (remediation): Coder — fixing HIGH findings``
      b. Use ``remediation.context_template``, substituting ``{task}``,
         ``{coder_output}`` (latest), and ``{hunter_findings}`` (the
         filtered HIGH/CRITICAL subset, serialised as readable text).
      c. Re-run Coder, Tester, Hunter with ``loop_count += 1``.
  - Stop when Hunter's JSON block contains zero HIGH/CRITICAL entries
    OR the loop cap is hit.

Failure handling:
  - If any stage raises an exception or the Tester reports failing
    tests the Coder cannot trivially fix, HALT the pipeline. Emit a
    Markdown error block naming the failed stage and do not run later
    stages. This matches ``PipelineResult.ok=False`` from
    ``orchestrator.run_pipeline``.

Non-code tasks:
  - This tool is for tasks that will WRITE to the repository. For
    read-only asks (explain, summarize, question) do NOT call this
    tool; answer directly using gabru's read_file / search_files.

Final report:
  - After all stages (and any remediation loop) complete, print a
    Markdown report titled ``# Gabru-Agent Pipeline Report`` with one
    ``## Stage N — <Role> (Xs)`` section per stage, including loops.
"""


_REMEDIATION_CONTEXT_TEMPLATE = (
    "TASK (original):\n{task}\n\n"
    "PRIOR CODER WORK:\n{coder_output}\n\n"
    "HUNTER FINDINGS (HIGH severity only):\n{hunter_findings}\n\n"
    "Fix only the HIGH-severity findings listed above. Do not rewrite "
    "unrelated code. When done, summarise each fix (one line per finding "
    "addressed) and list every file touched."
)


def _build_stages(task: str) -> list[dict]:
    """Build the three stage dicts for a given task.

    Context templates use Python str.format placeholders (``{task}``,
    ``{coder_output}``, ``{tester_output}``) that Claude Code fills in
    at execution time.
    """
    return [
        {
            "stage": 1,
            "name": "Coder",
            "system_prompt": CODER_SYSTEM_PROMPT,
            "context": (
                f"TASK:\n{task}\n\n"
                "Implement this task. When done, write a 3-4 line summary "
                "naming every file changed (one line per file) and the "
                "exact command(s) the Tester should run to exercise your "
                "work."
            ),
            "gabru_tools": CODER_TOOLS,
        },
        {
            "stage": 2,
            "name": "Tester",
            "system_prompt": TESTER_SYSTEM_PROMPT,
            "context": (
                f"TASK (original):\n{task}\n\n"
                "CODER REPORT:\n{coder_output}\n\n"
                "Write pytest tests that exercise the Coder's change. Run "
                "them with the terminal tool and report the exact pass/fail "
                "counts from the final pytest summary line."
            ),
            "gabru_tools": TESTER_TOOLS,
            "note": "Replace {coder_output} with the Stage 1 summary before executing.",
        },
        {
            "stage": 3,
            "name": "Hunter",
            "system_prompt": HUNTER_SYSTEM_PROMPT,
            "context": (
                f"TASK (original):\n{task}\n\n"
                "CODER REPORT:\n{coder_output}\n\n"
                "TESTER REPORT:\n{tester_output}\n\n"
                "Audit the change for edge cases and security issues. Report "
                "only — do not fix. Write a human-readable audit in prose, "
                "THEN end your response with a fenced JSON findings block in "
                "this EXACT shape (no prose after it):\n"
                "```json\n"
                '{"findings": [\n'
                '  {"file": "<relative path>", "line": <int|null>, '
                '"severity": "CRITICAL|HIGH|MEDIUM|LOW", '
                '"category": "LOGIC|SECURITY", '
                '"summary": "<one sentence>"}\n'
                "]}\n"
                "```\n"
                'If there are no findings, emit exactly: {"findings": []}.\n'
                "The executor parses this JSON block to count HIGH/CRITICAL "
                "findings and decide whether to trigger the remediation loop. "
                "Drift from the schema breaks the loop contract."
            ),
            "gabru_tools": HUNTER_TOOLS,
            "note": "Replace {coder_output} and {tester_output} with prior stage summaries.",
        },
    ]


def _handle_get_pipeline_stages(args: dict, **_kwargs) -> str:
    task = (args.get("task") or "").strip()
    if not task:
        return tool_error("'task' is required.")

    manifest = {
        "pipeline": "Coder -> Tester -> Hunter",
        "task": task,
        "stages": _build_stages(task),
        "remediation": {
            "context_template": _REMEDIATION_CONTEXT_TEMPLATE,
            "max_loops": 2,
            "loop_trigger_severity": "HIGH",
        },
        "execution_guide": _EXECUTION_GUIDE,
    }
    return json.dumps(manifest, ensure_ascii=False, indent=2)


_SCHEMA = {
    "name": "get_pipeline_stages",
    "description": (
        "Return the Gabru-Agent pipeline manifest for a task.\n\n"
        "The manifest tells Claude Code (acting as the LLM) exactly what "
        "to do at each of the three pipeline stages:\n"
        "  Stage 1 — Coder: implement the change\n"
        "  Stage 2 — Tester: write and run unit tests\n"
        "  Stage 3 — Hunter: audit for edge cases and security issues\n\n"
        "Each stage returns its role's system_prompt, a context template "
        "with placeholders for prior stages' outputs, and the gabru MCP "
        "tools that stage is allowed to use. The manifest also includes "
        "a remediation block: if Hunter reports HIGH-severity findings, "
        "Claude should re-run Coder (bounded by max_loops) before the "
        "final report.\n\n"
        "Call this ONLY for tasks that will write to the repository. "
        "For read-only questions, answer directly without calling this "
        "tool. No OpenRouter key required."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": (
                    "Full task description from the user, verbatim. Be "
                    "specific: file paths, expected behaviour, constraints, "
                    "acceptance criteria."
                ),
            },
        },
        "required": ["task"],
    },
}

registry.register(
    name="get_pipeline_stages",
    toolset="pipeline",
    schema=_SCHEMA,
    handler=_handle_get_pipeline_stages,
    emoji="🗺️",
    description="Return the 3-stage pipeline manifest for Claude Code to execute.",
)
