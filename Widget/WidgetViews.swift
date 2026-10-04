import SwiftUI
import WidgetKit

struct UsageEntry: TimelineEntry {
    let date: Date
    let snapshot: UsageSnapshot?
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

struct Header: View {
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

struct SmallView: View {
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

struct MediumView: View {
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

struct LargeView: View {
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

struct PrimaryGauge: View {
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

struct UpdatedLabel: View {
    let snapshot: UsageSnapshot

    var body: some View {
        if let fetchedAt = snapshot.fetchedAt {
            Text("업데이트 \(fetchedAt, style: .time)")
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
    }
}

struct EmptyStateView: View {
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
