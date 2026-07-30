from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.engine import get_session
from app.models import ModelSnapshot
from app.providers.openrouter import OpenRouterProvider, ProviderError

router = APIRouter()


def _openrouter() -> OpenRouterProvider:
    if not settings.openrouter_api_key:
        raise HTTPException(409, "OPENROUTER_API_KEY not configured — set it in .env")
    return OpenRouterProvider(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        http_referer=settings.openrouter_http_referer,
        app_name=settings.openrouter_app_name,
    )


@router.get("/providers/openrouter/connection")
async def test_connection() -> dict[str, Any]:
    return await _openrouter().test_connection()


@router.get("/providers/openrouter/models")
async def list_free_models(free_only: bool = True) -> list[dict[str, Any]]:
    try:
        models = await _openrouter().list_models()
    except ProviderError as exc:
        raise HTTPException(502, f"[{exc.category}] {exc}") from exc
    return [asdict(m) for m in models if m.is_free or not free_only]


@router.post("/providers/openrouter/models/{model_id:path}/snapshot")
async def snapshot_model(
    model_id: str, session: Session = Depends(get_session)
) -> dict[str, Any]:
    try:
        info = await _openrouter().validate_model(model_id)
    except ProviderError as exc:
        raise HTTPException(422, f"[{exc.category}] {exc}") from exc
    snap = ModelSnapshot(provider="openrouter", model_id=model_id, meta=asdict(info))
    session.add(snap)
    session.commit()
    return {"snapshot_id": snap.id, "model": asdict(info)}
