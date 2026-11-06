"""Cursor harness."""

from agent_talk.adapters.base import Adapter

CURSOR = Adapter(
    name="cursor",
    binary="cursor-agent",
    prompt_argv=lambda prompt: ["-p", prompt, "--output-format", "text"],
    status_argv=("status",),
    force_flag="--force",
)
