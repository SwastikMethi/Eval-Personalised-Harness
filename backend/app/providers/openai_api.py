"""OpenAI provider (spec §4).

Added for the repository analyzer rather than for benchmarking: deciding how a
repo can be evaluated at all is a setup-time judgement, and it is worth paying
for a capable model once per repo instead of guessing and discovering the
mistake as INSUFFICIENT_EVALUATION_SIGNAL after a run.

Nothing stops it being used as a run provider — combinations choose their own —
but note it is billed per token, so `is_free` stays False and the free-tier
reasoning that governs OpenRouter does not apply here.
"""

from app.providers.openai_compat import OpenAICompatibleProvider

DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"
    default_base_url = DEFAULT_BASE_URL
    is_free_tier = False
