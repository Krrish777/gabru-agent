# 05 — Architectural Decisions

A decision log. Each entry states the decision, the alternatives considered, the rationale, and the blast-radius if we're wrong.

## ADR-01 — Derive from Hermes Agent, don't start from scratch

**Decision:** Fork Hermes Agent (Nous Research, MIT) and prune aggressively.

**Alternatives:**
- Build from scratch (slower, reinvent tool registry + MCP integration).
- Fork a different base (LangGraph, AutoGen, smol-agents) — heavier frameworks, worse cost stories.

**Rationale:**
- Hermes already had the conversation loop, OpenRouter integration, MCP server, SQLite+FTS5 state, and skills system working.
- The ~48-hour strip removed provider adapters we didn't need (Anthropic-direct, Gemini, Bedrock, Nous-Portal, Codex, Copilot), cut the messaging gateway, dropped ACP/TUI surface, and trimmed the skill list. Net result: a lean foundation focused on the 3-role pipeline.

**Blast radius if wrong:** Low. Upstream attribution preserved in `LICENSE` and `NOTICE` per MIT; we can keep pulling relevant upstream changes. A clean-room rewrite was never going to ship in hackathon time.

## ADR-02 — OpenRouter as the only provider in CLI mode

**Decision:** Every LLM call in CLI mode goes through OpenRouter (`https://openrouter.ai/api/v1`). For Claude specifically, we use OpenRouter's `anthropic/*` model slugs.

**Alternatives:**
- Multi-provider abstraction (Hermes had this; we stripped it).
- Direct Anthropic API (cheaper at scale, but forks auth/billing/prompt-caching code paths).

**Rationale:**
- One auth path, one billing story, one retry/backoff policy.
- OpenRouter passes Anthropic prompt-cache markers through for `anthropic/*` slugs, so we don't lose the cost savings.
- Reduces the attack surface for provider-specific bugs (QA has seen many).

**Blast radius if wrong:** Medium. If OpenRouter outages become load-bearing, we'd need a secondary. But adding another provider today would mean re-threading cache semantics, retry classification, and tool-call formatting across N code paths — net-negative reliability.

## ADR-03 — One shared tool registry for all run modes

**Decision:** `tools/registry.py` is the only registration point. CLI, pipeline, and MCP server all dispatch through it.

**Alternatives:**
- Per-mode tool implementations (CLI tools vs. MCP tools as distinct surfaces).
- Registry split by concern (file-ops registry, exec registry, security registry).

**Rationale:**
- Writing a tool once and getting it in three places is the single biggest accelerant we have.
- Forces tool handlers to stay self-contained (no CLI-only side effects), which is a better design anyway.
- Enables the senior-QA harness: QA drives the registry over MCP stdio and transitively validates every mode.

