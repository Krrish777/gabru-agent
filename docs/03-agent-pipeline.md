# 03 — The 3-Agent Pipeline

## The roles in one line each

| Agent | Job | Can do | Cannot do |
|---|---|---|---|
| **Coder** (`agents/coder.py`) | Turn a task description into a minimal working code change | `read_file`, `write_file`, `patch`, `search_files`, `terminal`, `process`, `clarify`, `todo` | Write tests. Run security scans. |
| **Tester** (`agents/tester.py`) | Write pytest tests against the Coder's change and run them | Same file/exec tools as Coder | Write production code. Run security scans. |
| **Hunter** (`agents/hunter.py`) | Audit for edge cases and security issues — report only | `read_file`, `search_files`, `terminal`, `osv_check`, `tirith_security`, `clarify`, `todo` | Write files. Modify anything. |

Role boundaries are enforced by the **tool allow-list** (`*_TOOLS: List[str]`), not by prose in the system prompt. That's the defensible architectural claim.

## System prompts (verbatim)

### Coder

Key operating principles:
- **Read before you write.** Two minutes of reading saves thirty of rework.
- **Patch over rewrite.** Match surrounding style.
- **Actually verify your work ran** — `terminal` to syntax-check or execute. Import-cleanly + runs without exception > "looks right".
- **Clarify, don't guess** — if the task is ambiguous, use the `clarify` tool for one focused question rather than fan out across interpretations.
- **Hand-off summary** — final message names every file changed, one line per change, and the exact command(s) the Tester should run.

### Tester

- **Read the Coder's files first.** Docstrings, type hints, and edge cases are the spec.
- **Pytest with fixtures.** One behavior per test.
- **Never mock what you can run for real.** Filesystem ops in particular — mocks have a bad track record of passing while prod breaks.
- **Report exact pass/fail counts** from the final pytest summary line.
- **If tests fail because tests are wrong → fix the tests. If tests fail because the code is wrong → stop and say so.** Do NOT patch the Coder's code.

### Hunter

- **Broad read.** Use `search_files` to find every call site of any function Coder added/modified.
- **Two hunt modes:**
  - **LOGIC** — empty strings, zero, negative, huge, unicode, concurrent access, adversarial shape.
  - **SECURITY** — shell injection, SQL injection, path traversal, hardcoded secrets, disabled TLS, overly broad `except Exception: pass`, `eval`/`exec` on input.
- **Use static scanners** (`osv_check`, `tirith_security`) — they catch known-CVE classes faster than reading.
- **Finding format** — `file:line`, one-sentence description, concrete reproducing input / call site, severity (CRITICAL / HIGH / MEDIUM / LOW).
- **Do NOT fix.** Report only. Orchestrator decides whether to loop back.

## The two orchestration paths

### Path A — `orchestrator.run_pipeline()` (OpenRouter-backed)

Entry: `gabru-pipeline "task..."` (console script wired in `pyproject.toml`).

```python
def run_pipeline(task, *, api_key, base_url, model, ...):
    coder  = CoderAgent(base_url, api_key, model)
    tester = TesterAgent(base_url, api_key, model)
    hunter = HunterAgent(base_url, api_key, model)

    # Station 1: Coder — context = task
    # Station 2: Tester — context = task + coder_reply
    # Station 3: Hunter — context = task + coder_reply + tester_reply
```

Each `*Agent` dataclass lazily imports `run_agent.AIAgent`, builds an instance with:
- `ephemeral_system_prompt=<ROLE>_SYSTEM_PROMPT` (extra_prompt appended if passed)
- `model="anthropic/claude-sonnet-4.5"` by default
- `skip_memory=True, skip_context_files=True` (roles are stateless per run)
- `max_iterations=40, max_tokens=2048`

Crashes at any station are caught and recorded on `StationResult.error`. `PipelineResult.ok` is `False` if any station errored. **No retry / escalation logic in v1** — deliberately kept minimal; remediation lives in Path B.

Report format (see `orchestrator.PipelineResult.report`):

```markdown
# Gabru-Agent pipeline report
**Task:** ...
**Total time:** 12.3s
**Status:** success

## Coder  (4.2s)
...

## Tester  (3.8s)
...

## Hunter  (4.3s)
...
```

### Path B — `get_pipeline_stages` MCP tool (manifest + guided execution)

Entry: any MCP client (Claude Code live, Claude Desktop, Cursor) invokes `mcp__gabru__get_pipeline_stages(task=...)`.

The manifest returned is the full contract:

