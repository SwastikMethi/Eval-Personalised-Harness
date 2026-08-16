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

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from app.providers.base import ModelProvider
from app.providers.openrouter import ProviderError

# Long enough that re-submitting a matrix does not re-probe, short enough that
# enabling a model in a provider's console is picked up without a restart.
CACHE_TTL_S = 900.0

_cache: dict[tuple[str, str], tuple[float, "ProbeResult"]] = {}


# A one-token probe should be quick. deepseek-v4-flash takes 72-218s per call
# and NIM's gateway gives up around 302s, so without our own bound, pressing
# Start could hang for minutes and then wrongly refuse a model that works.
# Exceeding this means "slow", never "broken".
PROBE_TIMEOUT_S = 25.0


@dataclass(frozen=True)
class ProbeResult:
    provider: str
    model_id: str
    ok: bool
    detail: str = ""
    # Usable, with something the user should know — "slow", or a transient
    # upstream error. Availability is not a binary: deepseek-v4-flash works and
    # is slow, and refusing it would remove a legitimate competitor from the
    # comparison on our infrastructure's terms.
    warning: str = ""

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
        await asyncio.wait_for(
            provider.complete(
                model_id,
                [{"role": "user", "content": "ok"}],
                max_tokens=1,
                temperature=0.0,
            ),
            timeout=PROBE_TIMEOUT_S,
        )
        result = ProbeResult(requested, model_id, True)
    except TimeoutError:
        # Slow is not broken. deepseek-v4-flash needs 72-218s per call and
        # completed seven of them in one run; refusing it here would delete a
        # working combination from the comparison.
        result = ProbeResult(
            requested,
            model_id,
            True,
            warning=(
                f"slow: no answer to a one-token prompt within {PROBE_TIMEOUT_S:.0f}s"
            ),
        )
    except ProviderError as exc:
        # Only a rejection that will never succeed disqualifies a model. A 404
        # ("not enabled for this account") is final; a 429 or a 5xx is not, and
        # the queue already parks and retries those.
        if not exc.retryable:
            result = ProbeResult(requested, model_id, False, str(exc)[:300])
        else:
            result = ProbeResult(
                requested, model_id, True, warning=f"transient upstream error: {exc}"[:200]
            )
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
    unique: list[tuple[str, str]] = []
    for combo in combinations:
        key = (combo.provider, combo.model_id)
        if key not in seen:
            seen.add(key)
            unique.append(key)

    # Concurrently, because these were awaited one after another and each probe
    # costs whatever the model costs — gpt-oss-120b measured 21s, so a two-model
    # matrix meant ~40s of a dead Start button. Wall time is now the slowest
    # single probe rather than their sum.
    return list(
        await asyncio.gather(
            *(probe(provider_for(name), model_id, name) for name, model_id in unique)
        )
    )
