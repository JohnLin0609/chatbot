"""Stream / consumer-group name resolution.

Names live in Settings so they can be overridden per environment; this module
just provides typed accessors so call sites don't reach into config fields by
string.
"""

from core.config import Settings


def inbound_stream(settings: Settings) -> str:
    return settings.inbound_stream


def outbound_stream(settings: Settings) -> str:
    return settings.outbound_stream


def core_group(settings: Settings) -> str:
    return settings.core_consumer_group


def http_group(settings: Settings) -> str:
    return settings.http_consumer_group


def cli_group(settings: Settings) -> str:
    return settings.cli_consumer_group
