# 01 — Vision & Business Perspective

## The problem we set out to solve

Writing production code is not a single skill. It's three in a trench coat:

1. **Implementing** the change
2. **Testing** the change
3. **Auditing** the change for security / edge-case issues

Single-agent "AI coder" demos (Copilot, Cursor autocomplete, one-shot Claude) flatten these into a single loop where the same model writes, tests, and reviews its own work. That's like asking the author of a patch to be their own reviewer — it works, but the quality ceiling is low, and the security blind spots are exactly the places a self-review can't see.

Our bet: **splitting these three roles into specialized agents with disjoint tool access produces higher-quality, safer code than any single-agent setup, at the same unit cost.**

## The market framing

| Segment | Current tooling | What they lack |
|---|---|---|
| Solo developers | Copilot, Cursor, Claude Code | One model, one perspective, no adversarial review |
| Small teams | GitHub Copilot Enterprise, Code Review bots | Testing and security review are bolted on, not structurally required |
| Enterprise | CodeQL, Semgrep, Snyk, in-house review | Each tool is siloed; no orchestration of "write → test → audit" as a single workflow |

Gabru-Agent targets the **autonomous-development** tier that sits above "AI autocomplete" and below "humans-in-the-loop PR review". It is the thing you hand a GitHub issue to.

## Why a multi-agent system, not a better prompt

Prompting a single model with "be a coder, then be a tester, then be a reviewer" works for toy tasks. It breaks down in practice because:

- **Context contamination** — the reviewer can see the coder's internal monologue ("I think this handles empty strings"), which biases the audit. A clean adversarial review needs to see **only the output**, not the reasoning.
- **Tool-access isolation** — a coder with `osv_check` wastes tokens running vulnerability scans it was never asked for; a reviewer with `write_file` will happily rewrite code instead of reporting findings. The only reliable way to enforce role boundaries is to remove the tools.
- **Prompt drift** — a long single-agent conversation slowly loses the role signal. Three shorter conversations keep each role sharp.

Gabru encodes role discipline in the **tool-list allow-list**, not in prose. That is the defensible architectural claim.

## What winning looks like (success metrics)

Short-term (hackathon + first 90 days):

| Metric | Today | Target |
|---|---|---|
| Senior-QA harness pass rate | 42/45 (93%) | 45/45 on Linux CI |
| Pytest collection | 5,517 collected | ≥95% pass on retained surface |
| Tools in registry | 26 exposed | 30+ with Hunter wired to `bandit` / `semgrep` |
| Live demo round-trip | ~15s Coder + Tester + Hunter on reverse_str | < 30s on a real GitHub issue |
| Remediation loop | Capped at 2 iterations | Same cap; 0 known loops-to-cap in benchmark |

Medium-term (productization):

- GitHub-issue ingestion adapter → close real issues end-to-end
- Eval harness with synthetic fixtures and LLM-judge scoring
- Frontend UI (not required for hackathon; helpful for non-technical stakeholders)

## Commercial model (if productized)

| Segment | Delivery | Willingness to pay |
|---|---|---|
| Individual developers | CLI + MCP, bring-your-own-key | Low (open-source substitutes exist) |
| Teams (5–50 devs) | Hosted MCP + org-scoped skill packs | Medium — priced per seat, security compliance is the wedge |
| Enterprise | Self-hosted with SSO + audit logs + custom toolsets | High — priced on compliance posture, not per-API-call |

The **security-review agent (Hunter)** is the enterprise wedge. It's the thing that moves the product from "nice dev tool" to "auditable code-quality layer" for regulated industries (fintech, healthcare, public sector).

## The on-stage narrative

Three beats, stated in full in [`../presentation-content.md`](../presentation-content.md):

1. **Problem** — Single-agent coders can't reliably self-review. Costly, brittle, unsafe.
2. **Solution** — Three specialized agents with enforced tool boundaries, orchestrated as a manifest.
3. **Proof** — Live demo: judge dictates a task, manifest comes back visibly, three stages execute visibly, report renders, optionally the remediation loop fires. No staging, no hidden prompts.

The point the slide deck should land is **"one model, three disciplined roles, shared body"** — because that's what gives us the quality ceiling neither single-agent coders nor loose multi-agent swarms can reach.
