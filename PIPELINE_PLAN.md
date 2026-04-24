# Plan: Claude Code as Model, Gabru as Pipeline Orchestrator + Toolbox

## Context

**Problem with current setup (what judges see today):**
Gabru reads a predefined `prompt.md`, calls OpenRouter three times (Coder → Tester → Hunter),
and prints a report. From a judge's view this looks like a batch script — not a living multi-agent
system. No live user input, no visible agent handoffs, no "wow" moment. It's also expensive
(OpenRouter API charges stack fast during demo rehearsals).

**What we want judges to see:**
- User types a natural-language task into Claude Code **live, on stage**
- Multi-agent pipeline kicks off **visibly**, with each role announcing itself
- Judges watch tool calls stream past (`read_file`, `write_file`, `terminal`, `search_files`)
- Final structured report appears, clearly marked by role
- Story: "Claude is the intelligence, Gabru is the body. Neither works without the other."

**Constraint:** Zero OpenRouter spend. Claude Code (this session) is the LLM for every role.

---

## The three architectural approaches

### Approach A — Single-conversation pipeline

**How it works:**
One Claude Code session plays all three roles back-to-back in the same context window.
When the user says "build X," Claude Code:

1. Silently retrieves the three role system prompts (hardcoded in a skill or fetched from a gabru tool)
2. Announces: **"Stage 1: Coder"** → executes Coder prompt using `mcp__gabru__*` tools
3. Announces: **"Stage 2: Tester"** → executes Tester prompt using `mcp__gabru__*` tools
4. Announces: **"Stage 3: Hunter"** → executes Hunter prompt using `mcp__gabru__*` tools
5. Prints a final combined report

```
Claude Code session (single context window)
  │
  ├─ role-switch → Coder  (uses gabru tools)
  ├─ role-switch → Tester (uses gabru tools)
  └─ role-switch → Hunter (uses gabru tools)
```

**Implementation cost:** Lowest. A single Claude Code *skill* + maybe a tiny MCP tool that returns the
three system prompts.

**Trade-offs:**

| Dimension | Verdict |
|-----------|---------|
| Dev effort | Lowest — 1 skill file, 30 minutes |
| Cost | Zero OpenRouter spend; single LLM session |
| Speed | Fastest — no subprocess overhead |
| Demo visibility | Highest — judges see everything in one scroll of text |
| Context isolation | All 3 roles share one window. Hunter can "see" Coder's reasoning, which weakens the adversarial audit (Hunter should ideally see only output, not Coder's internal monologue) |
| Architectural purity | Technically one agent wearing three hats, not three agents |
| Judge narrative | "One model, three personas, one goal." Compelling and clean. |

**Demo risk:** Judges who probe architecture might say "so it's just one Claude with a system prompt?"
Defensible answer: "Role isolation is enforced by Gabru — each role's toolset is filtered
(Hunter can't `write_file`, Coder can't `osv_check`). The separation is functional, not just linguistic."

---

### Approach B — Subprocess-per-stage (ACP mode)

**How it works:**
Gabru's `orchestrator.run_pipeline()` spawns `claude --acp --stdio` as a child subprocess for each
role. Each subprocess is a fresh Claude Code instance with its own context window. Gabru chains their
outputs the way it already does with OpenRouter today — it just swaps the transport layer from
HTTPS-to-OpenRouter for stdio-to-Claude-subprocess.

```
User → Claude Code (parent, this session)
         │
         └─ mcp__gabru__run_pipeline(task=...)
              │
              └─ gabru orchestrator:
                   ├─ Coder  = subprocess: claude --acp --stdio  (fresh context)
                   ├─ Tester = subprocess: claude --acp --stdio  (fresh context)
                   └─ Hunter = subprocess: claude --acp --stdio  (fresh context)
```

Gabru already supports this — `delegate_tool.py` has `acp_command` / `acp_args` plumbing that
explicitly calls out *"Enables spawning Claude Code (claude --acp --stdio) or other ACP-capable
agents from any parent."* We'd plumb the same parameters into `CoderAgent` / `TesterAgent` /
`HunterAgent` and `orchestrator.run_pipeline()`.

