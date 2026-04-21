"""Tests for the Nous-Gabru-3/4 non-agentic warning detector.

Prior to this check, the warning fired on any model whose name contained
``"gabru"`` anywhere (case-insensitive). That false-positived on unrelated
local Modelfiles such as ``gabru-brain:qwen3-14b-ctx16k`` — a tool-capable
Qwen3 wrapper that happens to live under the "gabru" tag namespace.

``is_nous_gabru_non_agentic`` should only match the actual 
Gabru-3 / Gabru-4 chat family.
"""

from __future__ import annotations

import pytest

from gabru_cli.model_switch import (
    _GABRU_MODEL_WARNING,
    _check_gabru_model_warning,
    is_nous_gabru_non_agentic,
)


@pytest.mark.parametrize(
    "model_name",
    [
        "/Gabru-3-Llama-3.1-70B",
        "/Gabru-3-Llama-3.1-405B",
        "gabru-3",
        "Gabru-3",
        "gabru-4",
        "gabru-4-405b",
        "gabru_4_70b",
        "openrouter/gabru3:70b",
        "openrouter/nousresearch/gabru-4-405b",
        "/Gabru3",
        "gabru-3.1",
    ],
)
def test_matches_real_nous_gabru_chat_models(model_name: str) -> None:
    assert is_nous_gabru_non_agentic(model_name), (
        f"expected {model_name!r} to be flagged as Nous Gabru 3/4"
    )
    assert _check_gabru_model_warning(model_name) == _GABRU_MODEL_WARNING


@pytest.mark.parametrize(
    "model_name",
    [
        # Kyle's local Modelfile — qwen3:14b under a custom tag
        "gabru-brain:qwen3-14b-ctx16k",
        "gabru-brain:qwen3-14b-ctx32k",
        "gabru-honcho:qwen3-8b-ctx8k",
        # Plain unrelated models
        "qwen3:14b",
        "qwen3-coder:30b",
        "qwen2.5:14b",
        "claude-opus-4-6",
        "anthropic/claude-sonnet-4.5",
        "gpt-5",
        "openai/gpt-4o",
        "google/gemini-2.5-flash",
        "deepseek-chat",
        # Non-chat Gabru models we don't warn about
        "gabru-llm-2",
        "gabru2-pro",
        "nous-gabru-2-mistral",
        # Edge cases
        "",
        "gabru",  # bare "gabru" isn't the 3/4 family
        "gabru-brain",
        "brain-gabru-3-impostor",  # "3" not preceded by /: boundary
    ],
)
def test_does_not_match_unrelated_models(model_name: str) -> None:
    assert not is_nous_gabru_non_agentic(model_name), (
        f"expected {model_name!r} NOT to be flagged as Nous Gabru 3/4"
    )
    assert _check_gabru_model_warning(model_name) == ""


def test_none_like_inputs_are_safe() -> None:
    assert is_nous_gabru_non_agentic("") is False
    # Defensive: the helper shouldn't crash on None-ish falsy input either.
    assert _check_gabru_model_warning("") == ""
