"""Message envelope shared by every harness."""

from __future__ import annotations

import json
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

# Crockford base32. I, L, O, and U are omitted so ids survive a messy copy.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_AGENT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_KEYS = (
    "id",
    "from",
    "to",
    "type",
    "subject",
    "body",
    "reply_to",
    "artifacts",
    "created_at",
)


class MessageType(str, Enum):
    task = "task"
    reply = "reply"
    evidence = "evidence"
    question = "question"
    done = "done"
    blocked = "blocked"


@dataclass(frozen=True)
class _TypeRule:
    wakes: bool
    # When this is set, a message of the type with no artifacts is reported
    # as that type instead. A done with nothing attached is not done.
    without_artifacts: MessageType | None = None


_RULES: dict[MessageType, _TypeRule] = {
    MessageType.task: _TypeRule(wakes=True),
    MessageType.reply: _TypeRule(wakes=False),
    MessageType.evidence: _TypeRule(wakes=False),
    MessageType.question: _TypeRule(wakes=True),
    MessageType.done: _TypeRule(wakes=False, without_artifacts=MessageType.blocked),
    MessageType.blocked: _TypeRule(wakes=False),
}

# Replies stay out of this set so two daemons cannot wake each other forever.
WAKES: frozenset[MessageType] = frozenset(
    kind for kind, rule in _RULES.items() if rule.wakes
)


def parse_agent(name: str) -> str:
    if not isinstance(name, str) or _AGENT_RE.fullmatch(name) is None:
        raise ValueError(f"invalid agent name: {name!r}")
    return name


def parse_id(value: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise ValueError(f"invalid message id: {value!r}")
    return value


def new_id() -> str:
    """Return msg_ plus a 26-character Crockford ULID.

    The high 48 bits are the Unix time in milliseconds. The low 80 bits
    come from secrets. Big-endian text sorts by time.
    """
    millis = time.time_ns() // 1_000_000
    millis &= (1 << 48) - 1
    value = (millis << 80) | secrets.randbits(80)
    chars: list[str] = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "msg_" + "".join(reversed(chars))


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_created_at(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(f"invalid created_at: {value!r}")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise ValueError(f"invalid created_at: {value!r}") from None
    return value


@dataclass(frozen=True)
class Message:
    id: str
    from_: str
    to: str
    type: MessageType
    subject: str
    body: str
    reply_to: str | None
    artifacts: tuple[str, ...]
    created_at: str

    def __post_init__(self) -> None:
        parse_id(self.id)
        parse_agent(self.from_)
        parse_agent(self.to)
        if not isinstance(self.type, MessageType):
            raise ValueError(f"invalid message type: {self.type!r}")
        if not isinstance(self.subject, str) or not isinstance(self.body, str):
            raise ValueError("subject and body must be strings")
        if self.reply_to is not None:
            parse_id(self.reply_to)
        if not isinstance(self.artifacts, tuple) or any(
            not isinstance(item, str) for item in self.artifacts
        ):
            raise ValueError("artifacts must be a list of strings")
        _parse_created_at(self.created_at)

    @classmethod
    def create(
        cls,
        *,
        from_: str,
        to: str,
        type: MessageType | str,
        subject: str,
        body: str,
        reply_to: str | None = None,
        artifacts: tuple[str, ...] | list[str] = (),
        id: str | None = None,
        created_at: str | None = None,
    ) -> Message:
        if isinstance(artifacts, str):
            raise ValueError("artifacts must be a list of strings")
        if isinstance(type, MessageType):
            type_value: object = type.value
        else:
            type_value = type
        return cls.from_dict(
            {
                "id": new_id() if id is None else id,
                "from": from_,
                "to": to,
                "type": type_value,
                "subject": subject,
                "body": body,
                "reply_to": reply_to,
                "artifacts": list(artifacts),
                "created_at": _utc_now() if created_at is None else created_at,
            }
        )

    def to_json(self) -> str:
        payload = {
            "id": self.id,
            "from": self.from_,
            "to": self.to,
            "type": self.type.value,
            "subject": self.subject,
            "body": self.body,
            "reply_to": self.reply_to,
            "artifacts": list(self.artifacts),
            "created_at": self.created_at,
        }
        return json.dumps(payload, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: object) -> Message:
        if not isinstance(data, dict):
            raise ValueError("message must be a JSON object")
        missing = [key for key in _KEYS if key not in data]
        if missing:
            raise ValueError("message missing " + ", ".join(missing))
        raw_type = data["type"]
        if not isinstance(raw_type, str):
            raise ValueError(f"invalid message type: {raw_type!r}")
        try:
            msg_type = MessageType(raw_type)
        except ValueError:
            raise ValueError(f"invalid message type: {raw_type!r}") from None
        artifacts = data["artifacts"]
        if not isinstance(artifacts, list):
            raise ValueError("artifacts must be a list of strings")
        reply_to = data["reply_to"]
        if reply_to is not None and not isinstance(reply_to, str):
            raise ValueError("reply_to must be a string or null")
        return cls(
            id=data["id"],
            from_=data["from"],
            to=data["to"],
            type=msg_type,
            subject=data["subject"],
            body=data["body"],
            reply_to=reply_to,
            artifacts=tuple(artifacts),
            created_at=data["created_at"],
        )


def effective_type(msg: Message) -> MessageType:
    rule = _RULES[msg.type]
    if rule.without_artifacts is not None and not msg.artifacts:
        return rule.without_artifacts
    return msg.type
