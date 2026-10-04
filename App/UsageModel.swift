import AppKit
import ServiceManagement
import SwiftUI
import WidgetKit

@MainActor
final class UsageModel: ObservableObject {
    /// 자동 갱신 주기 (1분)
    static let refreshInterval: TimeInterval = 60
    /// 429(요청 한도 초과) 응답에 Retry-After 헤더가 없을 때 쉬는 시간
    static let defaultBackoff: TimeInterval = 5 * 60

    @Published private(set) var snapshot: UsageSnapshot?
    @Published private(set) var isLoading = false
    @Published var launchAtLogin: Bool = SMAppService.mainApp.status == .enabled {
        didSet { updateLoginItem() }
    }

    private var timer: Timer?
    /// 이 시각 전에는 자동 갱신을 건너뛴다 (429 백오프)
    private var nextAllowedFetch = Date.distantPast
    private var wakeObserver: NSObjectProtocol?

    init() {
        snapshot = SharedStore.load()

        timer = Timer.scheduledTimer(withTimeInterval: Self.refreshInterval, repeats: true) { [weak self] _ in
            Task { @MainActor in await self?.refresh(force: false) }
        }
        timer?.tolerance = 5
        wakeObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didWakeNotification, object: nil, queue: .main
        ) { [weak self] _ in
            Task { @MainActor in await self?.refresh(force: false) }
        }
        Task { await refresh(force: false) }
    }

    /// - Parameter force: 사용자가 직접 누른 새로고침이면 true (백오프 무시)
    func refresh(force: Bool = true) async {
        guard !isLoading else { return }
        guard force || Date() >= nextAllowedFetch else { return }
        isLoading = true
        defer { isLoading = false }

        let previous = snapshot
        var next = snapshot ?? UsageSnapshot(windows: [])
        do {
            let result = try await UsageFetcher.fetch()
            next.windows = result.windows
            next.plan = result.plan ?? next.plan
            next.fetchedAt = Date()
            next.error = nil
            nextAllowedFetch = .distantPast
        } catch UsageError.rateLimited(let retryAfter) {
            nextAllowedFetch = Date().addingTimeInterval(retryAfter ?? Self.defaultBackoff)
            next.error = UsageError.rateLimited(retryAfter: retryAfter).localizedDescription
        } catch {
            // 이전 데이터는 유지하고 오류만 표시한다.
            next.error = error.localizedDescription
        }

        snapshot = next
        SharedStore.save(next)
        // macOS는 위젯 새로고침 횟수를 제한하므로 표시 내용이 바뀐 경우에만 다시 그리게 한다.
        if previous?.windows != next.windows || previous?.error != next.error || previous?.plan != next.plan {
            WidgetCenter.shared.reloadTimelines(ofKind: SharedStore.widgetKind)
        }
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
