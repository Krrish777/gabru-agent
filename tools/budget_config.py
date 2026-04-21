"""Minimal stub for tool-result budget configuration.

The original Hermes budget_config module supported per-tool thresholds,
turn-wide budgets, and preview-size tuning. For Gabru-Agent we ship a
lightweight default that keeps tool_result_storage operational while a
fuller implementation (if needed) is reintroduced later.
"""

from dataclasses import dataclass


DEFAULT_PREVIEW_SIZE_CHARS = 4096
_DEFAULT_THRESHOLD = 32_000
_DEFAULT_TURN_BUDGET = 256_000


@dataclass(frozen=True)
class BudgetConfig:
    """Tool-result budget knobs.

    Attributes:
        preview_size: Max chars in a persisted-result preview.
        default_threshold: Per-tool persistence threshold (chars).
        turn_budget: Aggregate per-turn chars before enforcement kicks in.
    """

    preview_size: int = DEFAULT_PREVIEW_SIZE_CHARS
    default_threshold: int = _DEFAULT_THRESHOLD
    turn_budget: int = _DEFAULT_TURN_BUDGET

    def resolve_threshold(self, tool_name: str) -> int:
        """Return persistence threshold for ``tool_name``.

        The stub applies the same threshold to every tool. A future
        implementation may special-case individual tools.
        """
        return self.default_threshold


DEFAULT_BUDGET = BudgetConfig()
