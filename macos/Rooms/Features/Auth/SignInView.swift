import SwiftUI

/// Credential sign-in sheet. Uses the publishable key and base URL from
/// Settings.
struct SignInView: View {
    @Environment(AppState.self) private var appState
    @Environment(\.dismiss) private var dismiss

    @State private var email = ""
    @State private var password = ""

    private var isSigningIn: Bool {
        if case .signingIn = appState.phase { return true }
        return false
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Sign In")
                .font(.title2.weight(.semibold))

            Form {
                TextField("Email", text: $email)
                    .textContentType(.username)
                SecureField("Password", text: $password)
                    .textContentType(.password)
            }
            .formStyle(.columns)

            if let error = appState.signInError {
                Text(error)
                    .font(.callout)
                    .foregroundStyle(.red)
            }

            HStack {
                Spacer()
                Button("Cancel", role: .cancel) { dismiss() }
                    .keyboardShortcut(.cancelAction)
                Button("Sign In") {
                    Task {
                        await appState.signIn(email: email, password: password)
                        if appState.isSignedIn { dismiss() }
                    }
                }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
                .disabled(email.isEmpty || password.isEmpty || isSigningIn)
            }
        }
        .padding(24)
        .frame(width: 360)
        .overlay {
            if isSigningIn {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(.regularMaterial)
            }
        }
    }
}