**Implementation cost:** Highest. Requires:
- Adding `acp_command` / `acp_args` fields to each agent dataclass in `agents/*.py`
- Threading these through `orchestrator.run_pipeline()`
- New `run_pipeline` MCP tool that defaults `acp_command="claude"`
- Testing triple-nested subprocess lifecycle (parent Claude → gabru MCP server → claude subprocess)

**Trade-offs:**

| Dimension | Verdict |
|-----------|---------|
| Dev effort | Highest — 4+ files modified, subprocess debugging |
| Cost | Each subprocess makes its own Claude API calls. If the Claude subprocess uses the user's API key, this could cost as much as OpenRouter did. If it uses the user's Claude Code subscription plan, it's usage-gated, not per-call |
| Speed | Slowest — subprocess spawn + separate init per stage (~3-5s overhead each) |
| Demo visibility | Worst — subprocesses are opaque from judges' viewpoint. They see "gabru running..." with logs, not interactive work |
| Context isolation | Best — each role has a clean context window, true adversarial audit |
| Architectural purity | Most faithful to the original 3-agent design |
| Judge narrative | "True multi-agent system with process isolation." Sounds impressive on a slide but the live demo won't show it clearly |

**Demo risk:** The "wow" moment gets buried in subprocess log output. Judges wait through silence while
`claude --acp --stdio` spins up. And "we spawn Claude Code inside Claude Code" raises awkward
recursion-style questions ("so how is this different from just calling Claude three times?").

---

### Approach C — Manifest + guided execution (Recommended)

**How it works:**
Split the pipeline into two clean halves:

1. **Gabru owns the *what*** — a new MCP tool `get_pipeline_stages(task)` returns a structured
   JSON manifest: the three role system prompts, the context-chaining templates (what gets filled
   in between stages), and which gabru tools each role should use.
2. **Claude Code owns the *how*** — this session receives the manifest, executes each stage
   sequentially, and uses gabru's other MCP tools (`read_file`, `write_file`, `terminal`,
   `search_files`, `patch`) to do the real work.

Gabru is the conductor; Claude Code is the orchestra.

```
User → "build me X"
         │
Claude Code (this session)
  │
  ├─ 1. mcp__gabru__get_pipeline_stages(task="...")
  │      ↳ returns { stages: [{role, system_prompt, context_template, tools}, ...] }
  │
  ├─ 2. STAGE 1 — Coder
  │      announce: "Stage 1: Coder — implementing..."
  │      mcp__gabru__read_file → mcp__gabru__write_file → mcp__gabru__terminal
  │      capture coder_output
  │
  ├─ 3. STAGE 2 — Tester
  │      announce: "Stage 2: Tester — writing and running tests..."
  │      fill {coder_output} in context template
  │      mcp__gabru__write_file → mcp__gabru__terminal (pytest)
  │      capture tester_output
  │
  └─ 4. STAGE 3 — Hunter
         announce: "Stage 3: Hunter — auditing for vulnerabilities..."
         fill {coder_output}, {tester_output}
         mcp__gabru__search_files → mcp__gabru__read_file
         capture hunter_findings
  │
  └─ Final: structured markdown report
```

**Implementation cost:** Low. One new file (`tools/pipeline_tool.py`) + a one-line addition to
`toolsets.py`. Zero changes to `orchestrator.py`, `agents/*.py`, `mcp_serve.py`.

**Trade-offs:**

| Dimension | Verdict |
|-----------|---------|
| Dev effort | Low — 1 new file, ~80 lines |
| Cost | Zero OpenRouter spend; single Claude Code session |
| Speed | Fast — no subprocess overhead |
| Demo visibility | Highest + best-narrated — judges see the manifest come back from gabru (proof gabru "owns" the plan), then watch Claude execute each stage with role announcements |
| Context isolation | Same single-context limitation as Approach A |
| Architectural purity | Clean separation of concerns (plan vs execution) |
| Judge narrative | "Gabru decides what the agents do. Claude does the thinking. Neither ships without the other." This maps 1:1 onto the hackathon pitch. |

