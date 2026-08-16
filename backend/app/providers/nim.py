"""NVIDIA NIM provider (spec §4: "any OpenAI-compatible endpoint").

Exists because the OpenRouter free tier — roughly 50 requests a day without
credits — has been the binding constraint on every real run in this project.
A second provider is headroom, not a replacement: OpenRouter stays, and the
provider is chosen per combination.

What NIM does NOT tell us matters as much as what it does. Its listing carries
only id/object/created/owned_by:

    {"id": "01-ai/yi-large", "object": "model", "created": ..., "owned_by": ...}

No pricing, no context length, no `supported_parameters`. So context length and
tool support are reported as **None — unknown, not unsupported** (spec §31:
mark unavailable metrics as null). Preflight (§21) is what would settle them
empirically. Claiming `supports_tools=False` here would be inventing a
capability report, which is worse than admitting ignorance.

Cost: NIM bills credits, not per-token dollars we can read, so prices stay 0.0
and `is_free` stays False. A NIM run must not display "$0.00" the way a
genuine OpenRouter `:free` model does.

The HTTP handling lives in OpenAICompatibleProvider — NIM's wire protocol is
plain OpenAI, and a second copy of it would only be a place for one to drift.
"""

from app.providers.openai_compat import OpenAICompatibleProvider

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"


class NimProvider(OpenAICompatibleProvider):
    name = "nvidia"
    default_base_url = DEFAULT_BASE_URL
    # Credits, not a free per-token tier. Saying True would present a billed
    # model as free.
    is_free_tier = False
