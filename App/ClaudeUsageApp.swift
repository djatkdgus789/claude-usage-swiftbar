import SwiftUI

@main
struct ClaudeUsageApp: App {
    @StateObject private var model = UsageModel()

    var body: some Scene {
        MenuBarExtra {
            MenuContentView()
                .environmentObject(model)
        } label: {
            HStack(spacing: 3) {
                Image(systemName: "gauge.with.dots.needle.50percent")
                Text(model.menuBarText)
            }
        }
        .menuBarExtraStyle(.window)
    }
}

struct MenuContentView: View {
    @EnvironmentObject private var model: UsageModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header

            if let snapshot = model.snapshot, !snapshot.windows.isEmpty {
                TimelineView(.periodic(from: .now, by: 30)) { context in
                    VStack(alignment: .leading, spacing: 12) {
                        ForEach(snapshot.windows) { window in
                            UsageRow(window: window, now: context.date)
                        }
                    }
                }
            } else if model.snapshot?.error == nil {
                HStack {
                    ProgressView().controlSize(.small)
                    Text("불러오는 중…").foregroundStyle(.secondary)
                }
            }

            if let error = model.snapshot?.error {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Divider()

            HStack {
                if let fetchedAt = model.snapshot?.fetchedAt {
                    Text("업데이트: \(fetchedAt, style: .relative) 전")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button {
                    Task { await model.refresh() }
                } label: {
                    if model.isLoading {
                        ProgressView().controlSize(.small)
                    } else {
                        Image(systemName: "arrow.clockwise")
                    }
                }
                .buttonStyle(.borderless)
                .disabled(model.isLoading)
                .help("지금 새로고침")
            }

            Toggle("로그인 시 자동 실행", isOn: $model.launchAtLogin)
                .toggleStyle(.checkbox)
                .font(.callout)

            HStack {
                Link("claude.ai 사용량 보기", destination: URL(string: "https://claude.ai/settings/usage")!)
                    .font(.callout)
                Spacer()
                Button("종료") { NSApp.terminate(nil) }
                    .keyboardShortcut("q")
            }
        }
        .padding(16)
        .frame(width: 300)
    }

    private var header: some View {
        HStack {
            Image(systemName: "sparkle")
                .foregroundStyle(Color.claude)
            Text("Claude 사용량")
                .font(.headline)
            Spacer()
            if let plan = model.snapshot?.planDisplayName {
                Text(plan)
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(Capsule().fill(Color.claude.opacity(0.15)))
                    .foregroundStyle(Color.claude)
            }
        }
    }
}
