"""Adapter argv: the force flag is present only when the caller asked."""

import pytest

from agent_talk.adapters import REGISTRY, get
from agent_talk.adapters.claude import CLAUDE
from agent_talk.adapters.codex import CODEX
from agent_talk.adapters.cursor import CURSOR


def test_force_flag_is_added_only_when_requested() -> None:
    assert CURSOR.argv("hello") == [
        "cursor-agent",
        "-p",
        "hello",
        "--output-format",
        "text",
    ]
    assert CURSOR.argv("hello", force=True) == [
        "cursor-agent",
        "-p",
        "hello",
        "--output-format",
        "text",
        "--force",
    ]
    assert CLAUDE.argv("hello") == ["claude", "-p", "hello"]
    assert CLAUDE.argv("hello", force=True) == [
        "claude",
        "-p",
        "hello",
        "--dangerously-skip-permissions",
    ]
    assert CODEX.argv("hello") == ["codex", "exec", "hello"]
    assert CODEX.argv("hello", force=True) == ["codex", "exec", "hello", "--full-auto"]
    for adapter in REGISTRY.values():
        plain = adapter.argv("hello")
        assert adapter.force_flag not in plain
        assert adapter.force_flag in adapter.argv("hello", force=True)


def test_installed_claude_has_no_status_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent_talk.adapters.base.shutil.which", lambda name: f"/bin/{name}")
    assert CLAUDE.status() == "unknown (no status command)"


def test_missing_binary_reports_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent_talk.adapters.base.shutil.which", lambda _name: None)
    assert CLAUDE.status() == "not installed"
    assert CURSOR.status() == "not installed"
    assert CODEX.status() == "not installed"


def test_unknown_harness_is_rejected() -> None:
    with pytest.raises(ValueError):
        get("nope")
