import SwiftUI

/// Signed-out state inside the tray: browser sign-in through ArchAgents,
/// with the email/password fallback tucked behind a sheet.
struct WelcomeTrayView: View {
    @Environment(AppState.self) private var appState
    @State private var showingCredentialSignIn = false

    var body: some View {
        VStack(spacing: 12) {
            Spacer()

            Image(systemName: "bubble.left.and.bubble.right.fill")
                .font(.system(size: 38))
                .foregroundStyle(Theme.purple)
            Text("Rooms")
                .font(.system(size: 26, weight: .bold))
                .kerning(-0.8)
                .foregroundStyle(Theme.ink)
            Text("Your team's work, still in sight.")
                .font(.system(size: 12))
                .foregroundStyle(Theme.muted)

            if appState.browserSignInPending {
                VStack(spacing: 10) {
                    ProgressView()
                        .controlSize(.small)
                    Text("Finish signing in with your browser…")
                        .font(.system(size: 11))
                        .foregroundStyle(Theme.muted)
                    Button("Cancel") {
                        appState.cancelSignIn()
                    }
                    .buttonStyle(.plain)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(Theme.muted)
                }
                .padding(.top, 14)
            } else {
                VStack(spacing: 8) {
                    Button {
                        Task { await appState.signInWithBrowser() }
                    } label: {
                        Text("Sign In with ArchAgents")
                            .font(.system(size: 12, weight: .bold))
                            .foregroundStyle(.white)
                            .frame(width: 210)
                            .padding(.vertical, 8)
                            .background(Theme.ink, in: RoundedRectangle(cornerRadius: 9))
                    }
                    .buttonStyle(.plain)

                    Button("Use email & password…") {
                        showingCredentialSignIn = true
                    }
                    .buttonStyle(.plain)
                    .font(.system(size: 10))
                    .foregroundStyle(Theme.muted)
                }
                .padding(.top, 14)
            }

            if let error = appState.signInError {
                Text(error)
                    .font(.system(size: 10))
                    .foregroundStyle(Theme.red)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 30)
                    .padding(.top, 4)
            }

            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .sheet(isPresented: $showingCredentialSignIn) {
            SignInView()
        }
    }
}
