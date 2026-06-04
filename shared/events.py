"""Event contracts exchanged between adapters and the core over Redis Streams.

Adapters publish `InboundEvent`s to the inbound stream; the core publishes
`OutboundEvent`s to the outbound stream. Both are serialised as a single JSON
string under the `data` stream field to avoid per-field type loss.
"""

from pydantic import BaseModel, Field


def make_session_id(platform: str, channel_id: str) -> str:
    """Normalised session key. Memory is scoped per platform + channel."""
    return f"{platform}:{channel_id}"


class InboundEvent(BaseModel):
    event_id: str  # business-level UUID (distinct from Redis stream message id)
    platform: str  # "line" | "discord" | "cli" | "http"
    channel_id: str
    session_id: str  # = make_session_id(platform, channel_id)
    user_id: str
    text: str
    message_id: str  # platform-native message id (dedupe / tracing)
    correlation_id: str  # gateways claim their matching outbound by this
    reply_token: str | None = None  # platform reply token, passed through verbatim
    timestamp: float


class OutboundEvent(BaseModel):
    event_id: str
    in_reply_to: str  # source InboundEvent.event_id
    platform: str
    channel_id: str
    session_id: str
    correlation_id: str  # passed through verbatim from the inbound event
    reply_token: str | None = None
    text: str = ""
    reply_message_id: int | None = None  # DB id of the persisted assistant reply
    status: str = "ok"  # "ok" | "error"
    error: str | None = None
    timestamp: float


def to_stream_fields(event: BaseModel) -> dict[str, str]:
    """Serialise an event to Redis stream field-values (single JSON field)."""
    return {"data": event.model_dump_json()}


def inbound_from_stream_fields(fields: dict) -> InboundEvent:
    return InboundEvent.model_validate_json(_data(fields))


def outbound_from_stream_fields(fields: dict) -> OutboundEvent:
    return OutboundEvent.model_validate_json(_data(fields))


def _data(fields: dict) -> str:
    # redis-py may return bytes or str depending on decode_responses.
    value = fields.get("data") or fields.get(b"data")
    if isinstance(value, bytes):
        return value.decode()
    return value