```json
{
  "pipeline": "Coder -> Tester -> Hunter",
  "task": "<verbatim user task>",
  "stages": [
    {
      "stage": 1,
      "name": "Coder",
      "system_prompt": "<CODER_SYSTEM_PROMPT>",
      "context": "TASK:\n<task>\n\nImplement... write a 3-4 line summary...",
      "gabru_tools": ["read_file", "write_file", "patch", "search_files",
                       "terminal", "process", "clarify", "todo"]
    },
    {
      "stage": 2,
      "name": "Tester",
      "system_prompt": "<TESTER_SYSTEM_PROMPT>",
      "context": "TASK (original):\n<task>\n\nCODER REPORT:\n{coder_output}\n\n...",
      "gabru_tools": [...],
      "note": "Replace {coder_output} with the Stage 1 summary before executing."
    },
    {
      "stage": 3,
      "name": "Hunter",
      "system_prompt": "<HUNTER_SYSTEM_PROMPT>",
      "context": "...CODER REPORT:\n{coder_output}\nTESTER REPORT:\n{tester_output}\n\nAudit..., THEN end your response with a fenced JSON findings block...",
      "gabru_tools": [...],
      "note": "Replace {coder_output} and {tester_output} with prior stage summaries."
    }
  ],
  "remediation": {
    "context_template": "TASK (original):\n{task}\n\nPRIOR CODER WORK:\n{coder_output}\n\nHUNTER FINDINGS (HIGH severity only):\n{hunter_findings}\n\nFix only the HIGH-severity findings...",
    "max_loops": 2,
    "loop_trigger_severity": "HIGH"
  },
  "execution_guide": "<block of instructions Claude Code follows>"
}
```

### The Hunter → Coder remediation loop (Path B only)

This is the closed-loop piece that turns the linear pipeline into a real agent.

1. `loop_count = 1` on first pass.
2. After Stage 3, **parse the fenced `json findings block`** at the end of Hunter's output.
   - **JSON is the contract** — do not prose-parse.
   - If malformed → halt pipeline with explicit error (Hunter failed the contract).
3. Count entries where `severity ∈ {HIGH, CRITICAL}`.
4. If count > 0 AND `loop_count < remediation.max_loops` (default 2):
   - Announce `## Stage 1 (remediation): Coder — fixing HIGH findings`.
   - Fill `remediation.context_template` with `{task}`, latest `{coder_output}`, filtered `{hunter_findings}`.
   - Re-run Coder → Tester → Hunter with `loop_count += 1`.
5. Stop when HIGH/CRITICAL count = 0 OR loop cap hit.

**Why capped at 2?** A genuinely unfixable HIGH finding should surface to the user, not burn indefinite budget. If the loop can't close in 2 iterations, that's a signal the task needs human review.

## Stage-chaining semantics

- **Coder → Tester**: Tester sees `TASK + CODER REPORT`. The Coder's narrative summary — not its scratch work — is the spec for the Tester.
- **Tester → Hunter**: Hunter sees `TASK + CODER REPORT + TESTER REPORT`. Hunter looks for what's *not* covered by the tests.
- **Hunter → Coder (remediation)**: Coder sees `TASK + PRIOR CODER WORK + HUNTER FINDINGS (HIGH only)`. Filtering to HIGH prevents the Coder from rewriting the world based on LOW noise.

Each "summary" is captured by the host (Path A: the orchestrator captures `station.reply`; Path B: Claude Code captures a 3-4 line summary at the end of each stage).

## Failure handling

| Failure mode | Path A (orchestrator) | Path B (manifest) |
|---|---|---|
| Station raises an exception | caught, `StationResult.error` populated, later stages still run | halt pipeline, emit a Markdown error block, skip later stages |
| Tester reports failing tests Coder can't trivially fix | Tester surfaces the failure in its reply; Hunter still runs | halt pipeline |
| Hunter returns malformed JSON block | n/a (Path A doesn't use the JSON contract) | halt pipeline (Hunter failed the contract) |
| Loop cap reached with unresolved HIGH findings | n/a | accept final report with open findings surfaced |

## Why Path B is the demo path

Path A works (senior-QA at 42/45) but burns three OpenRouter sessions per run. Path B is:

- **Zero external spend** during demo — Claude Code is already the model.
- **Visible to judges** — the manifest JSON comes back in the transcript; the three stage announcements are in the transcript; the tool calls are in the transcript.
- **Defensible under probing** — "where's your multi-agent system?" → "in the manifest, and enforced by the per-stage tool allow-list."

Approach B (subprocess-per-stage via ACP) is the eventual upgrade for true context isolation. `tools/delegate_tool.py` already has `acp_command`/`acp_args` plumbing. See [`05-decisions.md`](05-decisions.md) for the full Approach A vs. B vs. C tradeoff table and the rationale for choosing C.
