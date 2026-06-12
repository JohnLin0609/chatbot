"""Tracked fire-and-forget tasks.

Bare asyncio.create_task results can be garbage-collected mid-flight and are
silently dropped on shutdown. spawn() keeps a strong reference until the task
finishes; drain() lets a process flush stragglers (eval logging, async fact
extraction) before exiting.
"""

import asyncio
from typing import Awaitable

_tasks: set[asyncio.Task] = set()


def spawn(coro: Awaitable) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


async def drain(timeout: float = 10.0) -> None:
    """Wait for in-flight background tasks (best-effort, bounded)."""
    pending = {t for t in _tasks if not t.done()}
    if pending:
        await asyncio.wait(pending, timeout=timeout)
