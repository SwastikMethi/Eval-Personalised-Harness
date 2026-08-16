"""OpenAI provider (spec §4).

Added for the repository analyzer rather than for benchmarking: deciding how a
repo can be evaluated at all is a setup-time judgement, and it is worth paying
for a capable model once per repo instead of guessing and discovering the
mistake as INSUFFICIENT_EVALUATION_SIGNAL after a run.

Nothing stops it being used as a run provider — combinations choose their own —
but note it is billed per token, so `is_free` stays False and the free-tier
reasoning that governs OpenRouter does not apply here.
"""

import re
from typing import Any

from app.providers.base import CompletionResult
from app.providers.openai_compat import OpenAICompatibleProvider

DEFAULT_BASE_URL = "https://api.openai.com/v1"

# These families fixed sampling at temperature 1 and reject an explicit value
# outright ("does not support 0 with this model"), including the 0.0 callers
# send for reproducibility. gpt-4.x still honours 0.0, so unlike the token-cap
# spelling this genuinely varies by model and cannot be a class attribute.
_FIXED_TEMPERATURE = re.compile(r"^(gpt-5|o[0-9])")


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"
    default_base_url = DEFAULT_BASE_URL
    is_free_tier = False
    # gpt-5.x rejects `max_tokens` with a 400; gpt-4.x accepts either. Measured
    # against the live API, so the newer spelling is correct for the whole
    # family and needs no per-model branching.
    max_tokens_field = "max_completion_tokens"

    async def complete(
        self, model_id: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> CompletionResult:
        # Dropped rather than coerced to 1.0: the vendor default IS 1, so
        # omitting says "we could not honour the request" instead of implying
        # the caller asked for it. Callers that need determinism must pin a
        # model that still supports temperature=0 (the gpt-4.x family).
        if _FIXED_TEMPERATURE.match(model_id):
            kwargs.pop("temperature", None)
        return await super().complete(model_id, messages, **kwargs)
