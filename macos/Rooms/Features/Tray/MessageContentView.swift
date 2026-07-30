import AppKit
import Charts
import MarkdownUI
import SwiftUI

/// The native counterpart to the web room's ReactMarkdown + rich attachment
/// pipeline. Message text remains selectable and links/images are handled by
/// MarkdownUI's GFM renderer; attachment payloads stay typed and native.
struct MessageContentView: View {
    var message: ChatMessage

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            if !message.displayBody.isEmpty {
                Markdown(message.displayBody)
                    .markdownTheme(.gitHub)
                    .markdownTextStyle(\.text) {
                        FontSize(.em(0.86))
                        ForegroundColor(Theme.ink2)
                    }
                    .markdownTextStyle(\.code) {
                        FontFamilyVariant(.monospaced)
                        FontSize(.em(0.82))
                        ForegroundColor(Theme.ink)
                        BackgroundColor(Theme.surface)
                    }
                    .tint(Theme.green)
                    .textSelection(.enabled)
                    .environment(
                        \.openURL,
                        OpenURLAction { url in
                            guard ["http", "https", "mailto"].contains(
                                url.scheme?.lowercased() ?? ""
                            ) else { return .discarded }
                            return NSWorkspace.shared.open(url) ? .handled : .discarded
                        }
                    )
            }

            if !message.attachments.isEmpty {
                MessageAttachmentsView(attachments: message.attachments)
            }
        }
    }
}

enum MessageText {
    static func plainText(_ markdown: String) -> String {
        MarkdownContent(markdown).renderPlainText()
    }
}

struct MessageAttachmentsView: View {
    var attachments: [ChatAttachment]

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            ForEach(attachments) { attachment in
                attachmentView(attachment)
            }
        }
    }

    @ViewBuilder
    private func attachmentView(_ attachment: ChatAttachment) -> some View {
        if let chart = attachment.chart {
            ChartAttachmentView(chart: chart)
        } else if let task = attachment.task {
            TaskAttachmentView(task: task)
        } else if attachment.type == "artifact" {
            ArtifactAttachmentView(attachment: attachment)
        } else if attachment.type == "scraped_link" {
            LinkAttachmentView(attachment: attachment)
        } else if attachment.isImage, let url = attachment.resolvedURL {
            ImageAttachmentView(attachment: attachment, url: url)
        } else {
            FileAttachmentView(attachment: attachment)
        }
    }
}

private struct ImageAttachmentView: View {
    var attachment: ChatAttachment
    var url: URL

    var body: some View {
        Button {
            NSWorkspace.shared.open(url)
        } label: {
            AsyncImage(url: url) { phase in
                switch phase {
                case .empty:
                    ProgressView()
                        .controlSize(.small)
                        .frame(maxWidth: .infinity, minHeight: 72)
                case .success(let image):
                    image
                        .resizable()
                        .scaledToFit()
                        .frame(maxWidth: .infinity, maxHeight: 240)
                case .failure:
                    attachmentFallback
                @unknown default:
                    attachmentFallback
                }
            }
            .background(Theme.surface)
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .overlay {
                RoundedRectangle(cornerRadius: 8)
                    .stroke(Theme.line, lineWidth: 1)
            }
        }
        .buttonStyle(.plain)
        .help("Open \(attachment.displayName)")
    }

    private var attachmentFallback: some View {
        Label(attachment.displayName, systemImage: "photo")
            .font(.system(size: 9, weight: .semibold))
            .foregroundStyle(Theme.green)
            .frame(maxWidth: .infinity, minHeight: 56)
    }
}

private struct FileAttachmentView: View {
    var attachment: ChatAttachment

    var body: some View {
        Group {
            if let url = attachment.resolvedURL {
                Button {
                    NSWorkspace.shared.open(url)
                } label: {
                    card
                }
                .buttonStyle(.plain)
            } else {
                card
            }
        }
    }

