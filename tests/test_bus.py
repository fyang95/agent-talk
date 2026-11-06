"""File bus behavior: two senders, receipts, torn lines, concurrent appends."""

import json
import subprocess
import sys
from pathlib import Path

from agent_talk.bus import Bus
from agent_talk.protocol import Message

_WORKER = """
import sys
from pathlib import Path
from agent_talk.bus import Bus
from agent_talk.protocol import Message

root = Path(sys.argv[1])
start = int(sys.argv[2])
count = int(sys.argv[3])
bus = Bus(root)
for i in range(count):
    bus.send(Message.create(
        from_="writer",
        to="reader",
        type="task",
        subject="batch",
        body=f"{start}:{i}",
    ))
"""


def test_two_senders_land_in_one_inbox_sorted(tmp_path: Path) -> None:
    bus = Bus(tmp_path)
    later = Message.create(
        from_="alice",
        to="bob",
        type="task",
        subject="second",
        body="from alice",
        id="msg_later",
        created_at="2026-01-01T00:00:02Z",
    )
    earlier = Message.create(
        from_="cara",
        to="bob",
        type="question",
        subject="first",
        body="from cara",
        id="msg_earlier",
        created_at="2026-01-01T00:00:01Z",
    )
    other = Message.create(
        from_="alice",
        to="cara",
        type="task",
        subject="side",
        body="not for bob",
        id="msg_side",
        created_at="2026-01-01T00:00:03Z",
    )
    bus.send(later)
    bus.send(earlier)
    bus.send(other)
    assert (tmp_path / "log-alice.jsonl").is_file()
    assert (tmp_path / "log-cara.jsonl").is_file()
    assert [msg.id for msg in bus.inbox("bob")] == ["msg_earlier", "msg_later"]
    assert [msg.id for msg in bus.inbox("cara")] == ["msg_side"]


def test_unread_and_mark_read_are_idempotent(tmp_path: Path) -> None:
    bus = Bus(tmp_path)
    first = Message.create(
        from_="alice",
        to="bob",
        type="task",
        subject="one",
        body="1",
        id="msg_one",
        created_at="2026-01-01T00:00:01Z",
    )
    second = Message.create(
        from_="alice",
        to="bob",
        type="task",
        subject="two",
        body="2",
        id="msg_two",
        created_at="2026-01-01T00:00:02Z",
    )
    bus.send(first)
    bus.send(second)
    assert [msg.id for msg in bus.inbox("bob", unread=True)] == ["msg_one", "msg_two"]
    bus.mark_read("bob", ["msg_one", "msg_one"])
    bus.mark_read("bob", ["msg_one"])
    assert [msg.id for msg in bus.inbox("bob", unread=True)] == ["msg_two"]
    assert bus.read_ids("bob") == {"msg_one"}
    bus.mark_read("bob", ["msg_one", "msg_two"])
    bus.mark_read("bob", ["msg_two"])
    assert bus.inbox("bob", unread=True) == []
    lines = (tmp_path / "read-bob.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines == [json.dumps({"id": "msg_one"}), json.dumps({"id": "msg_two"})]


def test_torn_and_invalid_lines_are_skipped(tmp_path: Path) -> None:
    bus = Bus(tmp_path)
    kept = Message.create(
        from_="alice",
        to="bob",
        type="task",
        subject="kept",
        body="ok",
        id="msg_kept",
        created_at="2026-01-01T00:00:01Z",
    )
    bus.send(kept)
    path = tmp_path / "log-alice.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
        handle.write('{"id": "msg_cut"')
    found = bus.messages()
    assert [msg.id for msg in found] == ["msg_kept"]
    assert bus.inbox("bob") == found


def test_concurrent_appends_from_one_sender_stay_intact(tmp_path: Path) -> None:
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _WORKER, str(tmp_path), str(part), "200"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for part in range(4)
    ]
    for proc in procs:
        _out, err = proc.communicate(timeout=60)
        assert proc.returncode == 0, err
    raw_lines = (tmp_path / "log-writer.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(raw_lines) == 800
    for line in raw_lines:
        Message.from_dict(json.loads(line))
    bodies = {msg.body for msg in Bus(tmp_path).messages()}
    assert bodies == {f"{part}:{i}" for part in range(4) for i in range(200)}
