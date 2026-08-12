"""Prove a model can actually be called, before a matrix is queued (spec §21).

A provider's catalog is not an entitlement list. `deepseek-ai/deepseek-coder-6.7b-instruct`
appears in NIM's /models, so the UI offered it, and the run failed on its first
request with:

    404: Function 'e503b15c…': Not found for account 'NpkMx3LK…'

By then a workspace had been materialised, an image prepared, a container built
and sealed. The reply that made all of it pointless was available in half a
second, for one token.

Kept deliberately cheap — one token, deduplicated per (provider, model), cached
briefly — because a preflight that costs real money is one people turn off, and
then the late failures come back.
"""

import time
from dataclasses import dataclass
from typing import Any

from app.providers.base import ModelProvider
from app.providers.openrouter import ProviderError

# Long enough that re-submitting a matrix does not re-probe, short enough that
# enabling a model in a provider's console is picked up without a restart.
CACHE_TTL_S = 900.0

_cache: dict[tuple[str, str], tuple[float, "ProbeResult"]] = {}


@dataclass(frozen=True)
class ProbeResult:
    provider: str
    model_id: str
    ok: bool
    detail: str = ""

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.model_id}"


def clear_cache() -> None:
    _cache.clear()


async def probe(
    provider: ModelProvider, model_id: str, provider_key: str | None = None
) -> ProbeResult:
    """One minimal completion. Exercises auth, entitlement and generation.

    Listing the model is not enough — that is exactly what missed the 404.

    `provider_key` is what the COMBINATION asked for, which is what the user
    has to change. It can differ from `provider.name`: provider_for() falls
    back to the default when a name is not registered, so reporting the
    resolved provider's name would point at something the user never chose.
    """
    requested = provider_key or provider.name
    key = (requested, model_id)
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_S:
        return cached[1]

    try:
        await provider.complete(
            model_id,
            [{"role": "user", "content": "ok"}],
            max_tokens=1,
            temperature=0.0,
        )
        result = ProbeResult(requested, model_id, True)
    except ProviderError as exc:
        # A rate limit means the model exists and we are simply being
        # throttled; refusing the experiment for that would be wrong, and the
        # queue already parks and retries throttled runs.
        from app.core.errors import ErrorCategory

        if exc.category is ErrorCategory.RATE_LIMITED:
            result = ProbeResult(requested, model_id, True, "rate limited during preflight")
        else:
            result = ProbeResult(requested, model_id, False, str(exc)[:300])
    except Exception as exc:  # noqa: BLE001 - never let preflight itself crash creation
        result = ProbeResult(requested, model_id, False, f"{type(exc).__name__}: {exc}"[:300])

    _cache[key] = (time.monotonic(), result)
    return result


async def check_combinations(
    combinations: list[Any], provider_for: Any
) -> list[ProbeResult]:
    """Probe each UNIQUE (provider, model) once.

    A 2x2 matrix with 3 repetitions is 12 runs but only 4 distinct pairs, and
    probing per run would make preflight cost more than the thing it protects.
    """
    seen: set[tuple[str, str]] = set()
    results: list[ProbeResult] = []
    for combo in combinations:
        key = (combo.provider, combo.model_id)
        if key in seen:
            continue
        seen.add(key)
        results.append(await probe(provider_for(combo.provider), combo.model_id, combo.provider))
    return results
