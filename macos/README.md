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

The platform SDK is **vendored** at `Vendor/archastro-swift/` (library
sources + trimmed manifest, provenance in `VENDORED.md`) until
`archastro-swift` is published — refresh it from a local checkout with:

```bash
./scripts/vendor_sdk.sh [path-to-archastro-swift]   # default ../archastro-swift
```

Once the SDK ships as a tagged release, switch the package reference in
`project.yml` to a versioned git dependency and delete `Vendor/`.

Command-line build and test:

```bash
xcodebuild -project Rooms.xcodeproj -scheme Rooms build
xcodebuild -project Rooms.xcodeproj -scheme Rooms test
```

## Architecture

SwiftUI App lifecycle, Swift 6 strict concurrency, `@Observable` state.

```
Rooms/
  RoomsApp.swift          @main scene graph: WindowGroup, Settings, menu commands
  App/
    AppState.swift        @MainActor session/app state (restore → signIn → signedIn)
    SessionStore.swift    Keychain persistence for tokens
  Features/
    Rooms/                NavigationSplitView shell: sidebar list + room detail
    Auth/SignInView.swift Credential sheet → PlatformClient.withCredentials
  Settings/               Standard Settings window (base URL, publishable key)
RoomsTests/               swift-testing unit tests
```

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

The sidebar rooms are placeholders — next step is backing them with
`client.threads` and wiring `ApiChatChannel` over `client.openSocket()`
for realtime messages.

## Configuration

Set the base URL and publishable key in **Rooms → Settings…**. Defaults
target `https://platform.archastro.ai`.
