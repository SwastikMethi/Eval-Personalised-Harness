"""Analyzer provider selection.

The previous suggest endpoint hardcoded OpenRouter and returned 409 without an
OpenRouter key, so someone holding only an Anthropic key could not use the
feature at all. Selection is configurable, with "auto" preferring the strongest
reasoning available rather than failing.
"""

import pytest

from app.core.config import Settings
from app.repositories.analyzer import AnalyzerUnavailable, select_analyzer


def settings_with(**kw: str) -> Settings:
    base = {
        "anthropic_api_key": "",
        "openai_api_key": "",
        "openrouter_api_key": "",
        "nvidia_api_key": "",
        "analyzer_provider": "auto",
        "analyzer_model": "",
    }
    return Settings(**{**base, **kw})  # type: ignore[arg-type]


def test_auto_prefers_anthropic_when_available() -> None:
    a = select_analyzer(settings_with(anthropic_api_key="k", openai_api_key="k"))
    assert a.provider_name == "anthropic"
    assert a.provider.name == "anthropic"


def test_auto_falls_through_to_whatever_is_configured() -> None:
    assert select_analyzer(settings_with(openai_api_key="k")).provider_name == "openai"
    assert select_analyzer(settings_with(nvidia_api_key="k")).provider_name == "nvidia"


def test_explicit_choice_is_honoured() -> None:
    a = select_analyzer(
        settings_with(anthropic_api_key="k", openai_api_key="k", analyzer_provider="openai")
    )
    assert a.provider_name == "openai"


def test_explicit_choice_without_a_key_says_which_key_is_missing() -> None:
    with pytest.raises(AnalyzerUnavailable, match="ANALYZER_PROVIDER=anthropic"):
        select_analyzer(settings_with(openai_api_key="k", analyzer_provider="anthropic"))


def test_no_keys_at_all_names_every_option() -> None:
    with pytest.raises(AnalyzerUnavailable) as exc:
        select_analyzer(settings_with())
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "NVIDIA_API_KEY"):
        assert key in str(exc.value)


def test_model_override_beats_the_default() -> None:
    a = select_analyzer(settings_with(anthropic_api_key="k"), model_id="claude-opus-5")
    assert a.model_id == "claude-opus-5"
    assert a.provenance == {"provider": "anthropic", "model": "claude-opus-5"}


# --- model resolution -------------------------------------------------------
# A hardcoded default was wrong the first time it met a real account: "gpt-5"
# was invented in source and does not exist there. Resolve against the listing.


class FakeListing:
    def __init__(self, ids: list[str]) -> None:
        self._ids = ids

    async def list_models(self):  # type: ignore[no-untyped-def]
        from app.providers.base import ModelInfo

        return [
            ModelInfo(
                provider="fake", model_id=i, display_name=i, context_length=None,
                supports_tools=None, supports_structured_output=None,
                input_price_per_token=0.0, output_price_per_token=0.0, is_free=False,
                availability_status="available", is_alias=False,
            )
            for i in self._ids
        ]


def analyzer_for(name: str, ids: list[str], model_id: str = ""):  # type: ignore[no-untyped-def]
    from app.repositories.analyzer import Analyzer

    return Analyzer(provider=FakeListing(ids), provider_name=name, model_id=model_id)  # type: ignore[arg-type]


async def test_the_chosen_models_are_preferred() -> None:
    from app.repositories.analyzer import resolve_model

    anthropic = await resolve_model(
        analyzer_for("anthropic", ["claude-sonnet-5", "claude-opus-5"])
    )
    assert anthropic == "claude-opus-5"

    openai = await resolve_model(analyzer_for("openai", ["gpt-4.1", "gpt-5.5", "gpt-5.6-sol"]))
    assert openai == "gpt-5.6-sol"


async def test_resolution_falls_to_the_next_preference_when_absent() -> None:
    """An account without the first choice must still resolve, rather than
    404 in the middle of an analysis."""
    from app.repositories.analyzer import resolve_model

    chosen = await resolve_model(analyzer_for("openai", ["gpt-4.1", "gpt-4o"]))
    assert chosen == "gpt-4.1"


async def test_resolution_rejects_a_model_the_account_cannot_call() -> None:
    from app.repositories.analyzer import resolve_model

    with pytest.raises(AnalyzerUnavailable, match="not available"):
        await resolve_model(analyzer_for("openai", ["gpt-4o"], model_id="gpt-9-imaginary"))


async def test_resolution_says_what_to_set_when_nothing_matches() -> None:
    from app.repositories.analyzer import resolve_model

    with pytest.raises(AnalyzerUnavailable, match="ANALYZER_MODEL"):
        await resolve_model(analyzer_for("openai", ["some-other-model"]))
