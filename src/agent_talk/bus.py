"""Append-only file bus. One log per sender, one read ledger per reader."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

from agent_talk.protocol import Message, parse_agent, parse_id


def default_root() -> Path:
    env = os.environ.get("TALK_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".agent-talk"


class Bus:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def init(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def send(self, msg: Message) -> None:
        parse_agent(msg.from_)
        parse_agent(msg.to)
        self.init()
        self._append(self._log_path(msg.from_), (msg.to_json() + "\n").encode())

    def messages(self) -> list[Message]:
        if not self.root.is_dir():
            return []
        found: list[Message] = []
        for path in sorted(self.root.glob("log-*.jsonl")):
            if not path.is_file():
                continue
            found.extend(_read_messages(path))
        found.sort(key=lambda msg: (msg.created_at, msg.id))
        return found

    def inbox(self, agent: str, unread: bool = False) -> list[Message]:
        agent = parse_agent(agent)
        rows = [msg for msg in self.messages() if msg.to == agent]
        if unread:
            seen = self.read_ids(agent)
            rows = [msg for msg in rows if msg.id not in seen]
        return rows

    def read_ids(self, agent: str) -> set[str]:
        agent = parse_agent(agent)
        path = self._read_path(agent)
        if not path.is_file():
            return set()
        return _read_ids(path.read_bytes())

    def mark_read(self, agent: str, ids: list[str] | tuple[str, ...]) -> None:
        agent = parse_agent(agent)
        wanted: list[str] = []
        seen: set[str] = set()
        for msg_id in ids:
            msg_id = parse_id(msg_id)
            if msg_id in seen:
                continue
            seen.add(msg_id)
            wanted.append(msg_id)
        if not wanted:
            return
        self.init()
        path = self._read_path(agent)
        fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                existing = _read_ids(_read_fd(fd))
                fresh = [msg_id for msg_id in wanted if msg_id not in existing]
                if not fresh:
                    return
                payload = "".join(
                    json.dumps({"id": msg_id}) + "\n" for msg_id in fresh
                ).encode()
                _write_all(fd, payload)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def write_run_log(self, agent: str, msg_id: str, text: str) -> Path:
        agent = parse_agent(agent)
        msg_id = parse_id(msg_id)
        path = self.root / "runs" / agent / f"{msg_id}.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _log_path(self, agent: str) -> Path:
        return self.root / f"log-{parse_agent(agent)}.jsonl"

    def _read_path(self, agent: str) -> Path:
        return self.root / f"read-{parse_agent(agent)}.jsonl"

    def _append(self, path: Path, payload: bytes) -> None:
        # O_APPEND keeps the offset honest. The lock stays held across a
        # short write so two processes cannot tear one JSON line.
        fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                _write_all(fd, payload)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]


def _read_fd(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        block = os.read(fd, 65536)
        if not block:
            break
        chunks.append(block)
    return b"".join(chunks)


def _read_ids(raw: bytes) -> set[str]:
    found: set[str] = set()
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("id"), str):
            found.add(obj["id"])
    return found


def _read_messages(path: Path) -> list[Message]:
    found: list[Message] = []
    for line in path.read_bytes().splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            found.append(Message.from_dict(obj))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
            continue
    return found
