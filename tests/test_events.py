"""Event serialisation round-trips."""

from shared.events import (
    InboundEvent,
    OutboundEvent,
    inbound_from_stream_fields,
    make_session_id,
    outbound_from_stream_fields,
    to_stream_fields,
)


def test_session_id_normalisation():
    assert make_session_id("line", "c1") == "line:c1"


def test_inbound_round_trip():
    ev = InboundEvent(
        event_id="e1", platform="line", channel_id="c1",
        session_id=make_session_id("line", "c1"), user_id="u1", text="hi",
        message_id="m1", correlation_id="corr1", reply_token="tok", timestamp=1.5,
    )
    assert inbound_from_stream_fields(to_stream_fields(ev)) == ev


def test_outbound_round_trip_preserves_correlation():
    ev = OutboundEvent(
        event_id="o1", in_reply_to="e1", platform="line", channel_id="c1",
        session_id="line:c1", correlation_id="corr1", text="hello",
        status="ok", timestamp=2.0,
    )
    back = outbound_from_stream_fields(to_stream_fields(ev))
    assert back == ev
    assert back.correlation_id == "corr1"
