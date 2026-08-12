"""Which model analyses a repository, and with what default.

Repository analysis is a setup-time judgement made once per repo, not part of a
benchmarked run: it never goes through the run-scoped proxy (there is no run,
and the key must not leave the backend either way).

Provider choice is configurable because the user holds the keys, not us. "auto"
prefers the strongest reasoning available rather than failing when one key is
absent — the previous endpoint hardcoded OpenRouter and returned 409 without it,
which made the feature unavailable to someone holding an Anthropic key.
"""

from dataclasses import dataclass

from app.core.config import Settings
from app.providers.base import ModelProvider

# Preference order for "auto". Analysis quality decides whether the benchmark
# can score at all, so a capable model first, then the free tier as a fallback.
PREFERENCE = ("anthropic", "openai", "openrouter", "nvidia")

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-5",
    "openrouter": "cohere/north-mini-code:free",
    "nvidia": "openai/gpt-oss-120b",
}


class AnalyzerUnavailable(Exception):
    """No provider key is configured for repository analysis."""


@dataclass
class Analyzer:
    provider: ModelProvider
    provider_name: str
    model_id: str

    @property
    def provenance(self) -> dict[str, str]:
        return {"provider": self.provider_name, "model": self.model_id}


def _configured(settings: Settings) -> dict[str, str]:
    return {
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
        "openrouter": settings.openrouter_api_key,
        "nvidia": settings.nvidia_api_key,
    }


def _build(name: str, settings: Settings) -> ModelProvider:
    if name == "anthropic":
        from app.providers.anthropic import AnthropicProvider

        return AnthropicProvider(
            api_key=settings.anthropic_api_key, base_url=settings.anthropic_base_url
        )
    if name == "openai":
        from app.providers.openai_api import OpenAIProvider

        return OpenAIProvider(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    if name == "nvidia":
        from app.providers.nim import NimProvider

        return NimProvider(api_key=settings.nvidia_api_key, base_url=settings.nvidia_base_url)
    from app.providers.openrouter import OpenRouterProvider

    return OpenRouterProvider(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        http_referer=settings.openrouter_http_referer,
        app_name=settings.openrouter_app_name,
    )


def select_analyzer(settings: Settings, model_id: str | None = None) -> Analyzer:
    keys = _configured(settings)
    wanted = settings.analyzer_provider

    if wanted and wanted != "auto":
        if not keys.get(wanted):
            raise AnalyzerUnavailable(
                f"ANALYZER_PROVIDER={wanted} but no key is configured for it — "
                f"set its API key in .env, or use ANALYZER_PROVIDER=auto"
            )
        name = wanted
    else:
        name = next((p for p in PREFERENCE if keys.get(p)), "")
        if not name:
            raise AnalyzerUnavailable(
                "no provider key configured — set ANTHROPIC_API_KEY, OPENAI_API_KEY, "
                "OPENROUTER_API_KEY or NVIDIA_API_KEY in .env to analyse a repository"
            )

    chosen = model_id or settings.analyzer_model or DEFAULT_MODELS[name]
    return Analyzer(provider=_build(name, settings), provider_name=name, model_id=chosen)