    private var card: some View {
        HStack(spacing: 8) {
            Image(systemName: systemImage)
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(Theme.green)
                .frame(width: 24, height: 24)
                .background(Theme.greenSoft, in: RoundedRectangle(cornerRadius: 6))
            VStack(alignment: .leading, spacing: 1) {
                Text(attachment.displayName)
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(Theme.ink)
                    .lineLimit(2)
                Text(detail)
                    .font(.system(size: 8))
                    .foregroundStyle(Theme.muted2)
            }
            Spacer(minLength: 4)
            if attachment.resolvedURL != nil {
                Image(systemName: "arrow.up.right")
                    .font(.system(size: 8, weight: .bold))
                    .foregroundStyle(Theme.muted2)
            }
        }
        .padding(7)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .stroke(Theme.line, lineWidth: 1)
        }
    }

    private var detail: String {
        if attachment.type == "action" {
            let status = attachment.status
                ?? attachment.object?["status"]?.stringValue
            let actionType = attachment.object?["type"]?.stringValue
            return [actionType, status]
                .compactMap { $0 }
                .joined(separator: " · ")
                .replacingOccurrences(of: "_", with: " ")
        }
        return attachment.contentType
            ?? attachment.mediaType
            ?? attachment.type.replacingOccurrences(of: "_", with: " ").capitalized
    }

    private var systemImage: String {
        switch attachment.type {
        case "media": "play.rectangle.fill"
        case "action": "bolt.fill"
        case "chart": "chart.bar.fill"
        default: "doc.fill"
        }
    }
}

private struct LinkAttachmentView: View {
    var attachment: ChatAttachment

    var body: some View {
        Group {
            if let url = attachment.resolvedURL {
                Button {
                    NSWorkspace.shared.open(url)
                } label: {
                    card
                }
                .buttonStyle(.plain)
            } else {
                card
            }
        }
    }

    private var card: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let image = safePreviewURL {
                AsyncImage(url: image) { phase in
                    if case .success(let value) = phase {
                        value.resizable().scaledToFill()
                    } else {
                        Theme.surface
                    }
                }
                .frame(height: 82)
                .clipped()
                .clipShape(RoundedRectangle(cornerRadius: 6))
            }
            Text(attachment.title ?? attachment.url ?? "Link")
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(Theme.ink)
                .lineLimit(2)
            if let description = attachment.description, !description.isEmpty {
                Text(description)
                    .font(.system(size: 8))
                    .foregroundStyle(Theme.muted)
                    .lineLimit(2)
            }
            if let url = attachment.url {
                Text(url)
                    .font(.system(size: 8))
                    .foregroundStyle(Theme.green)
                    .lineLimit(1)
            }
        }
        .padding(8)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .stroke(Theme.line, lineWidth: 1)
        }
    }

    private var safePreviewURL: URL? {
        guard let raw = attachment.imageURL,
              let url = URL(string: raw),
              ["http", "https"].contains(url.scheme?.lowercased() ?? "")
        else { return nil }
        return url
    }
}

private struct ArtifactAttachmentView: View {
    var attachment: ChatAttachment

    var body: some View {
        Group {
            if let url = attachment.resolvedURL {
                Button {
                    NSWorkspace.shared.open(url)
                } label: {
                    card
                }
                .buttonStyle(.plain)
            } else {
                card
            }
        }
    }

