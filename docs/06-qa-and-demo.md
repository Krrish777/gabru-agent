# 06 — QA Evidence & Live Demo Script

## QA status — headline

**42 of 45** senior-QA checks pass. **0 failures.** 3 Windows-only SKIPs (ripgrep / `execute_code` platform gate).

Source: [`../QA_COVERAGE_REPORT.md`](../QA_COVERAGE_REPORT.md). Reproducible with:

```bash
python scripts/gabru_qa.py
```

## The QA harness architecture

`scripts/gabru_qa.py` spawns `python -m mcp_serve` as a subprocess, connects the official MCP Python client over stdio, and exercises every advertised tool against real filesystem + shell workflows. **No mocking.** Pass/fail contracts only — "doesn't crash" is not a pass.

### What gets tested — white-box

| ID | Check | Result |
|---|---|---|
| W1 | Schema integrity for every registered tool | PASS × 26 |
| W2 | Required-args enforced (empty args → validation error) | PASS (MCP SDK rejects before dispatch) |
| W3 | Malformed-args handling (wrong types → error) | PASS (`"Input validation error: 12345 is not of type 'string'"`) |
| W4 | Unknown-tool → clean error response | PASS (`{"error": "Unknown tool: not_a_real_tool_xyz"}`) |
| W5 | Server init + shutdown orderly | PASS (handshake protocol `2025-11-25`) |
| W6 | Idempotent read (dedup or identical) | PASS |

### What gets tested — black-box (role flows)

| Role | Check | Result |
|---|---|---|
| **Coder** | `write_file` creates `fib.py` with expected bytes | PASS |
| **Coder** | `terminal` runs `python fib.py` → exit 0, stdout `55` | PASS |
| **Coder** | `read_file` round-trips the written content | PASS |
| **Coder** | `execute_code` (`print(2+2)` → `4`) | SKIP (Windows — platform gate inside tool) |
| **Tester** | `write_file` creates `test_calc.py` | PASS |
| **Tester** | `terminal` runs pytest → exit 0, "2 passed" | PASS |
| **Tester** | Deliberate failing test → exit ≠ 0, "failed" in output | PASS |
| **Hunter** | Content-search for `shell=True` | SKIP (ripgrep not on PATH — passes on Linux CI) |
| **Hunter** | Filename-search for `vulnerable.py` | SKIP (same reason) |
| **Hunter** | `read_file` reads target for reasoning | PASS |
| **Multi-file** | `patch` `replace` mode modifies file on disk | PASS |
| **Introspection** | `memory.add` returns `success: True`, `entry_count ≥ 1` | PASS |
| **Introspection** | `todo` write + list round-trip marker | PASS |
| **Introspection** | `skills_list` returns ≥ 1 bundled pack (15 in this env) | PASS |

### Hackathon-alignment coverage map

| Agent role | Required primitive | QA proof |
|---|---|---|
| Coder | write source files | B1a |
| Coder | read / search existing code | B1c, B3c |
| Coder | run Python programs | B1b |
| Tester | write test files | B2a |
| Tester | run pytest + parse pass/fail | B2b, B2c |
| Hunter | scan code for risky patterns | B3a/B3b (SKIP Windows) |
| Hunter | read target for reasoning | B3c |
| Hunter | known-CVE scan | `osv_check` schema-checked |
| All | surgical edits | B4 |
| All | persistent state | B5a, B5b |
| All | procedural knowledge | B5c |

### Pytest

- **5,517** tests collected across `tests/`
- 0 collection errors
- Scope includes: core runtime, tool modules, agent internals, CLI commands, MCP server, retry classification, pricing, packaging metadata, SQL-injection regression, subprocess home isolation, IPv4 preference, timezone, base URL hostname normalization

Note: inherited tests targeting cut provider adapters (Anthropic-direct, Gemini, Bedrock, Nous Portal, Codex) still exist — flagged for deletion in a follow-up. Expected coverage target: **≥ 60%** on retained core modules.

## The live demo script

### Setup (before judges arrive)

1. Claude Code launched in the project dir.
2. `gabru mcp-serve` registered as an MCP server (via `claude mcp add gabru`).
3. Tool picker shows `mcp__gabru__*` entries.
4. A fresh terminal. A clean `demo_sandbox/` (already exists in repo).

### The live sequence

