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

# Preferences, not assertions. A hardcoded single default was wrong the first
# time it met a real account: "gpt-5" does not exist there, and a model id
# invented in source is the same class of error as a fabricated metric. The
# choice is resolved against the provider's own listing, so an account without
# the first preference gets the next one instead of a 404 mid-analysis.
DEFAULT_MODEL_PREFERENCES = {
    "anthropic": ("claude-opus-5", "claude-sonnet-5"),
    "openai": ("gpt-5.6-sol", "gpt-5.5", "gpt-4.1"),
    "openrouter": ("cohere/north-mini-code:free",),
    "nvidia": ("openai/gpt-oss-120b",),
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

    # Empty means "resolve against the provider's listing" — see resolve_model.
    chosen = model_id or settings.analyzer_model or ""
    return Analyzer(provider=_build(name, settings), provider_name=name, model_id=chosen)


async def resolve_model(analyzer: Analyzer) -> str:
    """Settle the analyzer's model against what the account can actually call.

    Verifying costs one listing request and turns "model_not_found" in the
    middle of an analysis into a clear error before anything is spent.
    """
    available = {m.model_id for m in await analyzer.provider.list_models()}

    if analyzer.model_id:
        if analyzer.model_id not in available:
            raise AnalyzerUnavailable(
                f"{analyzer.model_id} is not available on this {analyzer.provider_name} "
                f"account. Available include: {sorted(available)[:8]}"
            )
        return analyzer.model_id

    for candidate in DEFAULT_MODEL_PREFERENCES[analyzer.provider_name]:
        if candidate in available:
            analyzer.model_id = candidate
            return candidate

    raise AnalyzerUnavailable(
        f"none of the preferred {analyzer.provider_name} models are available on this "
        f"account ({DEFAULT_MODEL_PREFERENCES[analyzer.provider_name]}). Set ANALYZER_MODEL "
        f"to one of: {sorted(available)[:8]}"
    )
