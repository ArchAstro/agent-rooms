import SwiftUI

struct EventOverlayView: View {
    let event: StreamEvent
    let onOpen: () -> Void

    var body: some View {
        Button(action: onOpen) {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: event.level.systemImage)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(event.level.color)
                    .frame(width: 30, height: 30)
                    .background(event.level.background, in: RoundedRectangle(cornerRadius: 9))

                VStack(alignment: .leading, spacing: 5) {
                    HStack {
                        Text(event.author)
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(Theme.ink)
                            .lineLimit(1)
                        Spacer()
                        Text("Open activity")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(Theme.purple)
                        Image(systemName: "chevron.right")
                            .font(.system(size: 8, weight: .bold))
                            .foregroundStyle(Theme.purple.opacity(0.8))
                    }
                    Text(event.body)
                        .font(.system(size: 11))
                        .foregroundStyle(Theme.ink2)
                        .lineLimit(3)
                        .multilineTextAlignment(.leading)
                }
            }
            .padding(14)
            .frame(width: 356, height: 112, alignment: .topLeading)
            .contentShape(RoundedRectangle(cornerRadius: 16))
        }
        .buttonStyle(.plain)
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(Theme.paper.opacity(0.98))
                .overlay(
                    RoundedRectangle(cornerRadius: 16)
                        .stroke(Color.white.opacity(0.75), lineWidth: 0.75)
                )
                .shadow(color: .black.opacity(0.2), radius: 22, y: 9)
        )
        .padding(2)
        .help("Open Team Room activity")
        .accessibilityLabel("\(event.author): \(event.body). Open Team Room activity.")
    }
}
