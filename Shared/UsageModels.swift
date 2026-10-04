import Foundation

/// 하나의 사용량 한도 구간 (예: 5시간 세션, 주간 한도).
struct UsageWindow: Codable, Hashable, Identifiable {
    /// API 응답의 키 (`five_hour`, `seven_day`, ...)
    let id: String
    /// 사용률 (0 ~ 100)
    let utilization: Double
    /// 한도가 초기화되는 시각
    let resetsAt: Date?

    var title: String { Self.title(for: id) }
    var shortTitle: String { Self.shortTitle(for: id) }

    /// `date` 시점 기준 사용률. 초기화 시각이 지났다면 0으로 간주한다.
    func utilization(at date: Date) -> Double {
        if let resetsAt, resetsAt <= date { return 0 }
        return min(max(utilization, 0), 100)
    }

    static let displayOrder = [
        "five_hour",
        "seven_day",
        "seven_day_sonnet",
        "seven_day_opus",
        "seven_day_oauth_apps",
        "extra_usage",
    ]

    static func title(for key: String) -> String {
        switch key {
        case "five_hour": return "5시간 세션"
        case "seven_day": return "주간 한도"
        case "seven_day_sonnet": return "주간 Sonnet"
        case "seven_day_opus": return "주간 Opus"
        case "seven_day_oauth_apps": return "주간 OAuth 앱"
        case "extra_usage": return "추가 사용량"
        default: return key.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }

    static func shortTitle(for key: String) -> String {
        switch key {
        case "five_hour": return "5h"
        case "seven_day": return "7d"
        default: return title(for: key)
        }
    }

    static func sortKey(_ key: String) -> Int {
        displayOrder.firstIndex(of: key) ?? displayOrder.count
    }
}

/// 앱이 가져와 위젯과 공유하는 사용량 스냅샷.
struct UsageSnapshot: Codable, Hashable {
    var windows: [UsageWindow]
    /// 구독 플랜 (pro, max 등)
    var plan: String?
    /// 마지막으로 성공적으로 가져온 시각
    var fetchedAt: Date?
    /// 마지막 갱신 시도에서 발생한 오류
    var error: String?

    var fiveHour: UsageWindow? { windows.first { $0.id == "five_hour" } }
    var sevenDay: UsageWindow? { windows.first { $0.id == "seven_day" } }

    /// 가장 중요한 구간 (5시간 세션 우선)
    var primary: UsageWindow? { fiveHour ?? windows.first }

    var planDisplayName: String? {
        guard let plan, !plan.isEmpty else { return nil }
        return plan.prefix(1).uppercased() + plan.dropFirst()
    }

    static let preview = UsageSnapshot(
        windows: [
            UsageWindow(id: "five_hour", utilization: 42, resetsAt: Date().addingTimeInterval(2 * 3600 + 15 * 60)),
            UsageWindow(id: "seven_day", utilization: 18, resetsAt: Date().addingTimeInterval(4 * 86400)),
            UsageWindow(id: "seven_day_opus", utilization: 7, resetsAt: Date().addingTimeInterval(4 * 86400)),
        ],
        plan: "max",
        fetchedAt: Date(),
        error: nil
    )
}

/// 메인 앱과 위젯 확장이 App Group 컨테이너를 통해 스냅샷을 주고받는다.
enum SharedStore {
    static let widgetKind = "ClaudeUsageWidget"

    static var groupIdentifier: String? {
        Bundle.main.object(forInfoDictionaryKey: "AppGroupIdentifier") as? String
    }

    static var fileURL: URL? {
        guard let id = groupIdentifier,
              let container = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: id)
        else { return nil }
        return container.appendingPathComponent("usage.json")
    }

    static func load() -> UsageSnapshot? {
        guard let url = fileURL, let data = try? Data(contentsOf: url) else { return nil }
        return try? decoder.decode(UsageSnapshot.self, from: data)
    }

    static func save(_ snapshot: UsageSnapshot) {
        guard let url = fileURL, let data = try? encoder.encode(snapshot) else { return }
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? data.write(to: url, options: .atomic)
    }

    private static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        return e
    }()

    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()
}