    private var card: some View {
        VStack(alignment: .leading, spacing: 3) {
            Label("ARTIFACT", systemImage: "shippingbox.fill")
                .font(.system(size: 8, weight: .heavy))
                .foregroundStyle(Color.indigo)
            Text(attachment.title ?? attachment.filename ?? "Artifact")
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(Theme.ink)
                .lineLimit(2)
            if let description = attachment.description {
                Text(description)
                    .font(.system(size: 8))
                    .foregroundStyle(Theme.muted)
                    .lineLimit(2)
            }
            Text(
                [
                    attachment.version.map { "Version \($0)" },
                    attachment.contentType,
                ]
                .compactMap { $0 }
                .joined(separator: " · ")
            )
            .font(.system(size: 8))
            .foregroundStyle(Theme.muted2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(8)
        .background(Color.indigo.opacity(0.06), in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .stroke(Color.indigo.opacity(0.18), lineWidth: 1)
        }
    }
}

private struct TaskAttachmentView: View {
    var task: ChatTaskAttachment

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: statusIcon)
                    .foregroundStyle(statusColor)
                Text(task.name)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(task.status == "done" ? Theme.muted : Theme.ink)
                    .strikethrough(task.status == "done")
                Spacer(minLength: 4)
                if let status = task.status {
                    Text(status.replacingOccurrences(of: "_", with: " ").uppercased())
                        .font(.system(size: 7, weight: .heavy))
                        .foregroundStyle(statusColor)
                }
            }
            if let description = task.description, !description.isEmpty {
                Text(description)
                    .font(.system(size: 8))
                    .foregroundStyle(Theme.muted)
                    .lineLimit(2)
                    .padding(.leading, 20)
            }
            if task.ownerName != nil || task.dueDate != nil || task.subtasksCount > 0 {
                HStack(spacing: 10) {
                    if let owner = task.ownerName {
                        HStack(spacing: 3) {
                            if let ownerImageURL {
                                AsyncImage(url: ownerImageURL) { phase in
                                    if case .success(let image) = phase {
                                        image.resizable().scaledToFill()
                                    } else {
                                        Image(systemName: "person.fill")
                                    }
                                }
                                .frame(width: 11, height: 11)
                                .clipShape(Circle())
                            } else {
                                Image(systemName: "person.fill")
                            }
                            Text(owner)
                        }
                    }
                    if let dueDate = formattedDueDate {
                        Label(dueDate, systemImage: "calendar")
                    }
                    if task.subtasksCount > 0 {
                        Text("\(task.subtasksCount) subtask\(task.subtasksCount == 1 ? "" : "s")")
                    }
                }
                .font(.system(size: 8))
                .foregroundStyle(Theme.muted2)
                .padding(.leading, 20)
            }
        }
        .padding(8)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .stroke(Theme.line, lineWidth: 1)
        }
    }

    private var statusIcon: String {
        switch task.status {
        case "done": "checkmark.circle.fill"
        case "in_progress": "circle.dotted"
        default: "circle"
        }
    }

    private var statusColor: Color {
        switch task.status {
        case "done": Theme.green
        case "in_progress": Theme.blue
        default: Theme.muted2
        }
    }

    private var formattedDueDate: String? {
        guard var raw = task.dueDate else { return nil }
        if !raw.hasSuffix("Z")
            && raw.range(
                of: #"[+-]\d{2}:\d{2}$"#,
                options: .regularExpression
            ) == nil
        {
            raw += "Z"
        }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = formatter.date(from: raw)
            ?? {
                formatter.formatOptions = [.withInternetDateTime]
                return formatter.date(from: raw)
            }()
        else { return raw }
        return date.formatted(.dateTime.month(.abbreviated).day())
    }

    private var ownerImageURL: URL? {
        guard let raw = task.ownerImageURL,
              let url = URL(string: raw),
              ["http", "https"].contains(url.scheme?.lowercased() ?? "")
        else { return nil }
        return url
    }
}

