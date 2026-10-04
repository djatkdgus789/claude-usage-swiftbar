import AppKit
import SwiftUI
import XCTest

/// 위젯 레이아웃을 PNG로 렌더링한다. CI에서 결과 이미지를 확인하는 용도.
/// 저장 위치: 환경 변수 SNAPSHOT_DIR (xcodebuild 에는 TEST_RUNNER_SNAPSHOT_DIR 로 전달)
@MainActor
final class SnapshotTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_791_080_000)

    private var sample: UsageSnapshot {
        UsageSnapshot(
            windows: [
                UsageWindow(id: "five_hour", utilization: 42, resetsAt: now.addingTimeInterval(2 * 3600 + 15 * 60)),
                UsageWindow(id: "seven_day", utilization: 76, resetsAt: now.addingTimeInterval(3 * 86400)),
                UsageWindow(id: "seven_day_opus", utilization: 93, resetsAt: now.addingTimeInterval(3 * 86400)),
            ],
            plan: "max",
            fetchedAt: now,
            error: nil
        )
    }

    func testRenderWidgets() throws {
        var errored = sample
        errored.error = "토큰이 만료되었습니다."

        let cases: [(String, CGSize, AnyView)] = [
            ("small", CGSize(width: 170, height: 170), AnyView(SmallView(snapshot: sample, now: now))),
            ("medium", CGSize(width: 364, height: 170), AnyView(MediumView(snapshot: sample, now: now))),
            ("large", CGSize(width: 364, height: 382), AnyView(LargeView(snapshot: sample, now: now))),
            ("medium-error", CGSize(width: 364, height: 170), AnyView(MediumView(snapshot: errored, now: now))),
            ("small-empty", CGSize(width: 170, height: 170), AnyView(EmptyStateView(error: nil))),
            ("menu-rows", CGSize(width: 300, height: 190), AnyView(
                VStack(alignment: .leading, spacing: 12) {
                    ForEach(sample.windows) { UsageRow(window: $0, now: now) }
                }
            )),
        ]

        for (name, size, view) in cases {
            for dark in [false, true] {
                let content = view
                    .padding(16)
                    .frame(width: size.width, height: size.height, alignment: .topLeading)
                    .background(dark ? Color(white: 0.16) : Color.white)
                    .environment(\.colorScheme, dark ? .dark : .light)
                    .environment(\.locale, Locale(identifier: "ko_KR"))
                try write(content, name: "\(name)-\(dark ? "dark" : "light")")
            }
        }
    }

    private func write(_ view: some View, name: String) throws {
        let renderer = ImageRenderer(content: view)
        renderer.scale = 2
        let image = try XCTUnwrap(renderer.cgImage, "render failed: \(name)")
        let png = try XCTUnwrap(NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:]))

        let dir = ProcessInfo.processInfo.environment["SNAPSHOT_DIR"].map { URL(fileURLWithPath: $0) }
            ?? FileManager.default.temporaryDirectory.appendingPathComponent("ClaudeUsageSnapshots")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try png.write(to: dir.appendingPathComponent("\(name).png"))

        let attachment = XCTAttachment(data: png, uniformTypeIdentifier: "public.png")
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
