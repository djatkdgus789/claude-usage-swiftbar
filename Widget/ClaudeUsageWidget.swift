import SwiftUI
import WidgetKit

struct UsageEntry: TimelineEntry {
    let date: Date
    let snapshot: UsageSnapshot?
}

struct UsageProvider: TimelineProvider {
    func placeholder(in context: Context) -> UsageEntry {
        UsageEntry(date: Date(), snapshot: .preview)
    }

    func getSnapshot(in context: Context, completion: @escaping (UsageEntry) -> Void) {
        let snapshot = SharedStore.load() ?? (context.isPreview ? .preview : nil)
        completion(UsageEntry(date: Date(), snapshot: snapshot))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<UsageEntry>) -> Void) {
        let now = Date()
        let snapshot = SharedStore.load()

        // 현재 시점 + 각 한도의 초기화 시점마다 엔트리를 만들어
        // 메인 앱이 꺼져 있어도 초기화 후에는 0%로 표시되게 한다.
        var dates = [now]
        let horizon = now.addingTimeInterval(24 * 3600)
        for window in snapshot?.windows ?? [] {
            if let reset = window.resetsAt, reset > now, reset < horizon {
                dates.append(reset.addingTimeInterval(1))
            }
        }
        let entries = Set(dates).sorted().map { UsageEntry(date: $0, snapshot: snapshot) }

        // 메인 앱이 갱신할 때마다 reloadTimelines를 호출하므로 이 정책은 안전망 역할만 한다.
        completion(Timeline(entries: entries, policy: .after(now.addingTimeInterval(15 * 60))))
    }
}

// MARK: - Views

struct ClaudeUsageWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: UsageEntry

    var body: some View {
        Group {
            if let snapshot = entry.snapshot, !snapshot.windows.isEmpty {
                switch family {
                case .systemSmall: SmallView(snapshot: snapshot, now: entry.date)
                case .systemLarge: LargeView(snapshot: snapshot, now: entry.date)
                default: MediumView(snapshot: snapshot, now: entry.date)
                }
            } else {
                EmptyStateView(error: entry.snapshot?.error)
            }
        }
        .containerBackground(.background, for: .widget)
    }
}

private struct Header: View {
    let snapshot: UsageSnapshot

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: "sparkle")
                .foregroundStyle(Color.claude)
            Text("Claude")
                .font(.caption.weight(.semibold))
            if let plan = snapshot.planDisplayName {
                Text(plan)
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(Color.claude)
            }
            Spacer(minLength: 0)
            if snapshot.error != nil {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.caption2)
                    .foregroundStyle(.orange)
            }
        }
    }
}

private struct SmallView: View {
    let snapshot: UsageSnapshot
    let now: Date

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Header(snapshot: snapshot)
            Spacer(minLength: 0)
            ForEach(snapshot.windows.prefix(2)) { window in
                UsageRow(window: window, now: now)
            }
        }
    }
}

private struct MediumView: View {
    let snapshot: UsageSnapshot
    let now: Date

    var body: some View {
        let primary = snapshot.primary
        let others = snapshot.windows.filter { $0.id != primary?.id }

        VStack(alignment: .leading, spacing: 8) {
            Header(snapshot: snapshot)
            HStack(spacing: 16) {
                if let primary {
                    PrimaryGauge(window: primary, now: now)
                }
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(others.prefix(3)) { window in
                        UsageRow(window: window, now: now, showsReset: others.count < 3)
                    }
                    Spacer(minLength: 0)
                    UpdatedLabel(snapshot: snapshot)
                }
            }
        }
    }
}

private struct LargeView: View {
    let snapshot: UsageSnapshot
    let now: Date

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Header(snapshot: snapshot)
            if let primary = snapshot.primary {
                HStack {
                    Spacer()
                    PrimaryGauge(window: primary, now: now, size: 110)
                    Spacer()
                }
            }
            ForEach(snapshot.windows.filter { $0.id != snapshot.primary?.id }.prefix(4)) { window in
                UsageRow(window: window, now: now)
            }
            Spacer(minLength: 0)
            UpdatedLabel(snapshot: snapshot)
        }
    }
}

private struct PrimaryGauge: View {
    let window: UsageWindow
    let now: Date
    var size: CGFloat = 84

    var body: some View {
        let percent = window.utilization(at: now)
        VStack(spacing: 4) {
            ZStack {
                UsageRing(percent: percent, lineWidth: size / 9)
                VStack(spacing: 0) {
                    Text("\(Int(percent.rounded()))%")
                        .font(.system(size: size / 4.2, weight: .bold, design: .rounded).monospacedDigit())
                    Text(window.shortTitle)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            .frame(width: size, height: size)
            ResetLabel(date: window.resetsAt, now: now)
                .frame(maxWidth: size + 20)
                .minimumScaleFactor(0.8)
        }
    }
}

private struct UpdatedLabel: View {
    let snapshot: UsageSnapshot

    var body: some View {
        if let fetchedAt = snapshot.fetchedAt {
            Text("업데이트 \(fetchedAt, style: .time)")
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
    }
}

private struct EmptyStateView: View {
    let error: String?

    var body: some View {
        VStack(spacing: 6) {
            Image(systemName: "sparkle")
                .font(.title2)
                .foregroundStyle(Color.claude)
            Text(error ?? "Claude Usage 앱을 실행하세요")
                .font(.caption)
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
                .lineLimit(4)
        }
    }
}

// MARK: - Widget

@main
struct ClaudeUsageWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: SharedStore.widgetKind, provider: UsageProvider()) { entry in
            ClaudeUsageWidgetView(entry: entry)
        }
        .configurationDisplayName("Claude 사용량")
        .description("Claude 구독의 5시간 세션 및 주간 사용량을 보여줍니다.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge])
    }
}

#Preview(as: .systemMedium) {
    ClaudeUsageWidget()
} timeline: {
    UsageEntry(date: .now, snapshot: .preview)
}
