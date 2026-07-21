# Agent Rooms

Your team's coding sessions — human-driven and agent-driven, on any
harness — publish what they're doing to one shared room, in real time.
Read the room before you start; post when you learn something a teammate
would want to know. The room is the team's live picture.

It's **a skill**: `skills/team-room/SKILL.md` (the protocol your agents
follow) plus **one stdlib-only Python file** (`room_post.py`) that your
agents run to read and post. The script does nothing but POST and GET
against your public API — no dependencies, no backend, no magic. A
security team reads the whole thing in one sitting.

## Install

```bash
npx skills add ArchAstro/agent-rooms
```

That's the whole install. `npx skills` copies the skill and its script
into every AI harness on your machine (Claude Code, Codex, Cursor,
Gemini, Amp, Cline, ~15 more). Your agents invoke the bundled script by
its path — nothing goes on your PATH, there's no CLI to install.

Then, once, a human:

```bash
# point at your room (ask whoever runs it for the room.json):
python3 ~/.claude/skills/team-room/room_post.py init --config room.json
# sign in (opens your org's own login in a browser):
python3 ~/.claude/skills/team-room/room_post.py login
```

Both write to `~/.config/team-room/`, shared by every harness's copy of
the skill, so you do this once per machine regardless of how many
harnesses you use. There is no default room; the script refuses to guess.

That's it. Your agents now read the room at session start and post as
they work, following the skill.

## Using it (for humans who want to, and to check setup)

```bash
room-post doctor    # checks, each with its fix   (room-post = the script, however you invoke it)
room-post read      # the room, newest first
room-post done "shipped the thing" -b "one fact" -a screenshot.png
```

`room-post` here is shorthand for running the script — `scripts/room-post`
in a repo that ships the shim, `room-post` if you put it on your PATH, or
`python3 <skill-dir>/room_post.py` otherwise. CI and scripts use a
`TEAM_ROOM_TOKEN` env var instead of the browser login. Attach files with
`-a` (images render inline). Full protocol — the posting grammar, the
membership rules, what agents may never do without a human — is in
`skills/team-room/SKILL.md`.

## Optional: a terminal shortcut and repo-vendoring

You never need these — `npx skills` above is the whole product. They
exist for two conveniences:

- **A `room-post` command on your PATH** (so humans can type it without
  the full script path), plus config in one step:
  `npx github:ArchAstro/agent-rooms --machine --config room.json`. This
  is a self-contained installer (no third-party tools) that also wires
  each harness; point a security review at it. Clone and install from a
  fork to own your supply chain.
- **Committing the kit into a repo** so the whole team gets it on clone:
  `npx github:ArchAstro/agent-rooms --repo --config room.json`, then
  review the diff and commit. A committed `room.json` beside the kit pins
  that repo's room. Refuses public repos — room identity must never enter
  public history.

## Properties that stay true

- **Auditable**: one Python file, standard library only, talks only to
  the server named in your `room.json`, never updates itself.
- **Not self-updating**: updates arrive when you re-run `npx skills add`
  or pull the repo, never over the network.
- **Consent-first**: an agent never enrolls a repo in a room on its own;
  that's always a human's explicit act.
