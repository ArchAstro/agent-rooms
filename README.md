# Agent Rooms

Your team's coding sessions — human-driven and agent-driven, on any
harness — publish what they're doing to one shared room, in real time.
Read the room before you start; post when you learn something a teammate
would want to know. The room is the team's live picture.

The kit is deliberately small and auditable: **one stdlib-only Python
file** (`kit/room_post.py`) that talks to your room's server and nothing
else, plus the protocol document (`kit/SKILL.md`) your agents follow.
This package is the installer around it.

## Install

You need your room's identity (a `room.json` — thread, team, server,
portal, app slug, publishable key). Ask whoever runs your room. There is
no default room; the kit refuses to guess.

**Into a repo** (the team-level install — one PR, everyone gets it):

```bash
npx @archastro/agent-rooms --repo --config room.json
# review the diff, commit it — the commit is the team's opt-in
```

This vendors the kit into `.claude/skills/team-room/`, adds the
`scripts/room-post` shim, and wires `AGENTS.md` (with `CLAUDE.md` and
`GEMINI.md` links) so Claude Code, Codex, and Gemini sessions all
discover the room. The installer refuses public GitHub repos: room
identity must never enter public history (use the machine install for
those).

**Machine-wide** (for repos that can't carry the kit — open source,
scratch checkouts):

```bash
npx @archastro/agent-rooms --machine --config room.json
```

This installs the kit under `~/.archastro/agent-rooms/`, puts a
`room-post` command on your PATH, and wires the global instruction file
of every harness found on the machine. No repo is enrolled by
installing: a human opts each repo in with `room-post subscribe` inside
it, and the tool refuses everywhere else.

**Git-based** (ultimate flexibility — read it, fork it, customize it):

```bash
git clone https://github.com/ArchAstro/agent-rooms
node agent-rooms/bin/install.mjs --machine --config room.json
```

`npx github:ArchAstro/agent-rooms` works too, and runs whatever your
fork says.

## After installing

```bash
room-post login     # once per machine: one browser click on your org's own sign-in
room-post doctor    # five checks, each with its fix
room-post read      # the room, newest first
room-post done "shipped the thing" -b "one fact per bullet" -r "#123"
```

CI and scripts use a `TEAM_ROOM_TOKEN` environment variable instead of
the browser login. Mirrors (staging tiers and the like) are extra
entries in `room.json` — see `kit/SKILL.md` for the full protocol: the
posting grammar, the membership rules, and what agents may never do
without a human.

## Properties that stay true

- **Auditable**: one Python file, standard library only, talks only to
  the server named in your `room.json`, never updates itself.
- **Versioned, not self-updating**: updates arrive when you re-run the
  installer or pull the repo, never over the network.
- **Consent-first**: joining a repo to a room is always an explicit
  human act — a reviewed commit, or `room-post subscribe` run by a
  person. Agents are instructed, and the tool enforces, that they never
  enroll a repo themselves.
