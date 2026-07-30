import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct ChatView: View {
    @Environment(AppState.self) private var appState
    @State private var draft = ""
    @State private var showingThreads = false
    @State private var showingInspector = false
    @State private var showingImporter = false
    @State private var showingSearch = false
    @State private var searchTerm = ""

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Button { showingThreads.toggle() } label: {
                    HStack(spacing: 5) {
                        Image(systemName: "number").font(.system(size: 10, weight: .bold))
                        Text(appState.selectedThread.title).font(.system(size: 12, weight: .bold))
                        if appState.selectedThread.isDefault {
                            Text("DEFAULT").font(.system(size: 7, weight: .heavy)).foregroundStyle(Theme.green)
                        }
                        Image(systemName: "chevron.down").font(.system(size: 8, weight: .bold))
                    }.foregroundStyle(Theme.ink)
                }.buttonStyle(.plain).popover(isPresented: $showingThreads) {
                    threadPicker
                }
                Spacer()
                Button { showingSearch.toggle() } label: {
                    Image(systemName: "magnifyingglass")
                }
                Button { showingInspector.toggle() } label: {
                    Image(systemName: "info.circle")
                }
                .buttonStyle(.plain)
                .popover(isPresented: $showingInspector) {
                    ThreadInspectorView().environment(appState)
                }
            }
            .buttonStyle(.plain).foregroundStyle(Theme.muted)
            .padding(.horizontal, 14).frame(height: 39)
            .overlay(alignment: .bottom) { Rectangle().fill(Theme.line).frame(height: 1) }

            if showingSearch {
                HStack(spacing: 7) {
                    Image(systemName: "magnifyingglass").foregroundStyle(Theme.muted2)
                    TextField("Search this conversation", text: $searchTerm)
                        .textFieldStyle(.plain).font(.system(size: 10))
                    Button { searchTerm = ""; showingSearch = false } label: {
                        Image(systemName: "xmark.circle.fill").foregroundStyle(Theme.muted2)
                    }.buttonStyle(.plain)
                }
                .padding(8).background(Theme.surface)
                .overlay(alignment: .bottom) { Rectangle().fill(Theme.line).frame(height: 1) }
            }

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 13) {
                        ForEach(filteredMessages) { message in
                            messageRow(message).id(message.id)
                        }
                        if let typingName = appState.typingByThread[appState.selectedThread.id] {
                            typingIndicator(typingName)
                        }
                    }.padding(14)
                }
                .scrollIndicators(.hidden)
                .onChange(of: appState.messages.count) {
                    if let id = appState.messages.last?.id { proxy.scrollTo(id, anchor: .bottom) }
                }
            }

            HStack(spacing: 7) {
                Button { showingImporter = true } label: {
                    Image(systemName: "paperclip").font(.system(size: 12)).foregroundStyle(Theme.muted)
                }.buttonStyle(.plain)
                TextField("Message \(appState.selectedThread.title)…", text: $draft)
                    .textFieldStyle(.plain).font(.system(size: 11)).onSubmit(send)
                Button(action: send) {
                    Image(systemName: "arrow.up").font(.system(size: 10, weight: .bold)).foregroundStyle(.white)
                        .frame(width: 25, height: 25).background(Theme.ink, in: RoundedRectangle(cornerRadius: 7))
                }.buttonStyle(.plain).disabled(
                    draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        || appState.isSendingMessage
                )
            }
            .padding(8).background(Color.white, in: RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(Theme.lineStrong, lineWidth: 1))
            .padding(11)
        }
        .fileImporter(isPresented: $showingImporter, allowedContentTypes: [.data]) { result in
            if case .success(let url) = result {
                Task { await appState.sendMessage("", attachmentName: url.lastPathComponent) }
            }
        }
    }

    private var threadPicker: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("CHAT").font(.system(size: 9, weight: .heavy)).foregroundStyle(Theme.muted2).padding(8)
            ForEach(appState.currentThreads) { thread in
                Button {
                    appState.selectThread(thread); showingThreads = false
                } label: {
                    HStack {
                        Image(systemName: "number")
                        Text(thread.title)
                        if thread.isDefault { Text("Default").font(.system(size: 8)).foregroundStyle(Theme.green) }
                        Spacer()
                        if thread.unreadCount > 0 { Text("\(thread.unreadCount)").foregroundStyle(.white).padding(.horizontal, 5).background(Theme.badgeRed, in: Capsule()) }
                    }.font(.system(size: 10, weight: .semibold)).foregroundStyle(Theme.ink).padding(8)
                }.buttonStyle(.plain).hoverHighlight()
            }
            Button("+ New thread") { appState.openInFullApp("New thread") }
                .buttonStyle(.plain).font(.system(size: 10, weight: .semibold)).foregroundStyle(Theme.green).padding(8)
        }.padding(5).frame(width: 260)
    }

    private func messageRow(_ message: ChatMessage) -> some View {
        HStack(alignment: .top, spacing: 9) {
            Text(message.initials).font(.system(size: 8, weight: .bold)).foregroundStyle(.white)
                .frame(width: 27, height: 27).background(message.isCurrentUser ? Theme.ink : Theme.green, in: RoundedRectangle(cornerRadius: 8))
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 5) {
                    Text(message.author).font(.system(size: 10, weight: .bold)).foregroundStyle(Theme.ink)
                    Text(message.organization).font(.system(size: 8)).foregroundStyle(Theme.muted2)
                    Spacer()
                    Text(message.time).font(.system(size: 8)).foregroundStyle(Theme.muted2)
                }
                if !message.body.isEmpty {
                    Text(message.body).font(.system(size: 11)).lineSpacing(2.5).foregroundStyle(Theme.ink2)
                }
                if let attachment = message.attachmentName {
                    Label(attachment, systemImage: "doc.fill")
                        .font(.system(size: 9, weight: .semibold)).foregroundStyle(Theme.green)
                        .padding(7).background(Theme.greenSoft, in: RoundedRectangle(cornerRadius: 7))
                }
            }
        }
        .contextMenu {
            Button("Copy message") {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(message.body, forType: .string)
            }
            if message.isCurrentUser {
                Button("Delete message", role: .destructive) {
                    Task { await appState.deleteMessage(message) }
                }
            }
        }
    }

    private func typingIndicator(_ name: String) -> some View {
        HStack(spacing: 5) {
            Circle().fill(Theme.green).frame(width: 5, height: 5)
            Text("\(name) is typing…").font(.system(size: 9)).foregroundStyle(Theme.muted)
            Spacer()
        }.padding(.leading, 36)
    }

    private func send() {
        let content = draft
        Task {
            if await appState.sendMessage(content) { draft = "" }
        }
    }

    private var filteredMessages: [ChatMessage] {
        let query = searchTerm.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return appState.currentMessages }
        return appState.currentMessages.filter {
            $0.body.localizedCaseInsensitiveContains(query)
                || $0.author.localizedCaseInsensitiveContains(query)
                || ($0.attachmentName?.localizedCaseInsensitiveContains(query) ?? false)
        }
    }
}

