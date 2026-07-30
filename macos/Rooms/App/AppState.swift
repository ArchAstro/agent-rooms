import AppKit
import Foundation
import Observation
import SwiftUI
import ArchAstroPlatform

/// Top-level observable state for the app: session lifecycle and the
/// signed-in platform client. Views read this through the environment.
@MainActor
@Observable
final class AppState {
    /// UI shell hooks kept as closures so the product state remains testable
    /// without owning AppKit windows.
    var onNewEvent: ((StreamEvent) -> Void)?
    var onMention: ((MessageMention) -> Void)?

    enum SessionPhase {
        case restoring
        case signedOut
        case signingIn
        case signedIn(PlatformClient)
    }

    var phase: SessionPhase = .restoring
    var signInError: String?
    /// True while a browser sign-in is waiting on the loopback redirect.
    var browserSignInPending = false
    /// Signed-in user's email, when known.
    var userEmail: String?
    /// Signed-in user's display name, loaded from `/users/me`.
    var userName: String?
    /// Signed-in user's @ handle, loaded from `/users/me`.
    var userAlias: String?
    /// Signed-in org name, when known.
    var orgName: String?
    var roomLoadError: String?
    var isLoadingRooms = false
    var hasLoadedRooms = false
    var isSendingMessage = false
    var messageHistoryByThread: [String: ThreadMessageHistory] = [:]
    private(set) var loadingOlderThreadIDs: Set<String> = []
    private var threadsWithLoadedOlderHistory: Set<String> = []
    private var hasLoadedCurrentUserProfile = false

    var accountDisplayName: String {
        let name = userName?.trimmingCharacters(in: .whitespacesAndNewlines)
        if let name, !name.isEmpty { return name }
        let email = userEmail?.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let email, !email.isEmpty else { return "Signed-in account" }
        return email
    }

    var accountEmail: String? {
        let email = userEmail?.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let email, !email.isEmpty, email != accountDisplayName else { return nil }
        return email
    }

    var accountOrganization: String? {
        let organization = orgName?.trimmingCharacters(in: .whitespacesAndNewlines)
        return organization?.isEmpty == false ? organization : nil
    }

    // MARK: Network tray state

    var selectedTab: TrayTab = .chat {
        didSet {
            if oldValue == .activity && selectedTab != .activity {
                newEventIDs.subtract(visibleCurrentEventIDs)
            }
        }
    }
    var availableNetworks = TrayPlaceholders.networks
    var selectedNetwork = TrayPlaceholders.networks[0]
    var members = TrayPlaceholders.members
    var threads = TrayPlaceholders.threads
    var selectedThread = TrayPlaceholders.threads[0]
    var messages = TrayPlaceholders.messages
    var tasks = TrayPlaceholders.tasks
    var workstream = TrayPlaceholders.workstream
    var events = TrayPlaceholders.events
    var activityFilter: StreamEvent.Level = .all {
        willSet {
            if selectedTab == .activity && !suppressActivityReadTracking {
                newEventIDs.subtract(visibleCurrentEventIDs)
            }
        }
    }
    var activityPaused = false
    var typingByThread = ["thread_general": "Fleet"]
    var newEventIDs: Set<String> = []
    var messageFocus: MessageFocus?

    var currentMembers: [NetworkMember] {
        members.filter { $0.networkID == selectedNetwork.id }
    }
    var currentThreads: [NetworkThread] {
        threads.filter { $0.networkID == selectedNetwork.id }
    }
    var currentMessages: [ChatMessage] {
        messages.filter { $0.threadID == selectedThread.id }
    }
    var canLoadOlderMessages: Bool {
        guard !selectedThread.id.isEmpty else { return false }
        return messageHistoryByThread[selectedThread.id]?.beforeCursor != nil
    }
    var isLoadingOlderMessages: Bool {
        loadingOlderThreadIDs.contains(selectedThread.id)
    }
    var currentTasks: [ThreadTask] {
        tasks.filter { $0.threadID == selectedThread.id }
    }
    var currentWorkstream: [WorkstreamItem] {
        workstream.filter { $0.networkID == selectedNetwork.id }
    }
    var currentEvents: [StreamEvent] {
        events.filter { $0.networkID == selectedNetwork.id }
    }
    var visibleCurrentEventIDs: [String] {
        currentEvents.filter { $0.matches(activityFilter) }.map(\.id)
    }
    var totalUnreadCount: Int {
        threads.reduce(0) { $0 + $1.unreadCount }
    }

    var toast: String?
    private var toastTask: Task<Void, Never>?
    private var liveFeedTask: Task<Void, Never>?
    private var channelSession: RoomChannelSession?
    private var channelConnectTask: Task<RoomChannelSession, any Error>?
    private var pendingLiveEvents = TrayPlaceholders.liveFeed
    private var suppressActivityReadTracking = false
    private var notifiedMentionMessageIDs: Set<String> = []
    private var pendingMentionTarget: MentionNavigationTarget?

