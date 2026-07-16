"""Unit tests for RedisConsumer construction and PEL reclaim.

Coverage:
- test_consumer_accepts_group_kwargs: RedisConsumer(queue_name=..., group_name=...,
  consumer_name=...) constructs — regression for the "got multiple values for
  keyword argument 'queue_name'" TypeError (kwargs were get()-ed but not
  pop()-ed before being forwarded to RedisConnection.__init__).
- test_reclaim_processes_and_acks: reclaim_pending_messages runs reclaimed
  entries through the callback and XACKs them.
- test_reclaim_leaves_failed_unacked: a callback that raises leaves the entry
  unacked (pending for a later sweep) and does not abort the sweep.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


from navigator.brokers.redis.consumer import RedisConsumer


def test_consumer_accepts_group_kwargs():
    consumer = RedisConsumer(
        queue_name="my_stream",
        group_name="my_group",
        consumer_name="worker-1",
    )
    assert consumer._queue_name == "my_stream"
    assert consumer._group_name == "my_group"
    assert consumer._consumer_name == "worker-1"


def _connection_with_pel(entries):
    """A RedisConsumer whose underlying client autoclaims ``entries`` once."""
    conn = RedisConsumer(queue_name="s", group_name="g", consumer_name="c")
    client = MagicMock()
    # First sweep returns the entries, cursor wraps to '0-0' ending the loop.
    client.xautoclaim = AsyncMock(return_value=("0-0", entries, []))
    client.xack = AsyncMock(return_value=1)
    conn._connection = client
    return conn, client


@pytest.mark.asyncio
async def test_reclaim_processes_and_acks():
    entries = [("1-1", {"body": '{"k": 1}', "ContentType": "application/json"})]
    conn, client = _connection_with_pel(entries)
    seen = []

    async def callback(data, processed):
        seen.append((data["message_id"], processed))

    processed = await conn.reclaim_pending_messages("s", callback)

    assert processed == 1
    assert seen and seen[0][0] == "1-1"
    client.xack.assert_awaited_once_with("s", "g", "1-1")


@pytest.mark.asyncio
async def test_reclaim_leaves_failed_unacked():
    entries = [
        ("1-1", {"body": '{"k": 1}', "ContentType": "application/json"}),
        ("1-2", {"body": '{"k": 2}', "ContentType": "application/json"}),
    ]
    conn, client = _connection_with_pel(entries)

    async def callback(data, processed):
        if data["message_id"] == "1-1":
            raise RuntimeError("handler failure")

    processed = await conn.reclaim_pending_messages("s", callback)

    assert processed == 1  # only the healthy entry
    acked = [call.args[2] for call in client.xack.await_args_list]
    assert acked == ["1-2"]  # the failed one stays pending
