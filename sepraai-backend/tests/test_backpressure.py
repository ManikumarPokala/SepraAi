"""
SepraAI v2.7 — Gateway Backpressure Test Suite

Validates the Backpressure Rule (Patch #9):
- Mocks Redis queue length checks.
- Asserts request proceeds when depth is within safety thresholds.
- Asserts request is blocked with HTTP 429 and Retry-After header when queues are saturated.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.backpressure import QueueBackpressureMiddleware, get_redis_queue_depth
from core.config import settings


@pytest.mark.asyncio
async def test_backpressure_under_limit():
    """Asserts that requests proceed normally when the queue depth is under the configured limit."""
    mock_redis = AsyncMock()
    # Mocking Redis key size for arq:queue
    mock_redis.hlen = AsyncMock(return_value=10)
    mock_redis.zcard = AsyncMock(return_value=5)

    depth = await get_redis_queue_depth(mock_redis)
    assert depth == 5 # zcard cardinality matches queue length

    # Validate middleware passes request
    app = FastAPI()
    middleware = QueueBackpressureMiddleware(app, redis_client=mock_redis)
    
    mock_request = MagicMock(spec=Request)
    mock_request.url.path = "/generate"
    mock_request.method = "POST"
    
    async def mock_call_next(req):
        return JSONResponse(status_code=200, content={"status": "dispatched"})

    response = await middleware.dispatch(mock_request, mock_call_next)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_backpressure_over_limit():
    """Asserts that gateway blocks ingestion returning 429 when queues are saturated."""
    mock_redis = AsyncMock()
    # Mocking Redis key size exceeding backpressure limit (500)
    mock_redis.zcard = AsyncMock(return_value=600)

    depth = await get_redis_queue_depth(mock_redis)
    assert depth == 600

    app = FastAPI()
    middleware = QueueBackpressureMiddleware(app, redis_client=mock_redis)
    
    mock_request = MagicMock(spec=Request)
    mock_request.url.path = "/generate"
    mock_request.method = "POST"

    async def mock_call_next(req):
        return JSONResponse(status_code=200, content={"status": "dispatched"})

    response = await middleware.dispatch(mock_request, mock_call_next)
    assert response.status_code == 429
    assert response.headers.get("retry-after") == "30"
    
    import json
    body = json.loads(response.body.decode())
    assert "saturated" in body["message"]
