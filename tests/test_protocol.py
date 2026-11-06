"""Envelope behavior: round trip, ids, names, and done-without-evidence."""

import json

import pytest

from agent_talk.protocol import (
    Message,
    MessageType,
    WAKES,
    effective_type,
    new_id,
    parse_agent,
)

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _decode(text: str) -> int:
    value = 0
    for char in text:
        value = (value << 5) | _ALPHABET.index(char)
    return value


def test_roundtrip_preserves_envelope_order_and_from_key() -> None:
    msg = Message.create(
        from_="claude",
        to="cursor-a",
        type=MessageType.task,
        subject="build login form",
        body="line one\nline two",
        reply_to=None,
        artifacts=("spec.md", "notes.md"),
    )
    raw = msg.to_json()
    assert "\n" not in raw
    parsed = json.loads(raw)
    assert list(parsed) == [
        "id",
        "from",
        "to",
        "type",
        "subject",
        "body",
        "reply_to",
        "artifacts",
        "created_at",
    ]
    assert parsed["from"] == "claude"
    assert parsed["body"] == "line one\nline two"
    assert Message.from_dict(parsed) == msg


def test_ids_are_unique_crockford_ulids() -> None:
    ids = [new_id() for _ in range(200)]
    assert len(set(ids)) == 200
    for item in ids:
        assert item.startswith("msg_")
        body = item[4:]
        assert len(body) == 26
        assert set(body) <= set(_ALPHABET)


def test_id_packs_time_then_random(monkeypatch: pytest.MonkeyPatch) -> None:
    def at(millis: int, bits: int) -> str:
        monkeypatch.setattr(
            "agent_talk.protocol.time.time_ns",
            lambda: millis * 1_000_000,
        )
        monkeypatch.setattr("agent_talk.protocol.secrets.randbits", lambda _n: bits)
        return new_id()

    zero = at(0, 0)
    assert zero == "msg_" + ("0" * 26)
    one = at(1, 0)
    decoded = _decode(one[4:])
    assert decoded < (1 << 128)
    assert decoded >> 80 == 1
    assert decoded & ((1 << 80) - 1) == 0

    early = at(1_700_000_000_000, (1 << 80) - 1)
    late = at(1_700_000_000_001, 0)
    assert early < late
    assert early[:14] < late[:14]


def test_same_millisecond_ids_share_a_time_prefix_and_differ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agent_talk.protocol.time.time_ns",
        lambda: 1_700_000_000_000 * 1_000_000,
    )
    ids = [new_id() for _ in range(40)]
    assert len(set(ids)) == 40
    assert len({item[:14] for item in ids}) == 1


@pytest.mark.parametrize("name", ["../x", "A", "", "has space", "claude/x"])
def test_bad_agent_names_are_rejected(name: str) -> None:
    with pytest.raises(ValueError):
        parse_agent(name)
    with pytest.raises(ValueError):
        Message.create(
            from_=name,
            to="cursor",
            type="task",
            subject="s",
            body="b",
        )
    payload = json.loads(
        Message.create(
            from_="claude",
            to="cursor",
            type="task",
            subject="s",
            body="b",
        ).to_json()
    )
    payload["to"] = name
    with pytest.raises(ValueError):
        Message.from_dict(payload)


def test_done_without_artifacts_is_blocked() -> None:
    empty = Message.create(
        from_="cursor",
        to="claude",
        type="done",
        subject="shipped",
        body="trust me",
    )
    assert effective_type(empty) is MessageType.blocked
    attached = Message.create(
        from_="cursor",
        to="claude",
        type="done",
        subject="shipped",
        body="see the diff",
        artifacts=("diff.patch",),
    )
    assert effective_type(attached) is MessageType.done


@pytest.mark.parametrize("kind", list(MessageType))
def test_every_type_with_an_artifact_keeps_its_type(kind: MessageType) -> None:
    msg = Message.create(
        from_="a",
        to="b",
        type=kind,
        subject="s",
        body="c",
        artifacts=("evidence.txt",),
    )
    assert effective_type(msg) is kind


def test_only_task_and_question_wake() -> None:
    assert WAKES == frozenset({MessageType.task, MessageType.question})


def test_from_dict_rejects_a_bad_shape() -> None:
    good = json.loads(
        Message.create(
            from_="claude",
            to="cursor",
            type="task",
            subject="s",
            body="b",
        ).to_json()
    )
    with pytest.raises(ValueError):
        Message.from_dict(["nope"])
    bad_type = dict(good)
    bad_type["type"] = "nope"
    with pytest.raises(ValueError):
        Message.from_dict(bad_type)
    missing = dict(good)
    del missing["body"]
    with pytest.raises(ValueError):
        Message.from_dict(missing)
