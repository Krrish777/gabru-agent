# 07 — Roadmap & Open Questions

## What ships today

- ✅ CLI single-agent runtime (`gabru --task`)
- ✅ 3-agent sequential pipeline (`gabru-pipeline`) — OpenRouter-backed
- ✅ MCP stdio server (`gabru mcp-serve`) — 26 tools exposed
- ✅ Pipeline manifest tool (`get_pipeline_stages`) — demo path
- ✅ Remediation loop contract (Hunter JSON findings → bounded Coder re-run)
- ✅ Self-registering tool system + AST-scan discovery
- ✅ Role-scoped tool allow-lists enforced in both Path A (orchestrator) and Path B (manifest)
- ✅ Persistent memory + todo + session search (SQLite + FTS5)
- ✅ 6 bundled skill packs (software-development, github, red-teaming, devops, mcp, index-cache)
- ✅ Senior-QA harness with 45 checks (42 pass, 3 Windows SKIPs)
- ✅ Anthropic prompt-caching passthrough on OpenRouter
- ✅ Auto-compression near token limit

## Next 90 days — hackathon → first productization

### P0 (immediately after hackathon)

| Item | Why | Effort |
|---|---|---|
| GitHub-issue ingestion adapter | Closes the "hand an issue, get a PR" loop that justifies the product | 2–3 days |
| Hunter wired to `bandit` + `semgrep` via MCP or direct CLI | Current Hunter has `osv_check` + `tirith_security`; adding bandit/semgrep broadens coverage materially | 1–2 days |
| Eval harness with synthetic GitHub-issue fixtures | Prove quality claims with numbers, not vibes | 3–5 days |
| LLM-judge scoring for pipeline output | Regression signal for prompt changes | 2 days |
| Linux CI green (unblock Windows SKIPs on CI) | 45/45 on CI is a concrete number for slides | 1 day |

### P1

| Item | Why |
|---|---|
| Approach B (ACP subprocess-per-stage) swap | True context isolation for Hunter's adversarial audit. Manifest stays identical; only the executor changes. |
| Frontend UI | Helpful for non-technical stakeholders; not required for hackathon. |
| Skills-sync hub | Pulls updated skill packs from a central source; partial infra exists (`tools/skills_hub.py`, `skills_sync.py`). |
| More languages | Today's Coder/Tester/Hunter are implicitly Python-first. Extending to TypeScript + Go is the first expansion. |

### P2 (stretch)

- RL loop for the Coder (Tinker-Atropos plumbing already in `rl_*` tools — unused in demo).
- Debate/critique v2 orchestrator adapted from `tools/mixture_of_agents_tool.py`.
- Cost routing (fallback models when primary is degraded).

## Known gaps (honest list)

| Gap | Why it exists | Mitigation today |
|---|---|---|
| `search_files` SKIPs on Windows without `ripgrep` | Environmental, not a code bug | `choco install ripgrep` / `apt install ripgrep`; Linux CI resolves it |
| `execute_code` SKIPs on Windows | Tool's own platform gate | Use Linux/WSL2; Coder has `terminal` as fallback |
| `web_tools` doesn't auto-register in dev | Firecrawl not installed in dev env | Ships with Firecrawl in production |
| Pytest line coverage numbers pending | Background coverage run incomplete at report time | Will regenerate on next overnight pass |
| Inherited tests targeting cut provider adapters fail | Intentional — adapters were ripped out | Delete in a follow-up pass |
| `delegate_task`, `mixture_of_agents`, `session_search` not exercised by QA | Deferred to next-phase orchestrator E2E | Wire into `scripts/orchestrator_e2e.py` after agents stabilize |
| Single-context-window limitation in Path B | Chose Path C over B for demo reasons | Upgrade to Approach B when live subprocess isolation becomes worth the UX cost |

## Open questions

1. **Does Approach B's context isolation actually raise Hunter's finding quality?** Hypothesis: yes, materially. Test: A/B eval with the same task across Path A (fresh contexts via OpenRouter sessions) and Path B (single context). Need the eval harness built first.

2. **Is 2 remediation loops the right cap?** Hypothesis: yes for hackathon tasks; possibly 3 for real issues. Test: instrument loop count distribution over 50 real GitHub issues once ingestion adapter lands.

3. **Should Hunter's JSON findings block be injected by a structured-output tool rather than prose-contracted?** Hypothesis: contract-as-prose is fine when there's a judge in-transcript; structured output becomes valuable when we need to aggregate findings across runs.

4. **When do we need a "Planner" agent?** Hypothesis: on multi-file, multi-component tasks, a pre-Coder planning stage may outperform a single Coder call. Defer until we see evals flag long Coder contexts as a failure mode.

5. **How does this compete with emerging "agent IDE" offerings (Cursor Composer, Cline, Aider)?** Gabru's wedge is the role-separated review loop, especially the enforced Hunter audit. Competitors are mostly single-agent. Need to articulate this on the comparison slide.

## Non-goals (for now)

- ❌ Becoming a general-purpose Claude Code replacement. Gabru is a **specialized** system for the write/test/audit loop.
- ❌ Building our own LLM inference. We wrap OpenRouter + MCP; the model layer is somebody else's job.
- ❌ Re-adding provider adapters we ripped out. Multi-provider adds auth/billing/caching complexity we're not staffed to maintain at quality.
- ❌ Visual IDE plugin in v1. MCP + CLI is enough surface to prove the pattern.

## Attribution & licensing

MIT. Derived from Hermes Agent (Nous Research, MIT) — see [`../LICENSE`](../LICENSE) and [`../NOTICE`](../NOTICE). Attribution is preserved and will stay preserved.