    func showToast(_ message: String) {
        toastTask?.cancel()
        toast = message
        toastTask = Task {
            try? await Task.sleep(nanoseconds: 1_900_000_000)
            guard !Task.isCancelled else { return }
            toast = nil
        }
    }

    func selectNetwork(_ network: NetworkSnapshot, markVisibleContentRead: Bool = true) {
        if markVisibleContentRead && selectedTab == .activity {
            newEventIDs.subtract(visibleCurrentEventIDs)
        }
        let networkChanged = selectedNetwork.id != network.id
        selectedNetwork = network
        if networkChanged { messageFocus = nil }
        if networkChanged,
           let defaultThread = currentThreads.first(where: \.isDefault) ?? currentThreads.first {
            selectedThread = defaultThread
        } else if networkChanged {
            selectedThread = NetworkThread(
                id: "",
                networkID: network.id,
                title: "No threads",
                isDefault: false,
                unreadCount: 0
            )
        }
        if markVisibleContentRead && selectedTab == .chat { markSelectedThreadRead() }
        showToast("Switched to \(network.name)")
    }

    func selectThread(_ thread: NetworkThread) {
        messageFocus = nil
        selectedThread = thread
        markSelectedThreadRead()
        showToast("Opened \(thread.title)")
    }

    func unreadCount(for networkID: String) -> Int {
        threads.filter { $0.networkID == networkID }.reduce(0) { $0 + $1.unreadCount }
    }

    func markSelectedThreadRead() {
        guard let index = threads.firstIndex(where: { $0.id == selectedThread.id }) else { return }
        threads[index].unreadCount = 0
        guard let latestMessageID = currentMessages.first?.id,
              let client
        else { return }
        let threadID = selectedThread.id
        Task { [weak self] in
            guard let self else { return }
            let session = try? await requireRoomChannelSession(client: client)
            try? await session?.markRead(
                threadID: threadID,
                messageID: latestMessageID
            )
        }
    }

    func prepareActivityOverlay(_ event: StreamEvent) {
        if let network = availableNetworks.first(where: { $0.id == event.networkID }) {
            selectNetwork(network, markVisibleContentRead: false)
        }
        suppressActivityReadTracking = true
        activityFilter = .all
        suppressActivityReadTracking = false
        selectedTab = .activity
    }

    func openInFullApp(_ what: String, extraQueryItems: [URLQueryItem] = []) {
        guard let url = webAppURL(extraQueryItems: extraQueryItems),
              NSWorkspace.shared.open(url)
        else {
            showToast("Could not open the web app")
            return
        }
        showToast("\(what) opened in the web app")
    }

    func webAppURL(extraQueryItems: [URLQueryItem] = []) -> URL? {
        guard var components = URLComponents(string: archagentsURL) else { return nil }
        let basePath = components.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        components.path = (basePath.isEmpty ? "" : "/\(basePath)") + "/teams/\(selectedNetwork.id)"
        components.queryItems = [
            URLQueryItem(name: "tab", value: selectedTab.rawValue.lowercased()),
            URLQueryItem(name: "thread", value: selectedThread.id),
        ] + extraQueryItems
        return components.url
    }

    @discardableResult
    func sendMessage(_ body: String, attachmentName: String? = nil) async -> Bool {
        guard !selectedThread.id.isEmpty else {
            showToast("No Team Room is selected")
            return false
        }
        guard let client else { return false }
        let trimmed = body.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty || attachmentName != nil else { return false }

        // Uploads are not yet exposed by the Swift SDK. Never pretend a local
        // filename crossed the network.
        guard attachmentName == nil else {
            showToast("Open the web app to attach files")
            return false
        }

        isSendingMessage = true
        defer { isSendingMessage = false }
        do {
            let channel = try await requireRoomChannelSession(client: client)
            try await channel.postMessage(
                threadID: selectedThread.id,
                content: trimmed
            )
            showToast("Posted to Team Room")
            return true
        } catch let error as ApiError {
            showToast(error.message)
            return false
        } catch {
            showToast(error.localizedDescription)
            return false
        }
    }

    func deleteMessage(_ message: ChatMessage) async {
        guard message.isCurrentUser, let client else { return }
        do {
            let channel = try await requireRoomChannelSession(client: client)
            try await channel.deleteMessage(
                threadID: message.threadID,
                messageID: message.id
            )
            messages.removeAll { $0.id == message.id }
            events.removeAll { $0.id == "event-\(message.id)" }
            showToast("Message deleted")
        } catch let error as ApiError {
            showToast(error.message)
        } catch {
            showToast(error.localizedDescription)
        }
    }

    // MARK: Live SDK channels