**Blast radius if wrong:** Tools that need mode-aware behavior have to fake it (e.g. `approval` tool relies on the host's UI). Acceptable — that's a small set.

## ADR-04 — Self-registering tools via AST scan

**Decision:** `model_tools.discover_builtin_tools()` AST-scans `tools/*.py` for top-level `registry.register(...)` calls and imports each match.

**Alternatives:**
- Explicit `tools/__init__.py` manifest listing every tool module.
- Decorator-based registration discovered at import of the package.
- Entrypoint-based plugin discovery (setuptools `entry_points`).

**Rationale:**
- Adding a new tool is a single file, no manifest edit, no `__init__.py` change. This matters when tool authors are rotating.
- AST scan avoids executing modules just to find registration calls — strictly pattern-match first, import second.
- Explicit manifest tempts drift when somebody forgets to add the line.

**Blast radius if wrong:** If the AST pattern misses a registration (e.g. nested `register` call), the tool won't appear. Guarded by the linter convention of always top-level registration.

## ADR-05 — Pipeline manifest + guided execution (Approach C) for the demo

**Decision:** Expose `get_pipeline_stages(task)` as an MCP tool. Claude Code executes the manifest in its own loop.

**Alternatives rejected (full table):**

| Approach | Description | Verdict |
|---|---|---|
| **A — single-conversation pipeline** | Claude plays all 3 roles in one context; no gabru tool needed for orchestration | **Reject.** Gabru has nothing visible to do; judges will ask "where's the multi-agent system?" |
| **B — subprocess-per-stage (ACP)** | `orchestrator.run_pipeline()` spawns `claude --acp --stdio` per stage | **Reject.** Strongest context isolation, worst demo visibility — judges watch subprocess logs scroll in silence. |
| **C — manifest + guided execution** | Gabru returns structured JSON manifest; Claude Code executes it with role-scoped tools | **Accept.** Best demo visibility + zero external LLM spend + clean upgrade path to B. |

**Rationale:**
- Path A has nothing for gabru to *do* that's legible.
- Path B's strongest technical claim (fresh context per role) is invisible on stage.
- Path C makes gabru visibly responsible for the pipeline definition — one MCP round-trip proves it — while Claude Code does the visible execution.

**Blast radius if wrong:** Single context window means Hunter sees Coder's reasoning, not just output. That weakens the adversarial-audit claim. Mitigations: role-scoped tool allow-lists + explicit "report only, do not fix" Hunter prompt. The subprocess-isolation upgrade (Approach B) is a clean swap later — same manifest, different executor.

Full analysis in [`../PIPELINE_PLAN.md`](../PIPELINE_PLAN.md).

## ADR-06 — Role isolation enforced by tool allow-lists

**Decision:** Each role has a plain `List[str]` of tool names it may use. The orchestrator (Path A) or the host (Path B) filters the registry down to that list.

**Alternatives:**
- Prose-only role discipline (relies on the model to obey).
- RBAC-style permission system with scopes/actions.

**Rationale:**
- Prose alone fails — in testing, a Coder with access to `osv_check` *will* run it on speculation and waste tokens.
- RBAC is overkill for 3 roles with no dynamic permission changes.
- `List[str]` is the minimum viable enforcement — trivial to audit, trivial to change.

**Blast radius if wrong:** Tight lists can block legitimate work (e.g. Coder needing to check if a dep has a known CVE before adding it). The `clarify` tool is the escape hatch — ask the user, or escalate to the orchestrator.

## ADR-07 — Hunter outputs a JSON findings block (contract with remediation loop)

**Decision:** Hunter's system prompt requires a fenced ```json``` block at the end of its response with schema `{findings: [{file, line, severity, category, summary}, ...]}`.

**Alternatives:**
- Prose-only findings, regex-extracted.
- Findings as a separate MCP tool call (e.g. `report_finding(...)` called N times).

**Rationale:**
- Remediation loop needs a structured signal to decide when to re-trigger Coder. Prose parsing drifts; JSON is a contract.
- Separate tool calls were overkill and added per-finding overhead.
- Fenced JSON block is visible to the user in the transcript (transparency) AND machine-parseable.

**Blast radius if wrong:** Malformed JSON halts the pipeline. That's the correct failure mode — Hunter failed the contract; humans should look. Better than a silent miss.

## ADR-08 — Remediation loop capped at 2 iterations

**Decision:** `remediation.max_loops = 2`. On HIGH/CRITICAL findings, Coder re-runs up to twice.

**Alternatives:**
- Unbounded loop until clean.
- Single pass, no remediation.

**Rationale:**
- Unbounded loop is an unbounded cost bomb and masks genuinely hard bugs. If two tries can't close it, a human should look.
- Single-pass misses the common case of "Coder fixes it once Hunter points out the issue" — which is the whole value of the loop.
- Two iterations is enough for "forgot input validation" → "added validation" → Hunter confirms clean.

**Blast radius if wrong:** Tasks that need 3+ iterations surface as "HIGH findings unresolved" in the final report, which is the correct thing for a user to see.

## ADR-09 — Handlers are synchronous; MCP server offloads to threads

**Decision:** Tool handlers are plain synchronous Python. `mcp_serve.py` wraps each call in `asyncio.to_thread(_call)`.

**Alternatives:**
- Async handlers throughout.
- Hybrid (sync + async co-registered).

**Rationale:**
- Tool implementations are mostly IO to filesystem, shell, HTTP libraries that are already sync.
- Async would require dragging asyncio into every handler author's head.
- `asyncio.to_thread` is a one-line adapter in the MCP server and keeps the event loop responsive.

**Blast radius if wrong:** Long-running handlers (e.g. a 5-minute `osv_check` on a huge dep tree) hold a thread but don't block the event loop. Acceptable.

## ADR-10 — `GABRU_HOME` for all state paths; tests autouse a tmp override

**Decision:** Every state path resolves through `gabru_constants.get_gabru_home()`. Tests install an autouse fixture in `tests/conftest.py` that redirects `GABRU_HOME` to a tmp dir.

**Alternatives:**
- Hardcode `~/.gabru`.
- Per-module config.

**Rationale:**
- Profile isolation (dev vs. prod vs. CI vs. tests) needs to be a single env flip.
- Tests must never contaminate the developer's real home dir. The autouse fixture enforces this — belt + suspenders with the coding convention.

**Blast radius if wrong:** One module forgets `get_gabru_home()` and hardcodes `~/.gabru`. Caught by `test_subprocess_home_isolation.py` and the conftest fixture.

## ADR-11 — Preserve upstream attribution in LICENSE + NOTICE

**Decision:** Keep Hermes Agent / Nous Research attribution intact. Never scrub.

**Alternatives:**
- Remove attribution (MIT violation).
- Full rewrite (out of scope).

**Rationale:**
- MIT requires the notice be retained.
- It's the right thing to do.

**Blast radius if wrong:** Legal + reputational. Non-negotiable.

## ADR-12 — `scripts/run_tests.sh` as the canonical test command, not raw pytest

**Decision:** Use the wrapper. It pins `-n 4` xdist workers, sets `TZ=UTC LANG=C.UTF-8 PYTHONHASHSEED=0`, blanks every credential-shaped env var, and overrides `pyproject.toml`'s `addopts`.

**Alternatives:**
- Raw `pytest` (what most devs reach for).
- CI-only hardening (different command locally vs. CI).

**Rationale:**
- Flaky tests in multi-core workstations (`-n auto`) don't reproduce in CI (`-n 4`). Pinning matches CI parity.
- Timezone/locale/hash-seed drift produces "works on my machine" test failures.
- Blanking credentials prevents tests accidentally hitting real APIs.

**Blast radius if wrong:** Devs who skip the wrapper get inconsistent results vs. CI. Mitigation: wrapper is documented in `README.md`, `AGENTS.md`, and `CLAUDE.md`.
