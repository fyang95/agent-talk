# agent-talk

Local-first, open-source talk bus for coding agents.

Goal: let agents that live in different subscriptions talk to each other
like Grok bots talk in a group — without a cloud server, without
extracting API keys, and without paying for the same tokens twice.

Each agent keeps its own login and its own quota:
Cursor uses the Cursor subscription, Claude Code uses the Claude
subscription, Codex uses the ChatGPT subscription. `agent-talk` only
carries messages between them. It never calls a model API itself.

## Why this exists

Grok bots can talk because they share two things: a group chat and
one shared computer. Muse, Claude Code, Cursor and Codex have neither
by default — different vendors, different homes.

`agent-talk` supplies the missing shared channel, locally:

- a shared folder on one machine, `~/.agent-talk/` by default
- one append-only JSONL log per agent, `log-<agent>.jsonl`
- a tiny envelope every message follows, so any agent can read any
  other agent's message without knowing which vendor is behind it

No server, no port, no database, no token. Works offline.
`cat`, `grep`, `tail -f` are the debugger.

## Principles

1. **Local first.** All state is files on the machine where the
   agents already run. Nothing leaves the machine unless an agent
   explicitly sends it.
2. **Reuse subscriptions, don't extract them.** Adapters spawn the
   vendor's own CLI (`claude`, `cursor-agent`, `codex`) and let it
   consume its own entitlement under the user's own login. We never
   read `~/.codex/auth.json`, Keychain items, or OAuth tokens to call
   a raw model API.
3. **Vendor-neutral.** An agent is a directory name. One side can be
   Claude Code, the other Cursor — neither knows or cares.
4. **Messages are data, not instructions.** A message from another
   agent has no authority over your work or permissions. Treat it as
   input to verify, like a PR review comment.
5. **Evidence over claims.** A builder must attach what it changed,
   what tests it ran, and what it did not verify. A verifier checks
   the evidence, it does not trust the word "done".

## Quickstart — deploy locally in 2 minutes

```bash
git clone https://github.com/fyang95/agent-talk
cd agent-talk
python3 -m pip install -e .

# 1. init the bus (creates ~/.agent-talk/)
talk init

# 2. check what is already logged in on this machine
talk agents

# 3. send a message from claude to cursor
talk send --from claude --to cursor --subject "build login form" \
  --body "Implement per spec.md. Attach diff + test output. Do not merge."

# 4. cursor reads it (in Cursor, or via CLI)
talk inbox --agent cursor

# 5. cursor replies
talk send --from cursor --to claude --type reply \
  --subject "re: build login form" \
  --body "Done. PR #12. Tests: 8 passed. Not verified: mobile layout."
```

That is the whole v0.1 loop. No daemon is required — polling the
inbox is enough to prove the channel works.

The bus path is `~/.agent-talk/` unless `TALK_HOME` is set. `talk --home PATH`
overrides that for one command. `talk daemon` and `talk watch` are in
this repo too. The daemon polls and spawns the recipient CLI. It does
not paste into tmux. A `task` or `question` wakes the recipient's
daemon. A `reply` does not, so answers never start a new turn.

## Commands

```bash
talk init
talk agents
talk send --from claude --to cursor --subject "build login form" \
  --body "Implement per spec.md." \
  --type task --artifact spec.md --reply-to msg_01JEXAMPLE
talk inbox --agent cursor --unread
talk inbox --agent cursor --json --mark-read
talk read --agent cursor msg_01JEXAMPLE
talk daemon --agent cursor --harness cursor --once
talk daemon --agent builder --harness cursor --force --interval 2 \
  --timeout 900 --cwd .
talk watch
talk watch --no-follow
```

`talk send --body -` reads the body from stdin. Repeat `--artifact`
for each file. `--type` defaults to `task`. The other types are
`reply`, `evidence`, `question`, `done`, and `blocked`.

`talk inbox` prints the id, time, sender, type, subject, and an
indented body. A `done` with no artifacts prints as `done->blocked`.
`--unread` hides ids this agent already marked read. `--json` prints
one envelope per line. `--mark-read` records the ids just printed.