    func startLiveFeed() {
        guard liveFeedTask == nil else { return }
        liveFeedTask = Task { [weak self] in
            await self?.runRoomChannelLoop()
        }
    }

    func stopLiveFeed() {
        liveFeedTask?.cancel()
        liveFeedTask = nil
        channelConnectTask?.cancel()
        channelConnectTask = nil
        let session = channelSession
        channelSession = nil
        Task {
            await session?.disconnect()
        }
    }

    var isBackgroundRefreshRunning: Bool {
        liveFeedTask != nil
    }

    private func runRoomChannelLoop() async {
        var reconnectDelay = 1
        var hadConnection = false

        while !Task.isCancelled {
            guard isSignedIn, hasLoadedRooms, let client else {
                try? await Task.sleep(for: .milliseconds(250))
                continue
            }

            let desiredThreadIDs = Set(threads.lazy.map(\.id).filter { !$0.isEmpty })
            if desiredThreadIDs.isEmpty {
                try? await Task.sleep(for: .seconds(1))
                continue
            }

            if let channelSession,
               channelSession.isConnected,
               channelSession.threadIDs == desiredThreadIDs
            {
                reconnectDelay = 1
                try? await Task.sleep(for: .seconds(1))
                continue
            }

            let staleSession = channelSession
            channelSession = nil
            await staleSession?.disconnect()
            guard !Task.isCancelled else { return }

            // A bounded SDK history catch-up closes any gap while
            // the socket was unavailable and also triggers token rotation
            // before a reconnect attempts its WebSocket handshake.
            if hadConnection {
                await syncLatestMessagePages(client: client, notify: true)
            }

            do {
                channelSession = try await connectRoomChannels(client: client)
                if let channelSession {
                    installChannelMembers(channelSession.members)
                }
                hadConnection = true
                reconnectDelay = 1

                // Subscribe first, then catch up. Any message created during
                // this request is either in the page or buffered by Channel.
                await syncLatestMessagePages(client: client, notify: true)
            } catch {
                if hadConnection {
                    showToast("Live connection lost — reconnecting")
                }
                try? await Task.sleep(for: .seconds(reconnectDelay))
                reconnectDelay = min(reconnectDelay * 2, 30)
            }
        }
    }

    private func connectRoomChannels(
        client: PlatformClient
    ) async throws -> RoomChannelSession {
        if let channelConnectTask {
            return try await channelConnectTask.value
        }
        let targetThreads = threads
        let organizationName = orgName
        let task = Task<RoomChannelSession, any Error> { [weak self] in
            try await RoomChannelSession.connect(
                client: client,
                threads: targetThreads,
                organizationName: organizationName
            ) { event in
                Task { @MainActor in
                    self?.handleRoomChannelEvent(event)
                }
            }
        }
        channelConnectTask = task
        defer { channelConnectTask = nil }
        return try await task.value
    }

    private func requireRoomChannelSession(
        client: PlatformClient
    ) async throws -> RoomChannelSession {
        if let channelSession, channelSession.isConnected {
            return channelSession
        }
        let session = try await connectRoomChannels(client: client)
        channelSession = session
        installChannelMembers(session.members)
        return session
    }

    private func installChannelMembers(_ channelMembers: [NetworkMember]) {
        members = channelMembers
        for index in availableNetworks.indices {
            let count = channelMembers.count {
                $0.networkID == availableNetworks[index].id
            }
            let role = availableNetworks[index].relationship
                .split(separator: "·", maxSplits: 1)
                .first?
                .trimmingCharacters(in: .whitespacesAndNewlines)
                ?? "Member"
            availableNetworks[index].relationship =
                "\(role) · \(count) \(count == 1 ? "member" : "members")"
        }
        if let refreshed = availableNetworks.first(where: {
            $0.id == selectedNetwork.id
        }) {
            selectedNetwork = refreshed
        }
    }

    private func syncLatestMessagePages(
        client: PlatformClient,
        notify: Bool
    ) async {
        let targetThreads = threads.filter { !$0.id.isEmpty }
        let userID = currentUserID

        let pages = await withTaskGroup(of: LoadedMessagePage?.self) { group in
            for thread in targetThreads {
                group.addTask {
                    try? await TeamRoomAPI.loadMessagePage(
                        client: client,
                        threadID: thread.id,
                        networkID: thread.networkID,
                        currentUserID: userID
                    )
                }
            }
            var loaded: [LoadedMessagePage] = []
            for await page in group {
                if let page { loaded.append(page) }
            }
            return loaded
        }

        let knownMessageIDs = Set(messages.map(\.id))
        for page in pages {
            messages = mergeNewestFirst(page.messages, with: messages)
            events = mergeNewestFirst(page.events, with: events)
            if !threadsWithLoadedOlderHistory.contains(page.threadID) {
                messageHistoryByThread[page.threadID] = ThreadMessageHistory(
                    threadID: page.threadID,
                    beforeCursor: page.beforeCursor
                )
            }
        }

        guard notify else { return }
        for page in pages {
            let eventsByMessageID = Dictionary(
                uniqueKeysWithValues: page.events.map {
                    (String($0.id.dropFirst("event-".count)), $0)
                }
            )
            for message in page.messages.reversed()
            where !knownMessageIDs.contains(message.id) && !message.isCurrentUser
            {
                if let event = eventsByMessageID[message.id] {
                    announceIncomingMessage(message, event: event)
                }
            }
        }
    }

