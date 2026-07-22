import SwiftUI

/// Detail view for a single room. Message history and the realtime
/// channel wiring (`ApiChatChannel`) land next; the shell establishes the
/// layout: transcript area above a fixed composer.
struct RoomView: View {
    let room: Room
    @State private var draft = ""

    var body: some View {
        VStack(spacing: 0) {
            ContentUnavailableView(
                "No Messages Yet",
                systemImage: "text.bubble",
                description: Text("Messages in \(room.name) will appear here.")
            )
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            Divider()

            HStack(alignment: .bottom, spacing: 8) {
                TextField("Message \(room.name)", text: $draft, axis: .vertical)
                    .textFieldStyle(.plain)
                    .lineLimit(1...6)
                    .onSubmit(send)
                Button("Send", systemImage: "arrow.up.circle.fill", action: send)
                    .labelStyle(.iconOnly)
                    .buttonStyle(.borderless)
                    .font(.title2)
                    .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            .padding(10)
            .background(.bar)
        }
        .navigationTitle(room.name)
        .navigationSubtitle("\(room.unreadCount) unread")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button("Room Info", systemImage: "info.circle") {
                    // Room info inspector lands with the rooms feature.
                }
            }
        }
    }

    private func send() {
        // Posting goes through ApiChatChannel once rooms are wired up.
        draft = ""
    }
}
