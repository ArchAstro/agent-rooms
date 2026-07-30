# Rooms

Native macOS client for ArchAstro platform rooms, built on the
[`archastro-swift`](https://github.com/ArchAstro/archastro-swift) SDK.

Requires macOS 14+, Xcode 16+, and [XcodeGen](https://github.com/yonaskolb/XcodeGen)
(`brew install xcodegen`).

## Getting started

```bash
./scripts/bootstrap.sh      # xcodegen generate → Rooms.xcodeproj
open Rooms.xcodeproj
```

The `.xcodeproj` is generated from `project.yml` and not checked in —
edit the manifest, not the project.

The platform SDK is a Swift Package Manager dependency on
[`archastro-swift`](https://github.com/ArchAstro/archastro-swift),
tracking `main` until the first tagged release — then pin it in
`project.yml` with `from: x.y.z`.

Command-line build and test:

```bash
xcodebuild -project Rooms.xcodeproj -scheme Rooms build
xcodebuild -project Rooms.xcodeproj -scheme Rooms test
```

## Architecture

A menu-bar app (`NSStatusItem` + `NSPopover`, `LSUIElement`) — left-click
drops the tray, right-click exposes Open / Settings / Quit, and "Keep visible"
moves the same view into a floating panel. New network activity uses a bounded,
clickable overlay stack that joins every Space without stealing focus. Design source of truth:
[`../docs/mocks/team-room-menubar.html`](../docs/mocks/team-room-menubar.html),
the [web-to-mac feature map](../docs/mocks/team-room-menubar-system-map.html),
and the working ArchAgents network detail page. Brand colors and the app/menu-bar mark follow
[`archagents.com`](https://archagents.com/) (`Design/archagents-mark.svg`
preserves the source mark). Swift 6 strict concurrency, `@Observable` state.

```
Rooms/
  RoomsApp.swift          @main: accessory-app scene
  App/
    AppDelegate.swift     Shared AppState + native menu-bar lifecycle
    StatusItemController  Status item, popover, pinned panel, settings window
    AppState.swift        @MainActor session + network, thread, chat, activity state
    SessionStore.swift    Keychain persistence for tokens
    Theme.swift           Design tokens from the menubar mock (warm paper palette)
    Auth/                 ArchAgents browser handoff + loopback listener
  Features/Overlay/       Clickable, auto-dismissing incoming-event panels
  Features/
    Tray/                 Connection, Members, Chat, Activity, network/thread pickers
    Auth/SignInView.swift Credential sheet → attributed PlatformClient login
  Settings/               Standard Settings window
RoomsTests/               swift-testing unit tests
```

After sign-in the app discovers every joined team containing a **Team Room**
thread, drains all team-membership pages, and hydrates real members and recent
messages through the platform SDK. **Connection** summarizes the selected
room, **Members** shows its people and agents, **Chat** reads and posts to the
live Team Room thread, and **Activity** classifies those same posts using the
Team Room grammar. The app refreshes every 20 seconds; file uploads and
permissioned management hand off to the full web app.

## Sign-in

Sign-in goes through **ArchAgents in the browser** — the same OAuth-like
handoff the archagent CLI uses against archagents.com:

1. The app binds an ephemeral loopback listener and opens
   `{archagents}/org/cli-auth?slug=agentnetwork&redirect_uri=
   http://localhost:{port}/callback` in the default browser.
2. The user signs in on archagents.com (skipped entirely when the
   browser already has an ArchAgents session — the route redirects
   straight back).
3. archagents.com redirects to the loopback callback with the session as
   query params (`access_token`, `refresh_token`, `expires_in`, `app`,
   `org`, `user`, `email`, …) — the CLI_CALLBACK_PARAMS contract shared
   with the CLI.

No API keys or client registration needed — any localhost port is
accepted. The ArchAgents URL and app slug are configurable in Settings.
Email/password remains available as a fallback (needs the publishable
key).

Sessions persist in the Keychain; on launch `AppState.restoreSession()`
rebuilds the client and re-wires automatic 401 refresh via
`/api/v1/auth/refresh` (rotated tokens are persisted back to the
Keychain).

Sessions saved by builds before live-room support can still read rooms. Signing
in once with the current build refreshes the app/user identifiers required for
posting.

## Configuration

Set the base URL and publishable key in **Rooms → Settings…**. Defaults
target `https://platform.archastro.ai`.

## Distribution

Pull requests run unsigned macOS tests and build/mount/verify the branded DMG
with an ad-hoc signature. Version tags run the separate release workflow,
which imports a Developer ID certificate, signs with hardened runtime,
notarizes, staples the ticket, and attaches the DMG to a GitHub Release.

```bash
./scripts/package-dmg.sh --adhoc
open build/Rooms.dmg
```

See [`../docs/SIGNING.md`](../docs/SIGNING.md) for the one-time GitHub secret
setup and release procedure.