    private func handleRoomChannelEvent(_ event: RoomChannelEvent) {
        switch event {
        case .messageAdded(let networkID, let payload):
            guard let mapped = TeamRoomAPI.mapRealtimeMessage(
                payload,
                networkID: networkID,
                currentUserID: currentUserID
            ) else { return }

            let isNew = !messages.contains { $0.id == mapped.message.id }
            upsertNewestMessage(mapped)
            if isNew && !mapped.message.isCurrentUser {
                announceIncomingMessage(mapped.message, event: mapped.event)
            }

        case .messageUpdated(let networkID, let payload):
            guard let mapped = TeamRoomAPI.mapRealtimeMessage(
                payload,
                networkID: networkID,
                currentUserID: currentUserID
            ) else { return }
            let prior = messages.first { $0.id == mapped.message.id }
            let wasMention = prior.map(messageMentionsCurrentUser) ?? false
            upsertNewestMessage(mapped)
            if !mapped.message.isCurrentUser {
                if prior == nil {
                    announceIncomingMessage(mapped.message, event: mapped.event)
                } else if !wasMention && messageMentionsCurrentUser(mapped.message) {
                    announceMentionIfNeeded(mapped.message, networkID: networkID)
                }
            }

        case .threadEvent(_, let payload):
            guard let threadID = payload.threadId,
                  let index = threads.firstIndex(where: { $0.id == threadID })
            else { return }
            switch payload.type {
            case "unread_count_updated":
                if let count = payload.payload?["unread_count"]?.intValue {
                    threads[index].unreadCount = count
                }
            case "thread_marked_read":
                threads[index].unreadCount = 0
            default:
                break
            }

        case .typing(let payload):
            guard let threadID = payload.threadId else { return }
            if payload.isTyping == true {
                typingByThread[threadID] = payload.actor?.name
                    ?? payload.actor?.alias
                    ?? "Someone"
            } else {
                typingByThread.removeValue(forKey: threadID)
            }
        }
    }

    private func upsertNewestMessage(_ mapped: LoadedRealtimeMessage) {
        if let messageIndex = messages.firstIndex(where: {
            $0.id == mapped.message.id
        }) {
            messages[messageIndex] = mapped.message
        } else {
            messages.insert(mapped.message, at: 0)
        }
        if let eventIndex = events.firstIndex(where: {
            $0.id == mapped.event.id
        }) {
            events[eventIndex] = mapped.event
        } else {
            events.insert(mapped.event, at: 0)
        }
    }

    private func announceLiveEvent(_ event: StreamEvent) {
        if selectedTab != .activity
            || event.networkID != selectedNetwork.id
            || !event.matches(activityFilter)
        {
            newEventIDs.insert(event.id)
        }
        onNewEvent?(event)
    }

    func announceIncomingMessage(_ message: ChatMessage, event: StreamEvent) {
        announceLiveEvent(event)
        announceMentionIfNeeded(message, networkID: event.networkID)
    }

    private func announceMentionIfNeeded(
        _ message: ChatMessage,
        networkID: String
    ) {
        guard !message.isCurrentUser,
              messageMentionsCurrentUser(message),
              notifiedMentionMessageIDs.insert(message.id).inserted
        else { return }

        let roomName = availableNetworks.first { $0.id == networkID }?.name
            ?? "Team Room"
        let threadName = threads.first { $0.id == message.threadID }?.title
            ?? "Team Room"
        let plainBody = MessageText.plainText(message.displayBody)
            .split(whereSeparator: \.isWhitespace)
            .joined(separator: " ")
        let excerpt = plainBody.count > 240
            ? "\(plainBody.prefix(239))…"
            : plainBody
        onMention?(
            MessageMention(
                target: MentionNavigationTarget(
                    networkID: networkID,
                    threadID: message.threadID,
                    messageID: message.id
                ),
                roomName: roomName,
                threadName: threadName,
                author: message.displayAuthor,
                body: excerpt
            )
        )
    }

    private func messageMentionsCurrentUser(_ message: ChatMessage) -> Bool {
        MentionMatcher.matches(
            message.displayBody,
            identity: MentionIdentity(
                fullName: userName,
                alias: userAlias,
                email: userEmail
            )
        )
    }

