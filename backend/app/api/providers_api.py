from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.engine import get_session
from app.models import ModelSnapshot
from app.providers.base import ModelProvider
from app.providers.openrouter import OpenRouterProvider, ProviderError

router = APIRouter()


def _provider(name: str) -> ModelProvider:
    """Build a provider by name, or 409 with the key that is missing."""
    if name == "openrouter":
        if not settings.openrouter_api_key:
            raise HTTPException(409, "OPENROUTER_API_KEY not configured — set it in .env")
        return OpenRouterProvider(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            http_referer=settings.openrouter_http_referer,
            app_name=settings.openrouter_app_name,
        )
    if name == "nvidia":
        if not settings.nvidia_api_key:
            raise HTTPException(409, "NVIDIA_API_KEY not configured — set it in .env")
        from app.providers.nim import NimProvider

        return NimProvider(
            api_key=settings.nvidia_api_key, base_url=settings.nvidia_base_url
        )
    raise HTTPException(404, f"unknown provider: {name}")


@router.get("/providers")
def list_providers() -> list[dict[str, Any]]:
    """Providers the UI can offer, and whether each is usable right now."""
    return [
        {
            "name": "openrouter",
            "configured": bool(settings.openrouter_api_key),
            "has_free_tier": True,
        },
        {
            "name": "nvidia",
            "configured": bool(settings.nvidia_api_key),
            # Credit-billed: nothing here is a free per-token tier, so the UI
            # must not offer a "free only" filter that would return nothing.
            "has_free_tier": False,
        },
    ]


@router.get("/providers/{provider}/connection")
async def test_connection(provider: str = "openrouter") -> dict[str, Any]:
    return await _provider(provider).test_connection()


@router.get("/providers/{provider}/models")
async def list_models(
    provider: str = "openrouter", free_only: bool = True, include_aliases: bool = False
) -> list[dict[str, Any]]:
    """Selectable models.

    Moving aliases are excluded by default: `validate_model` refuses to pin
    them, so offering them would only let a user choose something that fails at
    snapshot time. Sorted so free, tool-capable models come first — with 400+
    models the ordering is the difference between usable and unusable.

    `supports_tools` may be None (unknown) for providers whose listing does not
    report capabilities; unknown sorts with the known-capable rather than being
    pushed down as if it were unsupported.
    """
    try:
        models = await _provider(provider).list_models()
    except ProviderError as exc:
        raise HTTPException(502, f"[{exc.category}] {exc}") from exc

    selectable = [
        m
        for m in models
        if (m.is_free or not free_only) and (include_aliases or not m.is_alias)
    ]
    selectable.sort(key=lambda m: (not m.is_free, m.supports_tools is False, m.model_id))
    return [asdict(m) for m in selectable]


@router.post("/providers/{provider}/models/{model_id:path}/snapshot")
async def snapshot_model(
    provider: str, model_id: str, session: Session = Depends(get_session)
) -> dict[str, Any]:
    try:
        info = await _provider(provider).validate_model(model_id)
    except ProviderError as exc:
        raise HTTPException(422, f"[{exc.category}] {exc}") from exc
    snap = ModelSnapshot(provider=provider, model_id=model_id, meta=asdict(info))
    session.add(snap)
    session.commit()
    return {"snapshot_id": snap.id, "model": asdict(info)}
