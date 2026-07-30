import time

import httpx
import pytest

from app.api import proxy
from app.main import create_app


@pytest.fixture
async def client():  # type: ignore[no-untyped-def]
    app = create_app(start_worker=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


MODEL = "fake/deterministic-1:free"


def chat_body() -> dict[str, object]:
    return {"model": MODEL, "messages": [{"role": "user", "content": "hi"}]}


async def _post(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.post(
        "/proxy/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json=chat_body(),
    )


async def test_request_budget_exhaustion(client: httpx.AsyncClient) -> None:
    token = proxy.issue_run_token("run-a", MODEL, max_requests=2)
    try:
        assert (await _post(client, token)).status_code == 200
        assert (await _post(client, token)).status_code == 200
        resp = await _post(client, token)
        assert resp.status_code == 429
        assert "request budget" in resp.json()["detail"]
    finally:
        proxy.revoke_run_token("run-a")


async def test_output_token_budget(client: httpx.AsyncClient) -> None:
    token = proxy.issue_run_token("run-b", MODEL, max_output_tokens=1)
    try:
        assert (await _post(client, token)).status_code == 200  # first passes, records usage
        resp = await _post(client, token)
        assert resp.status_code == 429
        assert "output-token budget" in resp.json()["detail"]
    finally:
        proxy.revoke_run_token("run-b")


async def test_spend_ceiling(client: httpx.AsyncClient) -> None:
    token = proxy.issue_run_token(
        "run-c", MODEL, max_cost_usd=0.0001, input_price=1.0, output_price=1.0
    )
    try:
        assert (await _post(client, token)).status_code == 200
        resp = await _post(client, token)
        assert resp.status_code == 429
        assert "spend ceiling" in resp.json()["detail"]
    finally:
        proxy.revoke_run_token("run-c")


async def test_token_expiry_and_renewal(client: httpx.AsyncClient) -> None:
    token = proxy.issue_run_token("run-d", MODEL)
    try:
        proxy._active_tokens["run-d"].expires_at = time.time() - 1
        resp = await _post(client, token)
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"]

        proxy.renew_run_token("run-d")
        assert (await _post(client, token)).status_code == 200
    finally:
        proxy.revoke_run_token("run-d")


async def test_revoked_token_rejected(client: httpx.AsyncClient) -> None:
    token = proxy.issue_run_token("run-e", MODEL)
    proxy.revoke_run_token("run-e")
    resp = await _post(client, token)
    assert resp.status_code == 401


async def test_metric_persisted(client: httpx.AsyncClient) -> None:
    from sqlalchemy import select

    from app.db.engine import SessionLocal
    from app.models import ModelRequestMetric

    token = proxy.issue_run_token("run-f", MODEL)
    try:
        assert (await _post(client, token)).status_code == 200
    finally:
        proxy.revoke_run_token("run-f")
    with SessionLocal() as session:
        metrics = session.scalars(
            select(ModelRequestMetric).where(ModelRequestMetric.run_id == "run-f")
        ).all()
    assert len(metrics) == 1
    assert metrics[0].model_id == MODEL
    assert metrics[0].http_status == 200
