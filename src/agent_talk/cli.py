"""talk command."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_talk.adapters import REGISTRY, get
from agent_talk.bus import Bus, default_root
from agent_talk.daemon import run, watch
from agent_talk.protocol import Message, MessageType, effective_type, parse_agent


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ValueError as exc:
        print(f"talk: error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="talk",
        description="Local file bus for messages between coding agents.",
    )
    parser.add_argument(
        "--home",
        type=Path,
        help="bus directory. Overrides TALK_HOME for this command.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    init_cmd = commands.add_parser("init", help="create the bus directory")
    init_cmd.set_defaults(func=_cmd_init)

    agents_cmd = commands.add_parser("agents", help="show harness binaries and login status")
    agents_cmd.set_defaults(func=_cmd_agents)

    send_cmd = commands.add_parser("send", help="append a message to the sender log")
    send_cmd.add_argument("--from", dest="from_agent", required=True, metavar="AGENT")
    send_cmd.add_argument("--to", required=True, metavar="AGENT")
    send_cmd.add_argument("--subject", required=True)
    send_cmd.add_argument("--body", required=True, help="message body, or - to read stdin")
    send_cmd.add_argument(
        "--type",
        default=MessageType.task.value,
        choices=[kind.value for kind in MessageType],
    )
    send_cmd.add_argument("--reply-to", dest="reply_to", metavar="ID")
    send_cmd.add_argument("--artifact", action="append", default=[], metavar="PATH")
    send_cmd.set_defaults(func=_cmd_send)

    inbox_cmd = commands.add_parser("inbox", help="list messages addressed to an agent")
    inbox_cmd.add_argument("--agent", required=True, metavar="AGENT")
    inbox_cmd.add_argument("--unread", action="store_true")
    inbox_cmd.add_argument("--mark-read", action="store_true")
    inbox_cmd.add_argument("--json", action="store_true")
    inbox_cmd.set_defaults(func=_cmd_inbox)

    read_cmd = commands.add_parser("read", help="mark messages read")
    read_cmd.add_argument("--agent", required=True, metavar="AGENT")
    read_cmd.add_argument("ids", nargs="+", metavar="ID")
    read_cmd.set_defaults(func=_cmd_read)

    daemon_cmd = commands.add_parser("daemon", help="deliver unread tasks by spawning a harness")
    daemon_cmd.add_argument("--agent", required=True, metavar="AGENT")
    daemon_cmd.add_argument("--harness", choices=tuple(REGISTRY))
    daemon_cmd.add_argument("--force", action="store_true")
    daemon_cmd.add_argument("--once", action="store_true")
    daemon_cmd.add_argument("--interval", type=float, default=2)
    daemon_cmd.add_argument("--timeout", type=float, default=900)
    daemon_cmd.add_argument("--cwd", type=Path)
    daemon_cmd.set_defaults(func=_cmd_daemon)

    watch_cmd = commands.add_parser("watch", help="print messages as they land")
    watch_cmd.add_argument("--no-follow", action="store_true")
    watch_cmd.add_argument("--interval", type=float, default=1)
    watch_cmd.set_defaults(func=_cmd_watch)
    return parser


def _cmd_init(args: argparse.Namespace) -> int:
    bus = _bus(args)
    bus.init()
    print(bus.root)
    return 0


def _cmd_agents(_args: argparse.Namespace) -> int:
    rows = []
    for name, adapter in REGISTRY.items():
        found = adapter.detect() or "-"
        rows.append((name, found, adapter.status()))
    print(_table(("harness", "binary", "status"), rows))
    return 0


def _cmd_send(args: argparse.Namespace) -> int:
    body = sys.stdin.read() if args.body == "-" else args.body
    msg = Message.create(
        from_=args.from_agent,
        to=args.to,
        type=args.type,
        subject=args.subject,
        body=body,
        reply_to=args.reply_to,
        artifacts=tuple(args.artifact),
    )
    _bus(args).send(msg)
    print(msg.id)
    return 0


def _cmd_inbox(args: argparse.Namespace) -> int:
    agent = parse_agent(args.agent)
    bus = _bus(args)
    msgs = bus.inbox(agent, unread=args.unread)
    if args.json:
        for msg in msgs:
            print(msg.to_json())
    elif msgs:
        print("\n\n".join(_format_message(msg) for msg in msgs))
    if args.mark_read and msgs:
        bus.mark_read(agent, [msg.id for msg in msgs])
    return 0


def _cmd_read(args: argparse.Namespace) -> int:
    agent = parse_agent(args.agent)
    _bus(args).mark_read(agent, args.ids)
    return 0


def _cmd_daemon(args: argparse.Namespace) -> int:
    agent = parse_agent(args.agent)
    if args.interval < 0:
        raise ValueError("--interval must be >= 0")
    if args.timeout <= 0:
        raise ValueError("--timeout must be > 0")
    harness = args.harness
    if harness is None:
        if agent not in REGISTRY:
            known = ", ".join(REGISTRY)
            raise ValueError(
                f"no harness named {agent!r}. Pass --harness ({known})."
            )
        harness = agent
    get(harness)
    cwd = args.cwd if args.cwd is not None else Path.cwd()
    if not cwd.is_dir():
        raise ValueError(f"--cwd is not a directory: {cwd}")
    run(
        _bus(args),
        agent,
        harness,
        force=args.force,
        interval=args.interval,
        once=args.once,
        cwd=str(cwd),
        timeout=args.timeout,
        log=lambda line: print(line, file=sys.stderr, flush=True),
    )
    return 0


def _cmd_watch(args: argparse.Namespace) -> int:
    if args.interval < 0:
        raise ValueError("--interval must be >= 0")
    watch(_bus(args), interval=args.interval, follow=not args.no_follow)
    return 0


def _bus(args: argparse.Namespace) -> Bus:
    if args.home is not None:
        root = Path(args.home).expanduser()
    else:
        root = default_root()
    return Bus(root)


def _format_message(msg: Message) -> str:
    header = (
        f"{msg.id}  {msg.created_at}  {msg.from_}  {_type_label(msg)}  {msg.subject}"
    )
    body_lines = msg.body.splitlines() or [""]
    indented = "\n".join(f"  {line}" for line in body_lines)
    return f"{header}\n{indented}"


def _type_label(msg: Message) -> str:
    shown = effective_type(msg)
    if shown is msg.type:
        return msg.type.value
    return f"{msg.type.value}->{shown.value}"


def _table(header: tuple[str, str, str], rows: list[tuple[str, str, str]]) -> str:
    widths = [
        max(len(header[col]), *(len(row[col]) for row in rows))
        for col in range(len(header))
    ]

    def line(cells: tuple[str, ...]) -> str:
        return "  ".join(
            cell.ljust(widths[col]) for col, cell in enumerate(cells)
        ).rstrip()

    return "\n".join([line(header), *(line(row) for row in rows)])
