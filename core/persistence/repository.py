"""Data-access helpers over the ORM models.

These operate on a passed AsyncSession and flush (to populate ids) but do NOT
commit — the caller owns the transaction boundary so a turn's user+assistant
rows land atomically.
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.persistence.models import (
    AppSetting,
    Message,
    MessageFeedback,
    Session,
    Summary,
    UserMemory,
)


async def ensure_session(
    db: AsyncSession, session_key: str, platform: str, channel_id: str
) -> Session:
    """Upsert a session row by session_key and bump last_active_at."""
    result = await db.execute(
        select(Session).where(Session.session_key == session_key)
    )
    session = result.scalar_one_or_none()
    if session is None:
        session = Session(
            session_key=session_key, platform=platform, channel_id=channel_id
        )
        db.add(session)
    else:
        from sqlalchemy import func

        session.last_active_at = func.now()
    await db.flush()
    return session


async def append_message(
    db: AsyncSession,
    session_id: int,
    role: str,
    content: str,
    platform_message_id: str | None = None,
    user_id: str | None = None,
) -> Message:
    message = Message(
        session_id=session_id,
        role=role,
        content=content,
        platform_message_id=platform_message_id,
        user_id=user_id,
    )
    db.add(message)
    await db.flush()
    return message


async def load_session_messages_after(
    db: AsyncSession, session_id: int, after_id: int | None
) -> list[Message]:
    """A session's messages with id > after_id (None -> all), oldest-first."""
    stmt = select(Message).where(Message.session_id == session_id)
    if after_id is not None:
        stmt = stmt.where(Message.id > after_id)
    stmt = stmt.order_by(Message.id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def session_user_ids(db: AsyncSession, session_id: int) -> list[str]:
    """Distinct non-null user_ids that spoke in a session."""
    result = await db.execute(
        select(Message.user_id)
        .where(Message.session_id == session_id, Message.user_id.is_not(None))
        .distinct()
    )
    return [r for (r,) in result.all() if r]


async def load_recent(
    db: AsyncSession, session_id: int, limit: int
) -> list[Message]:
    """Return up to `limit` most-recent messages, oldest-first."""
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    rows.reverse()  # chronological order for prompt assembly
    return rows


async def save_summary(
    db: AsyncSession,
    session_id: int,
    summary_text: str,
    turn_count: int,
    covers_through_message_id: int | None = None,
) -> Summary:
    summary = Summary(
        session_id=session_id,
        summary_text=summary_text,
        turn_count=turn_count,
        covers_through_message_id=covers_through_message_id,
    )
    db.add(summary)
    await db.flush()
    return summary


async def idle_unfinalized_sessions(
    db: AsyncSession, cutoff, limit: int
) -> list[Session]:
    """Sessions idle since before `cutoff` that still need finalising — never
    finalised, or active again since the last finalisation."""
    from sqlalchemy import or_

    result = await db.execute(
        select(Session)
        .where(
            Session.last_active_at < cutoff,
            or_(
                Session.finalized_at.is_(None),
                Session.finalized_at < Session.last_active_at,
            ),
        )
        .order_by(Session.last_active_at)
        .limit(limit)
    )
    return list(result.scalars().all())


async def delete_session_by_key(db: AsyncSession, session_key: str) -> bool:
    """Delete a session and all its messages/summaries/feedback. Returns True if a
    session existed. Feedback rows are removed first (they FK message ids and aren't
    covered by the ORM relationship cascade); the session's messages+summaries go via
    the Session relationship cascade ("all, delete-orphan")."""
    result = await db.execute(
        select(Session).where(Session.session_key == session_key)
    )
    session = result.scalar_one_or_none()
    if session is None:
        return False
    msg_ids = (
        await db.execute(
            select(Message.id).where(Message.session_id == session.id)
        )
    ).scalars().all()
    if msg_ids:
        await db.execute(
            delete(MessageFeedback).where(MessageFeedback.message_id.in_(msg_ids))
        )
    await db.delete(session)
    await db.flush()
    return True


# ------------------------------------------------------------- app settings (KV)
async def get_app_setting(db: AsyncSession, key: str) -> str | None:
    row = await db.get(AppSetting, key)
    return row.value if row else None


async def upsert_app_setting(db: AsyncSession, key: str, value: str) -> None:
    row = await db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    await db.flush()


async def delete_app_setting(db: AsyncSession, key: str) -> None:
    row = await db.get(AppSetting, key)
    if row is not None:
        await db.delete(row)
        await db.flush()


async def get_latest_summary(db: AsyncSession, session_id: int) -> Summary | None:
    result = await db.execute(
        select(Summary)
        .where(Summary.session_id == session_id)
        .order_by(Summary.created_at.desc(), Summary.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


# ----------------------------------------------------------- user memory (tier-3)
async def get_user_memory(db: AsyncSession, user_key: str) -> UserMemory | None:
    result = await db.execute(
        select(UserMemory).where(UserMemory.user_key == user_key)
    )
    return result.scalar_one_or_none()


async def upsert_user_memory(
    db: AsyncSession,
    user_key: str,
    document: dict,
    last_extracted_message_id: int | None = None,
) -> UserMemory:
    row = await get_user_memory(db, user_key)
    if row is None:
        row = UserMemory(
            user_key=user_key,
            document=document,
            last_extracted_message_id=last_extracted_message_id,
        )
        db.add(row)
    else:
        row.document = document
        if last_extracted_message_id is not None:
            row.last_extracted_message_id = last_extracted_message_id
    await db.flush()
    return row


async def load_messages_after(
    db: AsyncSession, user_id: str, after_id: int | None, limit: int = 200
) -> list[Message]:
    """A user's messages (across sessions) newer than `after_id`, oldest-first."""
    stmt = select(Message).where(Message.user_id == user_id)
    if after_id is not None:
        stmt = stmt.where(Message.id > after_id)
    stmt = stmt.order_by(Message.id).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())
