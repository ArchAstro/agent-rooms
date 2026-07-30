import Foundation
import Security

/// Persisted session credentials.
struct StoredSession: Codable {
    enum Kind: String, Codable {
        /// Browser sign-in through archagents.com's cli-auth handoff.
        case archagents
        /// Email/password session (publishable-key based).
        case password
    }

    var kind: Kind
    var baseURL: String
    var accessToken: String
    var refreshToken: String?
    /// Publishable key (password sessions).
    var apiKey: String?
    /// Signed-in user's email, when known (display only).
    var email: String?
    /// Signed-in org name, when known (display only).
    var orgName: String?
    /// App and user identifiers from the ArchAgents browser handoff. They
    /// let the native app use the same user-authored message route as the
    /// Team Room kit. Optional for sessions saved by older app versions.
    var appId: String?
    var userId: String?
}

/// Keychain-backed storage for the signed-in session, scoped to this app.
struct SessionStore {
    private let service = "ai.archastro.Rooms"
    private let account = "session"

    func load() -> StoredSession? {
        var query = baseQuery()
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var item: CFTypeRef?
        guard
            SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
            let data = item as? Data
        else { return nil }
        return try? JSONDecoder().decode(StoredSession.self, from: data)
    }

    func save(_ session: StoredSession) {
        guard let data = try? JSONEncoder().encode(session) else { return }
        var query = baseQuery()
        let attributes: [String: Any] = [kSecValueData as String: data]

        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            query[kSecValueData as String] = data
            SecItemAdd(query as CFDictionary, nil)
        }
    }

    func clear() {
        SecItemDelete(baseQuery() as CFDictionary)
    }

    private func baseQuery() -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }
}