    /// Internal for placeholder/demo tests; production updates use SDK channels.
    func deliverNextLiveEvent() {
        guard !pendingLiveEvents.isEmpty else { return }
        var event = pendingLiveEvents.removeFirst()
        event = StreamEvent(
            id: "\(event.id)-\(UUID().uuidString.prefix(4))",
            networkID: event.networkID,
            level: event.level,
            author: event.author,
            body: event.body,
            time: "now",
            sessionID: event.sessionID
        )
        pendingLiveEvents.append(event)
        withAnimation(.easeOut(duration: 0.3)) {
            events.insert(event, at: 0)
            if selectedTab != .activity
                || event.networkID != selectedNetwork.id
                || !event.matches(activityFilter)
            {
                newEventIDs.insert(event.id)
            }
        }
        onNewEvent?(event)
    }

    private let sessionStore = SessionStore()
    private var activeAuthServer: LoopbackCallbackServer?
    private var activeAppID: String?
    private var currentUserID: String?

    var isSignedIn: Bool {
        if case .signedIn = phase { return true }
        return false
    }

    var client: PlatformClient? {
        if case .signedIn(let client) = phase { return client }
        return nil
    }

    // MARK: Configuration (Settings window)

    var baseURL: String {
        get { UserDefaults.standard.string(forKey: "baseURL") ?? "https://platform.archastro.ai" }
        set { UserDefaults.standard.set(newValue, forKey: "baseURL") }
    }

    /// ArchAgents web app that hosts the browser sign-in handoff.
    var archagentsURL: String {
        get { UserDefaults.standard.string(forKey: "archagentsURL") ?? ArchAgentsAuth.defaultArchAgentsURL }
        set { UserDefaults.standard.set(newValue, forKey: "archagentsURL") }
    }

    /// App slug the sign-in handoff authenticates against.
    var appSlug: String {
        get { UserDefaults.standard.string(forKey: "appSlug") ?? ArchAgentsAuth.defaultAppSlug }
        set { UserDefaults.standard.set(newValue, forKey: "appSlug") }
    }