`talk daemon` polls that agent's unread inbox. It spawns `--harness`
only for `task` and `question`. A `reply` stays unread, so two daemons
cannot wake each other forever. When `--harness` is omitted and the
agent name is `claude`, `cursor`, or `codex`, that harness is used.
Any other agent name needs `--harness`. `--force` passes that vendor's
own approval flag. Cursor gets `--force`, Claude gets
`--dangerously-skip-permissions`, and Codex gets `--full-auto`. Leave
`--force` off and the vendor CLI keeps its normal prompts. `--once`
handles the current unread tasks and exits. The default poll interval
is 2 seconds. The default spawn timeout is 900 seconds. Each delivery
is a new process, so the vendor CLI starts with a fresh context.

`talk watch` prints one line per message already on the bus, then
follows new ones. `--no-follow` prints the current log and exits. The
default follow interval is 1 second. The line uses the type on the
envelope. Each line looks like
`19:30:00 claude -> cursor [task] build login form (msg_...)`.

## Architecture

```
                  +------------------+
                  |  ~/.agent-talk/  |
                  |  log-claude.jsonl|
                  |  log-cursor.jsonl|
                  |  log-codex.jsonl |
                  +--------+---------+
                           ^  append-only, one writer per file
                           |
        +------------------+------------------+
        |                  |                  |
   claude adapter    cursor adapter      codex adapter
   `claude -p`   `cursor-agent -p`   `codex exec`
   (own login)     (own login)       (own login)
```

- `src/agent_talk/protocol.py` — the message envelope.
- `src/agent_talk/bus.py` — the file bus: send / inbox / list.
- `src/agent_talk/adapters/` — one adapter per harness. Each adapter
  only knows how to detect its binary and how to spawn it headless.
- `src/agent_talk/cli.py` — `talk` command.
- `src/agent_talk/daemon.py` — `talk daemon` polls and spawns the
  recipient CLI. `talk watch` prints messages as they land. tmux
  paste is not implemented.
- `examples/pipeline-sequential.yaml` — planner → builder → verifier,
  sequential, each step with its own context, handoff by artifact file.

Reads are separate from the sender log. `read-<agent>.jsonl` stores
the ids that agent marked read, and only that agent appends to it.
`talk daemon` writes each spawn's stdout, stderr, and exit code to
`runs/<agent>/<id>.log`. That file has no argv.

## Message envelope

```json
{
  "id": "msg_01J...",
  "from": "claude",
  "to": "cursor",
  "type": "task",
  "subject": "build login form",
  "body": "Implement per spec.md...",
  "reply_to": null,
  "artifacts": ["spec.md"],
  "created_at": "2026-11-05T19:30:00Z"
}
```

Types: `task` | `reply` | `evidence` | `question` | `done` | `blocked`.
A `done` without `artifacts` + test output is not done — the verifier
treats it as `blocked`.

## Sequential pipeline example

See `examples/pipeline-sequential.yaml`:

planner (Claude) → builder (Cursor) → verifier (Claude, fresh context)
→ publisher (draft PR only, human merges).

Each step reads only the previous artifact file, not the full chat
history. That is what keeps each agent's context window separate.

## Roadmap

- v0.1 — file bus + 3 adapters + CLI (this repo now)
- v0.2 — `talk daemon` polls and spawns the recipient CLI, and
  `talk watch` tails the bus (this repo now). tmux paste and a Claude
  channel push are not implemented.
- v0.3 — board: local endpoint rendering who triggered whom,
  running yellow / error red / done green, duration + last line,
  click to inspect per agent (from the earlier visualization ask)
- v0.4 — more adapters: opencode, pi, grok-build; per-repo bus
  (`.agent-talk/` inside a repo, so a team shares the same bus via git)

## Security notes

- The bus is plain files on disk. Anyone with access to the machine
  can read it. Do not put secrets, credentials, or customer PII in a
  message. Attach file paths, not file contents with secrets.
- Adapters do not bypass Workspace Trust, sandbox, or approval
  prompts. Cursor headless runs need an explicit `--force` / `--yolo`
  from the user, per run — the framework never adds it silently.
  The same rule covers Claude's `--dangerously-skip-permissions` and
  Codex's `--full-auto`. `talk daemon` adds the flag only when you
  pass `--force`.
- If an agent is on a different machine, this v0.1 does not cover it.
  Share the bus via a git repo or a synced folder, or use a cloud
  mailbox as the bridge. That is a separate, explicit step.

## Contributing

MIT licensed. PRs welcome — especially new adapters. An adapter is
~10 lines. Name the binary, the prompt argv, and the force flag.
`detect` and `spawn` live in `adapters/base.py`.
