import SwiftUI

/// Root view: split-view shell when signed in, welcome screen otherwise.
struct ContentView: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        @Bindable var appState = appState
        Group {
            switch appState.phase {
            case .restoring:
                ProgressView()
                    .controlSize(.large)
            case .signedOut, .signingIn:
                WelcomeView()
            case .signedIn:
                NavigationSplitView {
                    SidebarView(
                        rooms: appState.rooms,
                        selection: $appState.selectedRoomID
                    )
                } detail: {
                    if let roomID = appState.selectedRoomID,
                       let room = appState.rooms.first(where: { $0.id == roomID }) {
                        RoomView(room: room)
                    } else {
                        NoRoomSelectedView()
                    }
                }
            }
        }
        .frame(minWidth: 720, minHeight: 460)
    }
}

/// Signed-out landing state. Primary sign-in goes through the browser
/// (federated SSO, like archagents.com); email/password is a fallback.
struct WelcomeView: View {
    @Environment(AppState.self) private var appState
    @State private var showingCredentialSignIn = false

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: "bubble.left.and.bubble.right.fill")
                .font(.system(size: 44))
                .foregroundStyle(.tint)
            Text("Rooms")
                .font(.largeTitle.weight(.semibold))
            Text("Realtime rooms for the ArchAstro platform.")
                .foregroundStyle(.secondary)

            if appState.browserSignInPending {
                VStack(spacing: 10) {
                    ProgressView()
                    Text("Finish signing in with your browser…")
                        .foregroundStyle(.secondary)
                    Button("Cancel") {
                        appState.cancelSignIn()
                    }
                }
                .padding(.top, 12)
            } else {
                VStack(spacing: 8) {
                    Button {
                        Task { await appState.signInWithBrowser() }
                    } label: {
                        Text("Sign In with ArchAgents")
                            .frame(width: 220)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)

                    Button("Use email & password…") {
                        showingCredentialSignIn = true
                    }
                    .buttonStyle(.link)
                    .controlSize(.small)
                    .padding(.top, 2)
                }
                .padding(.top, 12)
            }

            if let error = appState.signInError {
                Text(error)
                    .font(.callout)
                    .foregroundStyle(.red)
                    .padding(.top, 4)
            }
        }
        .padding(40)
        .sheet(isPresented: $showingCredentialSignIn) {
            SignInView()
        }
    }
}

struct NoRoomSelectedView: View {
    var body: some View {
        ContentUnavailableView(
            "No Room Selected",
            systemImage: "bubble.left.and.bubble.right",
            description: Text("Choose a room from the sidebar.")
        )
    }
}

#Preview {
    ContentView()
        .environment(AppState())
}