```
JUDGE (live): "Add a function reverse_str(s) to demo_sandbox/utils.py that reverses a string,
               with type hints and a docstring."

CLAUDE CODE (visible in transcript):

  → mcp__gabru__get_pipeline_stages(task="Add a function reverse_str(s)...")

  ← [RAW JSON MANIFEST renders in the transcript]
    {
      "pipeline": "Coder -> Tester -> Hunter",
      "task": "...",
      "stages": [...],
      "remediation": {"max_loops": 2, "loop_trigger_severity": "HIGH"},
      "execution_guide": "..."
    }

  ## Stage 1: Coder — implementing reverse_str in demo_sandbox/utils.py
    → mcp__gabru__read_file(path="demo_sandbox/")
    → mcp__gabru__write_file(path="demo_sandbox/utils.py", content="def reverse_str(s: str) -> str: ...")
    → mcp__gabru__terminal(command="python -c 'from demo_sandbox.utils import reverse_str; print(reverse_str(\"abc\"))'")
      cba ✓
    [Coder summary captured: "Wrote demo_sandbox/utils.py; verified reverse_str('abc') returns 'cba'"]

  ## Stage 2: Tester — writing pytest
    → mcp__gabru__write_file(path="demo_sandbox/test_utils.py", content="import pytest; ...")
    → mcp__gabru__terminal(command="pytest demo_sandbox/test_utils.py -v")
      ===== 4 passed in 0.08s =====
    [Tester summary captured: "Created demo_sandbox/test_utils.py; 4 passed, 0 failed."]

  ## Stage 3: Hunter — auditing
    → mcp__gabru__search_files(pattern="reverse_str", path=".")
    → mcp__gabru__read_file(path="demo_sandbox/utils.py")
    Audit narrative...
    ```json
    {"findings": [
      {"file": "demo_sandbox/utils.py", "line": 3, "severity": "LOW",
       "category": "LOGIC", "summary": "Silent type coercion on non-str input"}
    ]}
    ```

  # Gabru-Agent Pipeline Report
  ## Stage 1 — Coder (4.2s)
  Created demo_sandbox/utils.py with reverse_str(s: str) -> str.
  ## Stage 2 — Tester (3.8s)
  Created demo_sandbox/test_utils.py. 4 passed, 0 failed in 0.08s.
  ## Stage 3 — Hunter (2.1s)
  No HIGH findings. One LOW: silent type coercion. Pipeline complete.
```

### What the judges see happen (beat-by-beat)

| Beat | What appears on screen | Proves |
|---|---|---|
| 1 | Judge's question captured verbatim in the transcript | Live input, not staging |
| 2 | `mcp__gabru__get_pipeline_stages` tool call + JSON response | Gabru owns the plan (concrete tool round-trip) |
| 3 | `## Stage 1: Coder` header | Visible role transition |
| 4 | `read_file` + `write_file` + `terminal` sequence | Real file activity + real process execution |
| 5 | `## Stage 2: Tester` header | Second role transition |
| 6 | `pytest` output with pass count | Real test execution, no mocking |
| 7 | `## Stage 3: Hunter` header | Third role transition |
| 8 | `search_files` + `read_file` + JSON findings block | Real audit, machine-parseable output |
| 9 | Final Markdown report | Clean wrap |

### Edge case — remediation loop demo (optional)

If the judge wants to see the loop fire, use a deliberately-unsafe task:

```
"Write a function run_cmd(cmd) in demo_sandbox/shell.py that runs a shell command
 and returns its output."
```

Expected flow:

1. Stage 1 Coder writes `subprocess.run(cmd, shell=True, ...)` (or similar).
2. Stage 2 Tester's tests pass.
3. Stage 3 Hunter flags `{"severity": "HIGH", "category": "SECURITY", "summary": "shell=True on user-provided input — command injection"}`.
4. **Loop triggers.** `## Stage 1 (remediation): Coder — fixing HIGH findings`.
5. Coder rewrites with `shlex.split` + `shell=False`.
6. Stage 2 Tester re-runs tests, all pass.
7. Stage 3 Hunter re-audits, HIGH count = 0.
8. Final report with 2 loop iterations listed.

### Fallback plans

| Failure | Response |
|---|---|
| Wi-Fi / OpenRouter unavailable | Pipeline Path B doesn't need OpenRouter — Claude Code is the model. The only external call is `get_pipeline_stages` which is local JSON. |
| `ripgrep` not on PATH | Hunter's `search_files` SKIPs on Windows; stage still completes via `read_file`. Note this to judges as "platform-conditional; passes on Linux CI." |
| Claude Code misbehaves mid-stage | The manifest is visible; if needed, narrate what each stage *should* do and recover by pasting the manifest into a fresh turn. |
| Judge asks "is this just one Claude with three system prompts?" | "Role isolation is enforced by the per-stage `gabru_tools` allow-list in the manifest. Coder can't call `osv_check`; Hunter can't call `write_file`. The separation is functional, not just linguistic." |

### Timing

End-to-end on a simple task (reverse_str): ~15 seconds. On a more realistic task (add a validation layer to a small module): 30–60 seconds. Judge the pace — if stages are fast, invite a second task.

## Reproducing the QA report

```bash
# Scrub check (should match only NOTICE / LICENSE / README)
grep -rnE "Hermes|hermes|Nous Research" \
  --include='*.py' --include='*.md' --include='*.toml' \
  --exclude=LICENSE --exclude=NOTICE --exclude=README.md \
  --exclude-dir=.git --exclude-dir=skills --exclude-dir=optional-skills .

# Functional QA
python scripts/gabru_qa.py

# Pytest line coverage
coverage run -m pytest tests/ -q --tb=no
coverage report --omit="tests/*,*/fakes/*"
```
