"""Codex harness."""

from agent_talk.adapters.base import Adapter

CODEX = Adapter(
    name="codex",
    binary="codex",
    prompt_argv=lambda prompt: ["exec", prompt],
    status_argv=("login", "status"),
    force_flag="--full-auto",
)
