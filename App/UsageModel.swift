import AppKit
import ServiceManagement
import SwiftUI
import WidgetKit

@MainActor
final class UsageModel: ObservableObject {
    /// 자동 갱신 주기 (사용량 API에 부담을 주지 않도록 5분)
    static let refreshInterval: TimeInterval = 5 * 60

    @Published private(set) var snapshot: UsageSnapshot?
    @Published private(set) var isLoading = false
    @Published var launchAtLogin: Bool = SMAppService.mainApp.status == .enabled {
        didSet { updateLoginItem() }
    }

    private var timer: Timer?
    private var wakeObserver: NSObjectProtocol?

    init() {
        snapshot = SharedStore.load()

        timer = Timer.scheduledTimer(withTimeInterval: Self.refreshInterval, repeats: true) { [weak self] _ in
            Task { @MainActor in await self?.refresh() }
        }
        wakeObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didWakeNotification, object: nil, queue: .main
        ) { [weak self] _ in
            Task { @MainActor in await self?.refresh() }
        }
        Task { await refresh() }
    }

    func refresh() async {
        guard !isLoading else { return }
        isLoading = true
        defer { isLoading = false }

        var next = snapshot ?? UsageSnapshot(windows: [])
        do {
            let result = try await UsageFetcher.fetch()
            next.windows = result.windows
            next.plan = result.plan ?? next.plan
            next.fetchedAt = Date()
            next.error = nil
        } catch {
            // 이전 데이터는 유지하고 오류만 표시한다.
            next.error = error.localizedDescription
        }

        snapshot = next
        SharedStore.save(next)
        WidgetCenter.shared.reloadTimelines(ofKind: SharedStore.widgetKind)
    }

    /// 메뉴 막대에 표시할 짧은 텍스트 (예: "42%")
    var menuBarText: String {
        guard let window = snapshot?.primary else { return "–" }
        return "\(Int(window.utilization(at: Date()).rounded()))%"
    }

    private func updateLoginItem() {
        do {
            if launchAtLogin {
                try SMAppService.mainApp.register()
            } else {
                try SMAppService.mainApp.unregister()
            }
        } catch {
            NSLog("Login item update failed: \(error)")
        }
    }
}
