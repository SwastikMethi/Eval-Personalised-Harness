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
