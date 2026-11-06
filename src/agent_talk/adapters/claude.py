"""Claude Code harness."""

from agent_talk.adapters.base import Adapter

CLAUDE = Adapter(
    name="claude",
    binary="claude",
    prompt_argv=lambda prompt: ["-p", prompt],
    status_argv=None,
    force_flag="--dangerously-skip-permissions",
)
