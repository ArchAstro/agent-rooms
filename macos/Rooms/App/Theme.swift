import SwiftUI

/// Design tokens from docs/mocks/team-room-menubar.html — the warm-paper
/// visual language for the Team Room tray.
enum Theme {
    // Ink
    static let ink = Color(hex: 0x171716)
    static let ink2 = Color(hex: 0x3F3E3A)
    static let muted = Color(hex: 0x77736D)
    static let muted2 = Color(hex: 0x6F6B65)

    // Surfaces
    static let paper = Color(hex: 0xFAF9F6)
    static let surface = Color(hex: 0xF1EFEA)
    static let line = Color(hex: 0x312E29).opacity(0.12)
    static let lineStrong = Color(hex: 0x312E29).opacity(0.18)

    // Accents
    static let purple = Color(hex: 0x6257D9)
    static let purpleSoft = Color(hex: 0xEFEDFF)
    static let green = Color(hex: 0x148266)
    static let greenSoft = Color(hex: 0xE7F5F0)
    static let amber = Color(hex: 0xA96414)
    static let amberSoft = Color(hex: 0xFBF0DC)
    static let red = Color(hex: 0xB54848)
    static let redSoft = Color(hex: 0xF9E8E7)
    static let blue = Color(hex: 0x376E9C)
    static let badgeRed = Color(hex: 0xCA514E)

    // Tray metrics
    static let trayWidth: CGFloat = 430
    static let trayHeight: CGFloat = 690
}

extension Color {
    init(hex: UInt32) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255
        )
    }
}

/// Uppercase section label with a hairline rule — mirrors `.section-label`.
struct SectionLabel: View {
    let text: String

    var body: some View {
        HStack(spacing: 7) {
            Text(text.uppercased())
                .font(.system(size: 9, weight: .heavy))
                .kerning(0.9)
                .foregroundStyle(Theme.muted2)
            Rectangle()
                .fill(Theme.line)
                .frame(height: 1)
        }
        .padding(.horizontal, 2)
    }
}

/// Small colored kind chip — mirrors `.card-kind`.
struct KindChip: View {
    let text: String
    let color: Color
    let background: Color

    var body: some View {
        Text(text.uppercased())
            .font(.system(size: 9, weight: .heavy))
            .kerning(0.7)
            .foregroundStyle(color)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(background, in: RoundedRectangle(cornerRadius: 5))
    }
}

/// Hover feedback shared by the tray's flat controls — the SwiftUI
/// equivalent of the mock's `:hover` backgrounds.
struct HoverHighlight: ViewModifier {
    var cornerRadius: CGFloat = 7
    var color = Color(hex: 0x21201C).opacity(0.06)
    @State private var hovered = false

    func body(content: Content) -> some View {
        content
            .background(
                hovered ? color : .clear,
                in: RoundedRectangle(cornerRadius: cornerRadius)
            )
            .onHover { hovered = $0 }
    }
}

extension View {
    func hoverHighlight(
        cornerRadius: CGFloat = 7,
        color: Color = Color(hex: 0x21201C).opacity(0.06)
    ) -> some View {
        modifier(HoverHighlight(cornerRadius: cornerRadius, color: color))
    }
}

/// Rounded status pill — mirrors `.status`.
struct StatusPill: View {
    let text: String
    let color: Color
    let background: Color

    var body: some View {
        Text(text)
            .font(.system(size: 9, weight: .bold))
            .foregroundStyle(color)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(background, in: Capsule())
            .fixedSize()
    }
}
