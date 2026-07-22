import SwiftUI

/// Standard macOS Settings window.
struct SettingsView: View {
    var body: some View {
        TabView {
            GeneralSettingsView()
                .tabItem {
                    Label("General", systemImage: "gearshape")
                }
        }
        .frame(width: 420)
    }
}

struct GeneralSettingsView: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        @Bindable var appState = appState
        Form {
            TextField("API Base URL", text: $appState.baseURL)
                .textContentType(.URL)
            TextField("ArchAgents URL", text: $appState.archagentsURL)
                .textContentType(.URL)
                .help("The ArchAgents web app that hosts browser sign-in.")
            TextField("App Slug", text: $appState.appSlug)
                .help("App slug for the sign-in handoff (default: agentnetwork).")
            TextField("Publishable Key", text: $appState.publishableKey)
                .help("Only needed for the email/password fallback.")

            if appState.isSignedIn {
                LabeledContent("Session") {
                    HStack {
                        if let email = appState.userEmail {
                            Text(appState.orgName.map { "\(email) · \($0)" } ?? email)
                                .foregroundStyle(.secondary)
                        }
                        Button("Sign Out") {
                            Task { await appState.signOut() }
                        }
                    }
                }
            }
        }
        .padding(20)
    }
}
