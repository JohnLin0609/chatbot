"""FeedbackStore: per-user 👍/👎 on assistant replies.

One rating per (message, user). Re-sending the same rating toggles it off
(cancel); sending the opposite flips it. `rate` returns the resulting state
(+1 / -1 / 0). `summary` aggregates for the admin view.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.persistence.models import Message, MessageFeedback


class FeedbackStore:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sm = sessionmaker

    async def rate(self, message_id: int, user_id: str, rating: int) -> int:
        """Upsert/toggle a rating. Returns the new state: +1, -1, or 0 (cleared)."""
        if rating not in (-1, 1):
            raise ValueError("rating must be +1 or -1")
        async with self._sm() as db:
            existing = (
                await db.execute(
                    select(MessageFeedback).where(
                        MessageFeedback.message_id == message_id,
                        MessageFeedback.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                db.add(
                    MessageFeedback(
                        message_id=message_id, user_id=user_id, rating=rating
                    )
                )
                state = rating
            elif existing.rating == rating:
                await db.delete(existing)  # toggle off
                state = 0
            else:
                existing.rating = rating  # flip
                state = rating
            await db.commit()
            return state

    async def get_for_user(self, message_ids: list[int], user_id: str) -> dict[int, int]:
        """Map message_id -> this user's rating, for the given messages."""
        if not message_ids:
            return {}
        async with self._sm() as db:
            rows = (
                await db.execute(
                    select(MessageFeedback.message_id, MessageFeedback.rating).where(
                        MessageFeedback.message_id.in_(message_ids),
                        MessageFeedback.user_id == user_id,
                    )
                )
            ).all()
            return {mid: r for (mid, r) in rows}

    async def summary(self, recent_negative: int = 20) -> dict:
        """Totals (up/down) plus the most recent 👎 replies (for the admin view)."""
        async with self._sm() as db:
            up = (
                await db.execute(
                    select(func.count()).where(MessageFeedback.rating == 1)
                )
            ).scalar_one()
            down = (
                await db.execute(
                    select(func.count()).where(MessageFeedback.rating == -1)
                )
            ).scalar_one()
            rows = (
                await db.execute(
                    select(
                        MessageFeedback.message_id,
                        Message.content,
                        MessageFeedback.updated_at,
                    )
                    .join(Message, Message.id == MessageFeedback.message_id)
                    .where(MessageFeedback.rating == -1)
                    .order_by(MessageFeedback.updated_at.desc())
                    .limit(recent_negative)
                )
            ).all()
            negatives = [
                {
                    "message_id": mid,
                    "content": content,
                    "at": at.isoformat() if at else None,
                }
                for (mid, content, at) in rows
            ]
            return {"up": up, "down": down, "recent_negative": negatives}