private struct ChartAttachmentView: View {
    var chart: ChatChart

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack {
                Label("CHART", systemImage: "chart.xyaxis.line")
                    .font(.system(size: 8, weight: .heavy))
                    .foregroundStyle(Color.indigo)
                Spacer()
                Text(chart.kindLabel)
                    .font(.system(size: 7, weight: .bold))
                    .foregroundStyle(Theme.muted2)
            }
            if let title = chart.title {
                Text(title)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(Theme.ink)
            }
            if case .series(_, _, _, _, let series) = chart {
                LazyVGrid(
                    columns: [GridItem(.adaptive(minimum: 82), spacing: 6)],
                    alignment: .leading,
                    spacing: 3
                ) {
                    ForEach(series) { item in
                        HStack(spacing: 3) {
                            Text(item.name)
                                .fontWeight(.semibold)
                                .lineLimit(1)
                            Text(item.values.last?.formatted() ?? "—")
                                .foregroundStyle(Theme.ink)
                            if item.values.count > 1,
                               let last = item.values.last
                            {
                                let delta = last - item.values[item.values.count - 2]
                                Text("\(delta > 0 ? "+" : "")\(delta.formatted())")
                                    .foregroundStyle(
                                        delta > 0
                                            ? Theme.green
                                            : delta < 0 ? Theme.red : Theme.muted2
                                    )
                            }
                            if item.axis == "right" {
                                Text("R")
                                    .font(.system(size: 6, weight: .heavy))
                                    .foregroundStyle(Theme.muted2)
                                    .help("Right axis")
                            }
                        }
                        .font(.system(size: 7))
                        .foregroundStyle(Theme.muted)
                    }
                }
            }
            chartPlot
                .frame(height: 130)
        }
        .padding(8)
        .background(Color.white, in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .stroke(Theme.line, lineWidth: 1)
        }
    }

    @ViewBuilder
    private var chartPlot: some View {
        switch chart {
        case .series(let kind, _, _, let categories, let series):
            seriesPlot(kind: kind, categories: categories, series: series)
        case .cells(let kind, _, let cells):
            if kind == .pie {
                piePlot(cells)
            } else {
                TreemapPlot(cells: cells)
            }
        case .scatter(_, let xLabel, let yLabel, let groups):
            Chart {
                ForEach(groups) { group in
                    ForEach(group.points) { point in
                        PointMark(
                            x: .value(xLabel ?? "X", point.x),
                            y: .value(yLabel ?? "Y", point.y)
                        )
                        .foregroundStyle(by: .value("Series", group.name))
                    }
                }
            }
            .chartLegend(position: .bottom, spacing: 4)
        }
    }

    @ViewBuilder
    private func seriesPlot(
        kind: ChatChart.SeriesKind,
        categories: [String],
        series: [ChatChart.Series]
    ) -> some View {
        switch kind {
        case .bars:
            Chart {
                seriesMarks(categories: categories, series: series) { category, value, name in
                    BarMark(
                        x: .value("Category", category),
                        y: .value("Value", value)
                    )
                    .foregroundStyle(by: .value("Series", name))
                    .position(by: .value("Series", name))
                }
            }
            .chartLegend(position: .bottom, spacing: 4)
        case .line:
            Chart {
                seriesMarks(categories: categories, series: series) { category, value, name in
                    LineMark(
                        x: .value("Category", category),
                        y: .value("Value", value),
                        series: .value("Series", name)
                    )
                    .foregroundStyle(by: .value("Series", name))
                    .interpolationMethod(.catmullRom)
                    PointMark(
                        x: .value("Category", category),
                        y: .value("Value", value)
                    )
                    .foregroundStyle(by: .value("Series", name))
                }
            }
            .chartLegend(position: .bottom, spacing: 4)
        case .area:
            Chart {
                seriesMarks(categories: categories, series: series) { category, value, name in
                    AreaMark(
                        x: .value("Category", category),
                        y: .value("Value", value),
                        series: .value("Series", name)
                    )
                    .foregroundStyle(by: .value("Series", name))
                    .opacity(0.45)
                    LineMark(
                        x: .value("Category", category),
                        y: .value("Value", value),
                        series: .value("Series", name)
                    )
                    .foregroundStyle(by: .value("Series", name))
                }
            }
            .chartLegend(position: .bottom, spacing: 4)
        case .composed:
            Chart {
                ForEach(Array(series.enumerated()), id: \.offset) { _, item in
                    ForEach(Array(categories.enumerated()), id: \.offset) { index, category in
                        let value = item.values.indices.contains(index) ? item.values[index] : 0
                        if item.presentation == "line" {
                            LineMark(
                                x: .value("Category", category),
                                y: .value("Value", value),
                                series: .value("Series", item.name)
                            )
                            .foregroundStyle(by: .value("Series", item.name))
                        } else {
                            BarMark(
                                x: .value("Category", category),
                                y: .value("Value", value)
                            )
                            .foregroundStyle(by: .value("Series", item.name))
                            .position(by: .value("Series", item.name))
                        }
                    }
                }
            }
            .chartLegend(position: .bottom, spacing: 4)
        }
    }

    @ChartContentBuilder
    private func seriesMarks<Content: ChartContent>(
        categories: [String],
        series: [ChatChart.Series],
        @ChartContentBuilder content: @escaping (String, Double, String) -> Content
    ) -> some ChartContent {
        ForEach(Array(series.enumerated()), id: \.offset) { _, item in
            ForEach(Array(categories.enumerated()), id: \.offset) { index, category in
                content(
                    category,
                    item.values.indices.contains(index) ? item.values[index] : 0,
                    item.name
                )
            }
        }
    }

    private func piePlot(_ cells: [ChatChart.Cell]) -> some View {
        Chart(cells) { cell in
            SectorMark(
                angle: .value("Size", max(0, cell.size)),
                innerRadius: .ratio(0.45),
                angularInset: 1
            )
            .foregroundStyle(by: .value("Cell", cell.name))
        }
        .chartLegend(position: .bottom, spacing: 4)
    }
}