struct ThreadInspectorView: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(appState.selectedThread.title).font(.system(size: 13, weight: .bold))
                    Text(appState.selectedThread.id).font(.system(size: 8, design: .monospaced)).foregroundStyle(Theme.muted2)
                }
                Spacer()
                Button("Settings ↗") { appState.openInFullApp("Thread settings") }
                    .buttonStyle(.plain).font(.system(size: 9, weight: .semibold)).foregroundStyle(Theme.green)
            }
            SectionLabel(text: "Participants")
            HStack(spacing: -4) {
                ForEach(appState.currentMembers.prefix(4)) { member in
                    Text(member.initials).font(.system(size: 8, weight: .bold)).foregroundStyle(.white)
                        .frame(width: 25, height: 25).background(Theme.green, in: Circle())
                        .overlay(Circle().stroke(Theme.paper, lineWidth: 2))
                }
                Text("\(appState.currentMembers.count) in room").font(.system(size: 9)).foregroundStyle(Theme.muted).padding(.leading, 10)
            }
            SectionLabel(text: "Tasks")
            ForEach(appState.currentTasks) { task in
                HStack(spacing: 8) {
                    Image(systemName: task.state == .completed ? "checkmark.circle.fill" : "circle.dotted")
                        .foregroundStyle(task.state == .completed ? Theme.green : Theme.amber)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(task.title).font(.system(size: 10, weight: .semibold))
                        Text("\(task.assignee) · \(task.state.rawValue)").font(.system(size: 8)).foregroundStyle(Theme.muted)
                    }
                    Spacer()
                }
            }
        }
        .padding(14).frame(width: 310)
    }
}
