# Default Machine Install Design

## Decision

Running the installer without arguments installs Agent Rooms for the current machine:

```bash
npx github:ArchAstro/agent-rooms
```

`--machine` remains an exact compatibility alias. `--repo [path]` remains the explicit vendoring path and is the only mode allowed to write into a Git repository.

## Machine behavior

The machine installer copies the kit under `~/.archastro/agent-rooms`, installs `room-post` under `~/.local/bin`, and adds the managed Agent Rooms contract to detected harness identities. That contract applies in every repository used by the installed harness. There is no repository registry, subscription file, or enable command.

The first `room-post login` stores the person's authenticated Room identity under `~/.config/team-room`. Room failures remain non-blocking and do not turn into engineering work.

## Repository behavior

The default install never writes to the current repository. A user must explicitly pass `--repo` to vendor the kit and managed instruction blocks into a repository. Existing `--repo` safeguards remain unchanged.

## Compatibility

- Existing `--machine` commands continue to work.
- Existing explicit `--repo` commands continue to work.
- Existing machine installs upgrade in place.
- No new local configuration format is introduced.

## Verification

The installer battery runs the no-argument command from inside a real temporary Git repository, verifies that machine files and global harness instructions are installed, verifies that no repository file or Git status changes, and checks that the generated contract says Agent Rooms applies across repositories. The same battery compares no-argument and `--machine` installation manifests and retains the explicit `--repo` coverage.
