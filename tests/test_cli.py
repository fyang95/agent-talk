"""CLI behavior for init, send, inbox, and watch."""

import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path


def _talk() -> str:
    path = Path(sys.executable).with_name("talk")
    assert path.exists(), f"missing console script at {path}"
    return str(path)


def _run(home: Path, *args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["TALK_HOME"] = str(home)
    env["PYTHONUNBUFFERED"] = "1"
    extra = kwargs.pop("env", None)
    if isinstance(extra, dict):
        env.update(extra)
    return subprocess.run(
        [_talk(), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        **kwargs,
    )


def test_home_flag_overrides_talk_home(tmp_path: Path) -> None:
    via_flag = tmp_path / "flag"
    via_env = tmp_path / "env"
    env = os.environ.copy()
    env["TALK_HOME"] = str(via_env)
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.run(
        [_talk(), "--home", str(via_flag), "init"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == str(via_flag)
    assert via_flag.is_dir()
    assert not via_env.exists()
    again = subprocess.run(
        [_talk(), "--home", str(via_flag), "init"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert again.returncode == 0
    assert again.stdout.strip() == str(via_flag)


def test_send_prints_only_the_id_and_rejects_a_bad_agent(tmp_path: Path) -> None:
    home = tmp_path / "bus"
    sent = _run(
        home,
        "send",
        "--from",
        "claude",
        "--to",
        "cursor",
        "--subject",
        "build login form",
        "--body",
        "Implement per spec.md.",
    )
    assert sent.returncode == 0
    assert sent.stderr == ""
    assert sent.stdout.strip().startswith("msg_")
    assert "\n" not in sent.stdout.strip()
    bad = _run(
        home,
        "send",
        "--from",
        "../x",
        "--to",
        "cursor",
        "--subject",
        "s",
        "--body",
        "b",
    )
    assert bad.returncode == 2
    assert bad.stdout == ""
    assert bad.stderr.startswith("talk: error:")


def test_body_dash_reads_stdin(tmp_path: Path) -> None:
    home = tmp_path / "bus"
    sent = _run(
        home,
        "send",
        "--from",
        "claude",
        "--to",
        "cursor",
        "--subject",
        "stdin",
        "--body",
        "-",
        input="from stdin\n",
    )
    assert sent.returncode == 0
    inbox = _run(home, "inbox", "--agent", "cursor", "--json")
    msg = json.loads(inbox.stdout)
    assert msg["body"] == "from stdin\n"


def test_inbox_shows_done_without_artifacts_as_blocked(tmp_path: Path) -> None:
    home = tmp_path / "bus"
    _run(
        home,
        "send",
        "--from",
        "cursor",
        "--to",
        "claude",
        "--type",
        "done",
        "--subject",
        "ship it",
        "--body",
        "trust me\nreally",
    )
    human = _run(home, "inbox", "--agent", "claude")
    assert human.returncode == 0
    assert "done->blocked" in human.stdout
    assert "ship it" in human.stdout
    assert "\n  trust me\n  really" in human.stdout
    raw = _run(home, "inbox", "--agent", "claude", "--json")
    msg = json.loads(raw.stdout)
    assert msg["type"] == "done"
    assert msg["artifacts"] == []


def test_send_keeps_artifact_and_reply_to(tmp_path: Path) -> None:
    home = tmp_path / "bus"
    parent = _run(
        home,
        "send",
        "--from",
        "claude",
        "--to",
        "cursor",
        "--subject",
        "parent",
        "--body",
        "go",
    )
    parent_id = parent.stdout.strip()
    sent = _run(
        home,
        "send",
        "--from",
        "cursor",
        "--to",
        "claude",
        "--type",
        "reply",
        "--subject",
        "re: parent",
        "--body",
        "done",
        "--reply-to",
        parent_id,
        "--artifact",
        "diff.patch",
        "--artifact",
        "test.log",
    )
    assert sent.returncode == 0, sent.stderr
    msg = json.loads(_run(home, "inbox", "--agent", "claude", "--json").stdout)
    assert msg["type"] == "reply"
    assert msg["reply_to"] == parent_id
    assert msg["artifacts"] == ["diff.patch", "test.log"]


def test_mark_read_flag_hides_the_printed_ids(tmp_path: Path) -> None:
    home = tmp_path / "bus"
    _run(
        home,
        "send",
        "--from",
        "claude",
        "--to",
        "cursor",
        "--subject",
        "s",
        "--body",
        "b",
    )
    shown = _run(home, "inbox", "--agent", "cursor", "--mark-read", "--json")
    assert shown.stdout.strip() != ""
    unread = _run(home, "inbox", "--agent", "cursor", "--unread", "--json")
    assert unread.stdout == ""


def test_mark_read_hides_a_message_from_unread(tmp_path: Path) -> None:
    home = tmp_path / "bus"
    sent = _run(
        home,
        "send",
        "--from",
        "claude",
        "--to",
        "cursor",
        "--subject",
        "s",
        "--body",
        "b",
    )
    msg_id = sent.stdout.strip()
    first = _run(home, "inbox", "--agent", "cursor", "--unread", "--json")
    assert msg_id in first.stdout
    marked = _run(home, "read", "--agent", "cursor", msg_id)
    assert marked.returncode == 0
    assert marked.stdout == ""
    second = _run(home, "inbox", "--agent", "cursor", "--unread", "--json")
    assert second.stdout == ""
    again = _run(home, "read", "--agent", "cursor", msg_id)
    assert again.returncode == 0
    still = _run(home, "inbox", "--agent", "cursor", "--json")
    assert msg_id in still.stdout


def test_watch_no_follow_prints_one_line_per_message(tmp_path: Path) -> None:
    home = tmp_path / "bus"
    _run(
        home,
        "send",
        "--from",
        "claude",
        "--to",
        "cursor",
        "--subject",
        "build login form",
        "--body",
        "go",
    )
    proc = _run(home, "watch", "--no-follow")
    assert proc.returncode == 0
    line = proc.stdout.strip()
    assert " claude -> cursor [task] build login form (msg_" in line
    clock, *_rest = line.split(" ", 1)
    assert len(clock) == 8 and clock[2] == ":" and clock[5] == ":"


def test_watch_follow_prints_a_message_that_arrives_later(tmp_path: Path) -> None:
    home = tmp_path / "bus"
    home.mkdir()
    env = os.environ.copy()
    env["TALK_HOME"] = str(home)
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [_talk(), "watch", "--interval", "0.05"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        sent = _run(
            home,
            "send",
            "--from",
            "claude",
            "--to",
            "cursor",
            "--subject",
            "late",
            "--body",
            "arrived",
        )
        msg_id = sent.stdout.strip()
        assert proc.stdout is not None
        deadline = time.monotonic() + 3
        chunks: list[str] = []
        while time.monotonic() < deadline and msg_id not in "".join(chunks):
            ready, _, _ = select.select([proc.stdout], [], [], 0.2)
            if ready:
                chunks.append(proc.stdout.readline())
        heard = "".join(chunks)
        assert msg_id in heard
        assert "[task] late" in heard
    finally:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=3)
    assert proc.returncode == 0