    /// Publishable key — only needed for the email/password fallback.
    var publishableKey: String {
        get { UserDefaults.standard.string(forKey: "publishableKey") ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: "publishableKey") }
    }

    var overlayEnabled: Bool = {
        let defaults = UserDefaults.standard
        // Event bodies may contain private room context, so previews are opt-in.
        guard defaults.object(forKey: "overlayEnabled") != nil else { return false }
        return defaults.bool(forKey: "overlayEnabled")
    }() {
        didSet {
            UserDefaults.standard.set(overlayEnabled, forKey: "overlayEnabled")
        }
    }

    var overlayAutoDismiss: Bool = {
        let defaults = UserDefaults.standard
        guard defaults.object(forKey: "overlayAutoDismiss") != nil else { return true }
        return defaults.bool(forKey: "overlayAutoDismiss")
    }() {
        didSet {
            UserDefaults.standard.set(
                overlayAutoDismiss,
                forKey: "overlayAutoDismiss"
            )
        }
    }

    var overlayDuration: Double = {
        let value = UserDefaults.standard.double(forKey: "overlayDuration")
        return value > 0 ? value : 6
    }() {
        didSet {
            UserDefaults.standard.set(overlayDuration, forKey: "overlayDuration")
        }
    }

    // MARK: Session lifecycle

    /// Restore a persisted session from the Keychain, if any.
    func restoreSession() async {
        guard case .restoring = phase else { return }
        guard let session = sessionStore.load() else {
            phase = .signedOut
            return
        }
        userEmail = session.email
        orgName = session.orgName
        activeAppID = session.appId
        currentUserID = session.userId
        let client = makeClient(for: session)
        phase = .signedIn(client)
        await refreshRooms()
    }

    /// Browser sign-in through ArchAgents — opens archagents.com's
    /// `/org/cli-auth` handoff (the same flow the archagent CLI uses) and
    /// receives the session tokens on a loopback redirect. If the browser
    /// already has an ArchAgents session, this completes without any
    /// re-authentication.
    func signInWithBrowser() async {
        phase = .signingIn
        browserSignInPending = true
        signInError = nil
        defer {
            browserSignInPending = false
            activeAuthServer = nil
        }

        do {
            let server = try await LoopbackCallbackServer.start()
            activeAuthServer = server
            let loginURL = try ArchAgentsAuth.loginURL(
                archagentsURL: archagentsURL,
                appSlug: appSlug,
                redirectURI: server.callbackURL
            )
            NSWorkspace.shared.open(loginURL)

            let callback = try await server.waitForCallback()
            let result = try ArchAgentsAuth.parseCallback(callback)

            let session = StoredSession(
                kind: .archagents,
                baseURL: baseURL,
                accessToken: result.accessToken,
                refreshToken: result.refreshToken,
                email: result.email.isEmpty ? nil : result.email,
                orgName: result.orgName.isEmpty ? nil : result.orgName,
                appId: result.appId,
                userId: result.userId
            )
            sessionStore.save(session)
            userEmail = session.email
            orgName = session.orgName
            activeAppID = result.appId
            currentUserID = result.userId
            phase = .signedIn(makeClient(for: session))
            await refreshRooms()
            startLiveFeed()
        } catch ArchAgentsAuth.AuthError.cancelled {
            phase = .signedOut
        } catch LoopbackCallbackServer.ServerError.cancelled {
            phase = .signedOut
        } catch let error as ApiError {
            signInError = error.message
            phase = .signedOut
        } catch {
            signInError = error.localizedDescription
            phase = .signedOut
        }
    }

    /// Abort a pending browser sign-in.
    func cancelSignIn() {
        activeAuthServer?.cancel()
    }

    /// Email/password fallback via `PlatformClient.withCredentials`.
    func signIn(email: String, password: String) async {
        guard !publishableKey.isEmpty else {
            signInError = "Set a publishable key in Settings first."
            return
        }
        phase = .signingIn
        signInError = nil
        do {
            let client = try await PlatformClient.withCredentials(
                apiKey: publishableKey,
                email: email,
                password: password,
                baseUrl: baseURL
            )
            if let accessToken = client.http.currentAccessToken() {
                sessionStore.save(
                    StoredSession(
                        kind: .password,
                        baseURL: baseURL,
                        accessToken: accessToken,
                        refreshToken: client.refreshToken,
                        apiKey: publishableKey,
                        email: email,
                        appId: nil,
                        userId: nil
                    )
                )
            }
            userEmail = email
            phase = .signedIn(client)
            await refreshRooms()
            startLiveFeed()
        } catch let error as ApiError {
            signInError = error.message
            phase = .signedOut
        } catch {
            signInError = "Could not sign in: \(error.localizedDescription)"
            phase = .signedOut
        }
    }

    func signOut() async {
        stopLiveFeed()
        if let client {
            await client.close()
        }
        sessionStore.clear()
        phase = .signedOut
        userEmail = nil
        userName = nil
        userAlias = nil
        orgName = nil
        activeAppID = nil
        currentUserID = nil
        hasLoadedRooms = false
        roomLoadError = nil
        messageHistoryByThread = [:]
        loadingOlderThreadIDs = []
        threadsWithLoadedOlderHistory = []
        hasLoadedCurrentUserProfile = false
        notifiedMentionMessageIDs = []
        pendingMentionTarget = nil
        messageFocus = nil
    }

    // MARK: Team Rooms

    /// Discover and hydrate every joined team containing a Team Room thread.
    /// Team pagination is fully drained inside TeamRoomAPI.
    func refreshRooms() async {
        guard let client else { return }
        isLoadingRooms = true
        roomLoadError = nil
        defer {
            isLoadingRooms = false
            hasLoadedRooms = true
        }

        do {
            let knownMessageIDs = Set(messages.map(\.id))
            let shouldNotify = hasLoadedRooms
            if !hasLoadedCurrentUserProfile {
                let me = try await client.users.me()
                currentUserID = me.id
                activeAppID = activeAppID ?? me.app
                userName = me.name
                userAlias = me.alias
                if userEmail == nil || userEmail?.isEmpty == true {
                    userEmail = me.email
                }
                if orgName == nil || orgName?.isEmpty == true {
                    orgName = me.orgName
                }
                hasLoadedCurrentUserProfile = true
            }

            let loaded = try await TeamRoomAPI.load(
                client: client,
                currentUserID: currentUserID,
                organizationName: orgName
            )
            let refreshedMessages = loaded.flatMap(\.messages)
            let refreshedEvents = loaded.flatMap(\.events)
            let hadLiveHistory = !messageHistoryByThread.isEmpty
            availableNetworks = loaded.map(\.room)
            members = loaded.flatMap(\.members)
            threads = loaded.flatMap(\.threads)
            let validThreadIDs = Set(threads.map(\.id))
            messages = hadLiveHistory
                ? mergeNewestFirst(
                    refreshedMessages,
                    with: messages.filter {
                        validThreadIDs.contains($0.threadID)
                    }
                )
                : refreshedMessages
            events = hadLiveHistory
                ? mergeNewestFirst(refreshedEvents, with: events)
                : refreshedEvents
            updateMessageHistories(
                loaded.flatMap(\.messageHistories),
                validThreadIDs: validThreadIDs
            )
            workstream = loaded.flatMap(\.workstream)
            tasks = []
            typingByThread = [:]
            newEventIDs.formIntersection(Set(events.map(\.id)))
            if shouldNotify {
                let eventsByMessageID = Dictionary(
                    uniqueKeysWithValues: refreshedEvents.map {
                        (String($0.id.dropFirst("event-".count)), $0)
                    }
                )
                for message in refreshedMessages.reversed()
                where !knownMessageIDs.contains(message.id)
                    && !message.isCurrentUser
                {
                    if let event = eventsByMessageID[message.id] {
                        announceIncomingMessage(message, event: event)
                    }
                }
            }

            if let prior = availableNetworks.first(where: { $0.id == selectedNetwork.id }) {
                selectedNetwork = prior
            } else if let first = availableNetworks.first {
                selectedNetwork = first
            } else {
                selectedNetwork = .empty
                selectedThread = .empty(networkID: "")
                return
            }
            selectedThread = currentThreads.first(where: { $0.id == selectedThread.id })
                ?? currentThreads.first(where: \.isDefault)
                ?? currentThreads.first
                ?? .empty(networkID: selectedNetwork.id)
            if let channelSession, channelSession.isConnected {
                installChannelMembers(channelSession.members)
            }
        } catch let error as ApiError {
            if hasLoadedRooms && !availableNetworks.isEmpty {
                showToast("Room refresh failed: \(error.message)")
            } else {
                roomLoadError = error.message
            }
        } catch {
            if hasLoadedRooms && !availableNetworks.isEmpty {
                showToast("Room refresh failed")
            } else {
                roomLoadError = error.localizedDescription
            }
        }
    }

    @discardableResult
    func prepareMentionNavigation(_ target: MentionNavigationTarget) -> Bool {
        guard let thread = threads.first(where: {
            $0.id == target.threadID && $0.networkID == target.networkID
        }),
        let network = availableNetworks.first(where: {
            $0.id == target.networkID
        })
        else { return false }

        selectedNetwork = network
        selectedThread = thread
        selectedTab = .chat
        guard currentMessages.contains(where: { $0.id == target.messageID }) else {
            return false
        }
        messageFocus = MessageFocus(
            threadID: target.threadID,
            messageID: target.messageID
        )
        return true
    }

    func navigateToMention(_ target: MentionNavigationTarget) async {
        pendingMentionTarget = target

        while sessionIsRestoring || isLoadingRooms {
            guard pendingMentionTarget == target else { return }
            try? await Task.sleep(for: .milliseconds(100))
        }
        guard pendingMentionTarget == target else { return }
        guard isSignedIn else {
            showToast("Sign in to open this mention")
            pendingMentionTarget = nil
            return
        }
        if !hasLoadedRooms {
            await refreshRooms()
        }
        guard pendingMentionTarget == target else { return }

        if prepareMentionNavigation(target) {
            pendingMentionTarget = nil
            markSelectedThreadRead()
            return
        }
        guard let client,
              threads.contains(where: {
                  $0.id == target.threadID && $0.networkID == target.networkID
              })
        else {
            showToast("That Team Room is no longer available")
            pendingMentionTarget = nil
            return
        }

        do {
            let page = try await TeamRoomAPI.loadMessageContext(
                client: client,
                threadID: target.threadID,
                networkID: target.networkID,
                messageID: target.messageID,
                currentUserID: currentUserID
            )
            guard pendingMentionTarget == target else { return }
            appendMessageContext(page)
            guard prepareMentionNavigation(target) else {
                showToast("That message is no longer available")
                pendingMentionTarget = nil
                return
            }
            pendingMentionTarget = nil
            markSelectedThreadRead()
        } catch {
            guard pendingMentionTarget == target else { return }
            showToast("Could not open that mention")
            pendingMentionTarget = nil
        }
    }

    private var sessionIsRestoring: Bool {
        if case .restoring = phase { return true }
        return false
    }

    /// Fetch the next older page through the generated thread resource. The
    /// platform returns pages oldest-first; TeamRoomAPI normalizes them to
    /// newest-first so each page appends at the bottom without re-sorting.
    func loadOlderMessages() async {
        guard let client else { return }
        let thread = selectedThread
        guard !thread.id.isEmpty,
              !loadingOlderThreadIDs.contains(thread.id),
              let cursor = messageHistoryByThread[thread.id]?.beforeCursor
        else { return }

        loadingOlderThreadIDs.insert(thread.id)
        defer { loadingOlderThreadIDs.remove(thread.id) }

        do {
            let page = try await TeamRoomAPI.loadMessagePage(
                client: client,
                threadID: thread.id,
                networkID: thread.networkID,
                currentUserID: currentUserID,
                beforeCursor: cursor
            )
            guard threads.contains(where: { $0.id == thread.id }) else { return }
            appendOlderPage(page)
        } catch let error as ApiError {
            showToast("Could not load older messages: \(error.message)")
        } catch {
            showToast("Could not load older messages")
        }
    }

    func appendOlderPage(_ page: LoadedMessagePage) {
        let messageIDs = Set(messages.map(\.id))
        messages.append(
            contentsOf: page.messages.filter { !messageIDs.contains($0.id) }
        )
        let eventIDs = Set(events.map(\.id))
        events.append(
            contentsOf: page.events.filter { !eventIDs.contains($0.id) }
        )
        messageHistoryByThread[page.threadID] = ThreadMessageHistory(
            threadID: page.threadID,
            beforeCursor: page.beforeCursor
        )
        threadsWithLoadedOlderHistory.insert(page.threadID)
    }

    func appendMessageContext(_ page: LoadedMessagePage) {
        let messageIDs = Set(messages.map(\.id))
        messages.append(
            contentsOf: page.messages.filter { !messageIDs.contains($0.id) }
        )
        let eventIDs = Set(events.map(\.id))
        events.append(
            contentsOf: page.events.filter { !eventIDs.contains($0.id) }
        )
        messageHistoryByThread[page.threadID] = ThreadMessageHistory(
            threadID: page.threadID,
            beforeCursor: page.beforeCursor
        )
        threadsWithLoadedOlderHistory.insert(page.threadID)
    }

    private func updateMessageHistories(
        _ refreshed: [ThreadMessageHistory],
        validThreadIDs: Set<String>
    ) {
        messageHistoryByThread = messageHistoryByThread.filter {
            validThreadIDs.contains($0.key)
        }
        threadsWithLoadedOlderHistory.formIntersection(validThreadIDs)
        for history in refreshed {
            if threadsWithLoadedOlderHistory.contains(history.threadID),
               messageHistoryByThread[history.threadID] != nil
            {
                continue
            }
            messageHistoryByThread[history.threadID] = history
        }
    }

    private func mergeNewestFirst<Element: Identifiable>(
        _ refreshed: [Element],
        with existing: [Element]
    ) -> [Element] where Element.ID: Hashable {
        var seen: Set<Element.ID> = []
        return (refreshed + existing).filter { seen.insert($0.id).inserted }
    }

    // MARK: Client construction

    /// Build a client for a stored session with automatic 401 refresh
    /// that persists rotated tokens back to the Keychain.
    ///
    /// Browser (archagents) sessions carry no app key, so they refresh via
    /// `/api/v1/auth/refresh/keyless` — the endpoint added for CLI
    /// org-login sessions. Password sessions refresh via the standard
    /// publishable-key `/api/v1/auth/refresh`.
    private func makeClient(for session: StoredSession) -> PlatformClient {
        var headers: [String: String] = [:]
        if let apiKey = session.apiKey {
            headers["x-archastro-api-key"] = apiKey
        }
        let client = PlatformClient(
            baseUrl: session.baseURL,
            accessToken: session.accessToken,
            defaultHeaders: headers
        )
        if let refreshToken = session.refreshToken {
            client.setRefreshToken(refreshToken)
        }

        // Refresh runs on a separate refresh-only HTTP client so it can
        // never re-enter the main client's 401 retry.
        let refreshHttp = HttpClient(
            baseUrl: session.baseURL,
            defaultHeaders: headers,
            refreshOnly: true
        )
        let refreshAuth = AuthClient(http: refreshHttp)
        let store = sessionStore
        let kind = session.kind
        client.http.setRefreshHandler { [weak client] in
            guard let client, let currentRefresh = client.refreshToken else {
                throw PlatformClientError.refreshFailed("No refresh token available")
            }

            let newAccessToken: String
            let newRefreshToken: String?
            switch kind {
            case .archagents:
                // Keyless rotation: the refresh token is the credential.
                let data: JSONValue = try await refreshHttp.request(
                    "/api/v1/auth/refresh/keyless",
                    method: "POST",
                    body: ["refresh_token": JSONValue.string(currentRefresh)]
                )
                guard let token = data["access_token"]?.stringValue else {
                    throw PlatformClientError.refreshFailed("Refresh did not return an access token")
                }
                newAccessToken = token
                newRefreshToken = data["refresh_token"]?.stringValue
            case .password:
                let refreshed = try await refreshAuth.refresh(refreshToken: currentRefresh)
                guard let token = refreshed.accessToken else {
                    throw PlatformClientError.refreshFailed("Refresh did not return an access token")
                }
                newAccessToken = token
                newRefreshToken = refreshed.refreshToken
            }

            client.setAccessToken(newAccessToken)
            if let newRefreshToken {
                client.setRefreshToken(newRefreshToken)
            }
            // The rotated refresh token is single-use — persist immediately
            // so a relaunch never replays a consumed token.
            var updated = session
            updated.accessToken = newAccessToken
            updated.refreshToken = newRefreshToken ?? currentRefresh
            store.save(updated)
            return newAccessToken
        }
        return client
    }
}
