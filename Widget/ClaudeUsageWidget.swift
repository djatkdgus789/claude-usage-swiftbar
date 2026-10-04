import SwiftUI
import WidgetKit

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
        completion(Timeline(entries: entries, policy: .after(now.addingTimeInterval(5 * 60))))
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