**Why this wins for the demo:**

1. **Live user input** — the judge dictates the task on stage; no `prompt.md` in sight.
2. **Two visible tool calls of different character:**
   - `get_pipeline_stages` → proves gabru is the orchestrator (the *manifest* is visible)
   - `read_file` / `write_file` / `terminal` → proves gabru is also the execution layer
3. **Visible role transitions** — three "Stage N: <Role>" announcements in the transcript
4. **Visible artifacts** — code file, test file, security findings, all created during the demo
5. **Cost story in the deck** — "We moved from N OpenRouter calls per pipeline run to zero. The
   model layer is whatever Claude Code is already running."

---

## Recommendation: **Approach C**

Why not A? Because A has nothing for gabru to *do*. Judges will say "where's your multi-agent
system?" and the only answer is "it's hardcoded in a Claude Code skill." Approach C makes gabru
visibly responsible for the pipeline definition — one concrete MCP round-trip proves it.

Why not B? Because the demo looks like waiting for logs to scroll. The subprocess isolation is a
technical win with no stage presence.

Approach C also leaves a clean upgrade path: if you later want per-stage isolation, you swap the
"Claude Code executes the manifest" step for "gabru's ACP subprocess executes the manifest" —
same manifest, different executor.

---

## Implementation (for Approach C)

### File 1: `tools/pipeline_tool.py` (new, ~80 lines)

```python
"""Pipeline manifest tool — returns the 3-stage plan for Claude Code to execute.

Gabru owns the decision pipeline (roles, prompts, chaining).
Claude Code is the LLM that executes each stage using gabru's other MCP tools.
No OpenRouter key needed.
"""

from __future__ import annotations

import json

from agents.coder import CODER_SYSTEM_PROMPT, CODER_TOOLS
from agents.hunter import HUNTER_SYSTEM_PROMPT, HUNTER_TOOLS
from agents.tester import TESTER_SYSTEM_PROMPT, TESTER_TOOLS
from tools.registry import registry, tool_error


_EXECUTION_GUIDE = """\
Execute each stage in order. For every stage:
  1. Announce it to the user: "Stage N: <Role> — <short description>"
  2. Adopt the stage's system_prompt as your operating principles for that stage.
  3. Use gabru's MCP tools (mcp__gabru__read_file, mcp__gabru__write_file,
     mcp__gabru__terminal, mcp__gabru__search_files, mcp__gabru__patch, etc.)
     to do the real work.
  4. Capture a short summary of the stage's outcome.
  5. In the next stage's context template, fill {coder_output} / {tester_output}
     with the summaries you captured.
After all three stages complete, print a markdown report titled
"# Gabru-Agent Pipeline Report" with one clearly labelled section per stage.
"""


def _handle_get_pipeline_stages(args: dict, **_kwargs) -> str:
    task = (args.get("task") or "").strip()
    if not task:
        return tool_error("'task' is required.")

    stages = [
        {
            "stage": 1,
            "name": "Coder",
            "system_prompt": CODER_SYSTEM_PROMPT,
            "context": (
                f"TASK:\n{task}\n\n"
                "Implement this task. When done, summarise every file you changed "
                "(one line per file) and the exact command(s) the Tester should run."
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
                "Write pytest tests for the Coder's change, run them, report pass/fail counts."
            ),
            "gabru_tools": TESTER_TOOLS,
            "note": "Replace {coder_output} with Stage 1 summary before sending.",
        },
        {
            "stage": 3,
            "name": "Hunter",
            "system_prompt": HUNTER_SYSTEM_PROMPT,
            "context": (
                f"TASK (original):\n{task}\n\n"
                "CODER REPORT:\n{coder_output}\n\n"
                "TESTER REPORT:\n{tester_output}\n\n"
                "Audit the change for edge cases and security issues. Report only — do not fix."
            ),
            "gabru_tools": HUNTER_TOOLS,
            "note": "Replace {coder_output} and {tester_output} with prior stage summaries.",
        },
    ]

    return json.dumps(
        {
            "pipeline": "Coder → Tester → Hunter",
            "task": task,
            "stages": stages,
            "execution_guide": _EXECUTION_GUIDE,
        },
        ensure_ascii=False,
        indent=2,
    )


_SCHEMA = {
    "name": "get_pipeline_stages",
    "description": (
        "Return the Gabru-Agent pipeline manifest for a task.\n\n"
        "The manifest tells Claude Code (acting as the LLM) exactly what to do "
        "at each of the three pipeline stages:\n"
        "  Stage 1 — Coder: implement the change\n"
        "  Stage 2 — Tester: write and run unit tests\n"
        "  Stage 3 — Hunter: audit for edge cases and security issues\n\n"
        "Each stage returns its role's system_prompt, a context template "
        "(with placeholders for prior stages' outputs), and the gabru MCP tools "
        "that stage should use. No OpenRouter key required."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": (
                    "Full task description. Be specific: file paths, expected "
                    "behaviour, constraints, acceptance criteria."
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
```

