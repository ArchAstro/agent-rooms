import SwiftUI

/// Sidebar listing the user's rooms.
struct SidebarView: View {
    let rooms: [Room]
    @Binding var selection: Room.ID?

    var body: some View {
        List(selection: $selection) {
            Section("Rooms") {
                ForEach(rooms) { room in
                    Label(room.name, systemImage: "number")
                        .badge(room.unreadCount > 0 ? room.unreadCount : 0)
                        .tag(room.id)
                }
            }
        }
        .listStyle(.sidebar)
        .navigationSplitViewColumnWidth(min: 200, ideal: 240)
        .navigationTitle("Rooms")
    }
}
