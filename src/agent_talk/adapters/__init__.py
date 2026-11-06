"""One adapter per vendor CLI."""

from agent_talk.adapters.base import Adapter
from agent_talk.adapters.claude import CLAUDE
from agent_talk.adapters.codex import CODEX
from agent_talk.adapters.cursor import CURSOR

REGISTRY: dict[str, Adapter] = {
    "claude": CLAUDE,
    "cursor": CURSOR,
    "codex": CODEX,
}


def get(harness: str) -> Adapter:
    try:
        return REGISTRY[harness]
    except KeyError:
        known = ", ".join(REGISTRY)
        raise ValueError(f"unknown harness: {harness!r} ({known})") from None
