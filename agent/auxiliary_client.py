"""Minimal stub for the removed Hermes auxiliary_client module.

The original module wrapped multiple provider SDKs (Anthropic, Codex/Responses,
Gemini, custom OpenAI endpoints) and exposed them behind a unified call_llm /
async_call_llm API for auxiliary uses (title generation, vision, context
compression, web summaries).

Gabru-Agent has not yet re-implemented this surface. This stub keeps top-level
imports resolvable so the retained modules (context_compressor, title_generator,
web_tools, session_search_tool, mixture_of_agents_tool, etc.) can be imported
for test collection. Calling into the stubs at runtime raises
NotImplementedError so the absence is loud rather than silent.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

OMIT_TEMPERATURE = object()
_AI_GATEWAY_HEADERS: Dict[str, str] = {}
_OR_HEADERS: Dict[str, str] = {}
_API_KEY_PROVIDER_AUX_MODELS: Dict[str, Any] = {}
_PROVIDER_VISION_MODELS: Dict[str, Any] = {}
_client_cache: Dict[Any, Any] = {}


def _raise_removed(name: str) -> None:
    raise NotImplementedError(
        f"agent.auxiliary_client.{name} was removed from Gabru-Agent. "
        "Reintroduce the auxiliary client surface before calling."
    )


def call_llm(*args: Any, **kwargs: Any) -> Any:
    _raise_removed("call_llm")


async def async_call_llm(*args: Any, **kwargs: Any) -> Any:
    _raise_removed("async_call_llm")


def extract_content_or_reasoning(response: Any) -> Tuple[Optional[str], Optional[str]]:
    """Best-effort content extraction used by retained tools.

    Returns (content, reasoning). The real implementation inspected multiple
    provider response shapes; the stub returns (None, None) so callers treat
    the result as an empty completion instead of crashing on attribute access.
    """
    return None, None


def get_text_auxiliary_client(*args: Any, **kwargs: Any) -> Any:
    _raise_removed("get_text_auxiliary_client")


def get_async_text_auxiliary_client(*args: Any, **kwargs: Any) -> Any:
    _raise_removed("get_async_text_auxiliary_client")


def resolve_provider_client(*args: Any, **kwargs: Any) -> Any:
    _raise_removed("resolve_provider_client")


def resolve_vision_provider_client(*args: Any, **kwargs: Any) -> Any:
    _raise_removed("resolve_vision_provider_client")


def get_available_vision_backends(*args: Any, **kwargs: Any) -> list:
    return []


def get_auxiliary_extra_body(*args: Any, **kwargs: Any) -> Optional[Dict[str, Any]]:
    return None


def neuter_async_httpx_del(*args: Any, **kwargs: Any) -> None:
    return None


def shutdown_cached_clients(*args: Any, **kwargs: Any) -> None:
    return None


def cleanup_stale_async_clients(*args: Any, **kwargs: Any) -> None:
    return None


def _fixed_temperature_for_model(model: Optional[str]) -> Any:
    return OMIT_TEMPERATURE


def _get_task_timeout(*args: Any, **kwargs: Any) -> Optional[float]:
    return None


def _codex_cloudflare_headers(*args: Any, **kwargs: Any) -> Dict[str, str]:
    return {}


def _to_openai_base_url(url: Optional[str]) -> Optional[str]:
    return url


def _validate_base_url(url: Optional[str]) -> Optional[str]:
    return url


def _validate_proxy_env_urls(*args: Any, **kwargs: Any) -> None:
    return None


def _resolve_api_key_provider(*args: Any, **kwargs: Any) -> Optional[str]:
    return None


def _is_connection_error(exc: BaseException) -> bool:
    return False


def _build_call_kwargs(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return {}


def _is_anthropic_compat_endpoint(url: Optional[str]) -> bool:
    return False


def _convert_openai_images_to_anthropic(*args: Any, **kwargs: Any) -> Any:
    return None


def _normalize_vision_provider(provider: Optional[str]) -> Optional[str]:
    return provider


def _get_cached_client(*args: Any, **kwargs: Any) -> Any:
    _raise_removed("_get_cached_client")


def _resolve_auto(*args: Any, **kwargs: Any) -> Any:
    _raise_removed("_resolve_auto")


def _try_anthropic(*args: Any, **kwargs: Any) -> Any:
    _raise_removed("_try_anthropic")


def _try_codex(*args: Any, **kwargs: Any) -> Any:
    _raise_removed("_try_codex")


def _try_custom_endpoint(*args: Any, **kwargs: Any) -> Any:
    _raise_removed("_try_custom_endpoint")


class AnthropicAuxiliaryClient:
    """Placeholder for the removed Anthropic auxiliary client."""

    def __init__(self, *args: Any, **kwargs: Any):
        _raise_removed("AnthropicAuxiliaryClient")


class CodexAuxiliaryClient:
    """Placeholder for the removed Codex auxiliary client."""

    def __init__(self, *args: Any, **kwargs: Any):
        _raise_removed("CodexAuxiliaryClient")