private struct TreemapPlot: View {
    var cells: [ChatChart.Cell]

    var body: some View {
        GeometryReader { geometry in
            let positiveTotal = cells.reduce(0) { $0 + max(0, $1.size) }
            HStack(spacing: 2) {
                ForEach(Array(cells.enumerated()), id: \.offset) { index, cell in
                    let ratio = positiveTotal > 0
                        ? max(0, cell.size) / positiveTotal
                        : 1 / Double(max(cells.count, 1))
                    ZStack(alignment: .bottomLeading) {
                        Rectangle()
                            .fill(treemapColor(index: index, heat: cell.heat))
                        Text(cell.name)
                            .font(.system(size: 8, weight: .semibold))
                            .foregroundStyle(.white)
                            .lineLimit(2)
                            .padding(4)
                    }
                    .frame(width: max(18, geometry.size.width * ratio - 2))
                    .clipShape(RoundedRectangle(cornerRadius: 4))
                    .help("\(cell.name): \(cell.size.formatted())")
                }
            }
        }
    }

    private func treemapColor(index: Int, heat: Double?) -> Color {
        if let heat {
            let value = min(1, max(0, heat))
            return Color(
                hue: 0.59 - value * 0.59,
                saturation: 0.55 + value * 0.35,
                brightness: 0.88 - value * 0.36
            )
        }
        let palette: [Color] = [.indigo, .orange, .green, .red, .cyan, .purple]
        return palette[index % palette.count]
    }
}

private extension ChatChart {
    var title: String? {
        switch self {
        case .series(_, let title, _, _, _),
             .cells(_, let title, _),
             .scatter(let title, _, _, _):
            title
        }
    }

    var kindLabel: String {
        let kind: String
        switch self {
        case .series(let value, _, _, _, _): kind = value.rawValue.capitalized
        case .cells(let value, _, _): kind = value.rawValue.capitalized
        case .scatter: kind = "Scatter"
        }
        guard case .series(_, _, let unit, _, _) = self,
              let unit,
              !unit.isEmpty
        else { return kind }
        return "\(kind) · \(unit)"
    }
}
