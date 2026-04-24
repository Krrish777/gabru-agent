"""Gabru-Agent orchestrator: Coder -> Tester -> Hunter sequential pipeline.

Accepts a task description (usually a GitHub-issue body) and runs the
three specialized agents in order, chaining each's output into the
next's context. Returns a ``PipelineResult`` with the raw reply from
each station plus a combined markdown report.

This is the stubbed v1 of the orchestrator — it runs serially with no
retry / escalation logic. The user's plan calls out that the
``tools.mixture_of_agents_tool`` primitive can be adapted here for a
more ambitious v2 (debate, critique loops, confidence-weighted merge).
That adaptation is intentionally out of scope for this scaffolding.

Usage:

    from orchestrator import run_pipeline

    result = run_pipeline(
        task="Add a function `reverse_str(s)` to utils.py that reverses a string.",
        api_key=os.environ["OPENROUTER_API_KEY"],
    )
    print(result.report)
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional

from agents.coder import CoderAgent
from agents.hunter import HunterAgent
from agents.tester import TesterAgent

logger = logging.getLogger(__name__)


DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass
class StationResult:
    """Output from one pipeline stage."""

    name: str
    reply: str
    elapsed_seconds: float
    error: Optional[str] = None


@dataclass
class PipelineResult:
    """Aggregate output from a full Coder -> Tester -> Hunter run."""

    task: str
    stations: List[StationResult] = field(default_factory=list)
    started_at: float = 0.0
    ended_at: float = 0.0

    @property
    def total_seconds(self) -> float:
        return self.ended_at - self.started_at

    @property
    def ok(self) -> bool:
        return all(s.error is None for s in self.stations)

    @property
    def report(self) -> str:
        """Render a markdown summary suitable for dumping to stdout or a file."""
        lines = [
            "# Gabru-Agent pipeline report",
            "",
            f"**Task:** {self.task[:500]}",
            f"**Total time:** {self.total_seconds:.1f}s",
            f"**Status:** {'success' if self.ok else 'partial failure'}",
            "",
        ]
        for s in self.stations:
            lines.append(f"## {s.name}  ({s.elapsed_seconds:.1f}s)")
            if s.error:
                lines.append(f"**Error:** {s.error}")
            lines.append("")
            lines.append(s.reply.strip() or "_(empty reply)_")
            lines.append("")
        return "\n".join(lines)


def _run_station(name: str, fn, context: str) -> StationResult:
    logger.info("[%s] starting", name)
    t0 = time.monotonic()
    try:
        reply = fn(context)
        return StationResult(name=name, reply=reply or "", elapsed_seconds=time.monotonic() - t0)
    except Exception as exc:  # noqa: BLE001 — log everything that breaks a station
        logger.exception("[%s] crashed", name)
        return StationResult(
            name=name,
            reply="",
            elapsed_seconds=time.monotonic() - t0,
            error=f"{type(exc).__name__}: {exc}",
        )


def run_pipeline(
    task: str,
    *,
    api_key: Optional[str] = None,
    base_url: str = DEFAULT_BASE_URL,
    model: Optional[str] = None,
    coder_extra_prompt: str = "",
    tester_extra_prompt: str = "",
    hunter_extra_prompt: str = "",
) -> PipelineResult:
    """Run Coder -> Tester -> Hunter sequentially on a task.

    Args:
        task: task description, usually a GitHub-issue body.
        api_key: OpenRouter API key. Falls back to ``OPENROUTER_API_KEY``.
        base_url: OpenAI-compatible endpoint (OpenRouter by default).
        model: LLM slug; each agent picks its own default if None.
        *_extra_prompt: optional role-specific guidance appended to
            the built-in system prompt for each agent.

    Returns:
        PipelineResult with per-station replies and a markdown report.
    """
    key = api_key or os.environ.get("OPENROUTER_API_KEY") or ""
    if not key:
        raise RuntimeError(
            "No OpenRouter API key. Set OPENROUTER_API_KEY or pass api_key=."
        )

    result = PipelineResult(task=task, started_at=time.time())

    coder = CoderAgent(base_url=base_url, api_key=key, model=model)
    tester = TesterAgent(base_url=base_url, api_key=key, model=model)
    hunter = HunterAgent(base_url=base_url, api_key=key, model=model)

    # Station 1: Coder
    coder_result = _run_station(
        "Coder",
        lambda ctx: coder.run(ctx, extra_prompt=coder_extra_prompt),
        task,
    )
    result.stations.append(coder_result)

    # Station 2: Tester — sees the task + the Coder's reply
    tester_context = (
        f"TASK (original):\n{task}\n\n"
        f"CODER REPORT:\n{coder_result.reply}\n\n"
        "Now write unit tests that exercise the Coder's change, run them, and report."
    )
    tester_result = _run_station(
        "Tester",
        lambda ctx: tester.run(ctx, extra_prompt=tester_extra_prompt),
        tester_context,
    )
    result.stations.append(tester_result)

    # Station 3: Hunter — sees task + both prior outputs
    hunter_context = (
        f"TASK (original):\n{task}\n\n"
        f"CODER REPORT:\n{coder_result.reply}\n\n"
        f"TESTER REPORT:\n{tester_result.reply}\n\n"
        "Audit the change for edge cases and security issues."
    )
    hunter_result = _run_station(
        "Hunter",
        lambda ctx: hunter.run(ctx, extra_prompt=hunter_extra_prompt),
        hunter_context,
    )
    result.stations.append(hunter_result)

    result.ended_at = time.time()
    return result


def main(argv: Optional[List[str]] = None) -> int:
    """Minimal CLI so you can `python -m orchestrator "<task>"`."""
    import argparse

    parser = argparse.ArgumentParser(prog="gabru-pipeline")
    parser.add_argument("task", help="Task description or path to a file containing one")
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("-o", "--output", default=None, help="Write report to this path")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    task_text = args.task
    if os.path.isfile(task_text):
        with open(task_text, "r", encoding="utf-8") as fh:
            task_text = fh.read()

    result = run_pipeline(
        task_text,
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
    )
    report = result.report

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(report)
        logger.info("wrote report to %s", args.output)
    else:
        print(report)

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