### File 2: `toolsets.py` (modify, one entry added around line 103)

```python
"pipeline": {
    "description": "Pipeline manifest — returns Coder/Tester/Hunter stage instructions for Claude Code",
    "tools": ["get_pipeline_stages"],
    "includes": [],
},
```

### Untouched
- `orchestrator.py`, `agents/*.py`, `mcp_serve.py` — left alone; the OpenRouter path still works
  for anyone using `gabru-pipeline` from the CLI. The new MCP tool is a parallel path.

---

## Claude Code's runtime behaviour (the demo script)

```
USER (live, on stage):
  "Build a Python function reverse_str(s) in utils.py that reverses
   a string, with type hints and a docstring."

CLAUDE CODE (visible):
  → calls mcp__gabru__get_pipeline_stages(task="...")
  ← receives manifest with 3 stages

  "Stage 1: Coder — implementing utils.py"
  → mcp__gabru__read_file(path=".")      [scans existing files]
  → mcp__gabru__write_file(path="utils.py", content="def reverse_str(s: str) -> str: ...")
  → mcp__gabru__terminal(cmd="python -c 'from utils import reverse_str; print(reverse_str(\"abc\"))'")
    CBA ✓
  [coder_output captured]

  "Stage 2: Tester — writing pytest"
  → mcp__gabru__write_file(path="tests/test_utils.py", content="import pytest; ...")
  → mcp__gabru__terminal(cmd="pytest tests/test_utils.py -v")
    ===== 4 passed in 0.08s =====
  [tester_output captured]

  "Stage 3: Hunter — auditing"
  → mcp__gabru__search_files(pattern="reverse_str", path=".")
  → mcp__gabru__read_file(path="utils.py")
  - No injection/unsafe patterns
  - Edge case: type coercion on non-str input
  [hunter_output captured]

  # Gabru-Agent Pipeline Report
  ## Stage 1 — Coder  (4.2s)
  Created utils.py with reverse_str(s: str) -> str.
  ## Stage 2 — Tester  (3.8s)
  Created tests/test_utils.py. 4 passed, 0 failed in 0.08s.
  ## Stage 3 — Hunter  (2.1s)
  No security issues. One edge case noted (MEDIUM): reverse_str coerces
  non-string input silently via type hint only.
```

Every bolded line above is something judges watch happen in real time.

---

## Verification

1. Activate venv: `.venv\Scripts\activate` (Windows) / `source .venv/bin/activate` (Unix)
2. Confirm tool registers:
   ```
   python -c "import model_tools; from tools.registry import registry; print(registry.get_schema('get_pipeline_stages'))"
   ```
3. Full run-through:
   - In Claude Code session, give a live task (e.g. "add reverse_str to utils.py")
   - Watch `mcp__gabru__get_pipeline_stages` appear in the tool-call list
   - Watch three clearly-announced stage executions
   - Watch the final report render
