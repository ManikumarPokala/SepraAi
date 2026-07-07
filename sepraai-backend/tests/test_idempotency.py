"""
SepraAI v2.7 — Idempotency & Transaction Safety Tests

Tests the idempotency rules (Patch #1):
- Verifies atomic_chunk_commit wraps cache insertion and status updates in a single transaction.
- Verifies duplicate tasks trigger the re-commit rule and return matching cached assets.
"""

import pytest
import uuid
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Chunk, ChunkStatus, AssetCache
from core.concurrency import atomic_chunk_commit, aggregate_job_rollup
from workers.run_worker_manim import render_manim_chunk_task


@pytest.mark.asyncio
async def test_atomic_chunk_commit_transaction():
    """
    Asserts that atomic_chunk_commit executes cache addition and status update
    as part of the same transaction context.
    """
    mock_session = MagicMock(spec=AsyncSession)
    mock_session.begin = MagicMock()
    
    # Mock optimistic_update within transaction
    with patch("core.concurrency.optimistic_update", new_callable=AsyncMock) as mock_opt:
        await atomic_chunk_commit(
            session=mock_session,
            chunk_id=uuid.uuid4(),
            content_hash="a" * 64,
            storage_path="/buckets/assets/output.mp4",
            video_path="/buckets/assets/output.mp4",
            audio_path="/buckets/assets/output.wav",
            version=1,
        )
        
        # Verify transaction boundary was invoked
        mock_session.begin.assert_called_once()
        
        # Verify the AssetCache object was registered to session
        mock_session.add.assert_called_once()
        added_obj = mock_session.add.call_args[0][0]
        assert isinstance(added_obj, AssetCache)
        assert added_obj.content_hash == "a" * 64
        
        # Verify optimistic_update was triggered to mark status
        mock_opt.assert_called_once()
        _, kwargs = mock_opt.call_args
        assert kwargs["values_to_update"]["status"] == ChunkStatus.RENDERED
        assert kwargs["values_to_update"]["video_path"] == "/buckets/assets/output.mp4"


@pytest.mark.asyncio
@patch("workers.run_worker_manim.get_db_session")
@patch("workers.run_worker_manim.optimistic_update", new_callable=AsyncMock)
@patch("workers.run_worker_manim.aggregate_job_rollup", new_callable=AsyncMock)
async def test_worker_idempotency_noop_ack(
    mock_rollup,
    mock_opt,
    mock_get_db_session,
):
    """
    Asserts that if the task was already completed (RENDERED status),
    the worker executes the no-op path, re-commits status, and skips running shell commands.
    """
    chunk_id = uuid.uuid4()
    mock_chunk = Chunk(
        id=chunk_id,
        status=ChunkStatus.RENDERED,
        version=2,
        video_path="/bucket/cache/vid.mp4",
        audio_path="/bucket/cache/aud.wav",
        video_part_job_id=uuid.uuid4(),
    )
    
    # Mock DB queries return
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.begin = MagicMock()
    
    mock_result_chunk = MagicMock()
    mock_result_chunk.scalar_one_or_none.return_value = mock_chunk
    
    mock_result_cache = MagicMock()
    mock_result_cache.scalar_one_or_none.return_value = None
    
    # Setup execute side effects for the queries
    mock_session.execute.side_effect = [mock_result_chunk, mock_result_cache]
    
    mock_db_context = AsyncMock()
    mock_db_context.__aenter__.return_value = mock_session
    mock_get_db_session.return_value = mock_db_context
    
    # Trigger task run
    ctx = {"job": MagicMock()}
    code = "import manim"
    
    with patch("workers.run_worker_manim.run_sandboxed_command") as mock_cmd:
        res = await render_manim_chunk_task(ctx, chunk_id, code)
        
        # Verify it skipped execution command entirely
        mock_cmd.assert_not_called()
        
        # Verify it re-committed terminal state to protect against stuck states (Patch #1 Re-commit)
        mock_opt.assert_called_once()
        assert res["status"] == "success"
        assert res["video_path"] == "/bucket/cache/vid.mp4"
        
        # Verify job rollup was triggered to update parent status
        mock_rollup.assert_called_once()
