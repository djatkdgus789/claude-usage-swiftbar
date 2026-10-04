import SwiftUI

extension Color {
    /// Claude 브랜드 톤의 주황색
    static let claude = Color(red: 0.85, green: 0.47, blue: 0.34)

    static func usageTint(_ percent: Double) -> Color {
        switch percent {
        case 90...: return .red
        case 70..<90: return .orange
        default: return .claude
        }
    }
}

/// 가로 막대 게이지
struct UsageBar: View {
    let percent: Double
    var height: CGFloat = 6

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.primary.opacity(0.1))
                Capsule()
                    .fill(Color.usageTint(percent))
                    .frame(width: max(height, geo.size.width * percent / 100))
                    .opacity(percent > 0 ? 1 : 0)
            }
        }
        .frame(height: height)
    }
}

/// 원형 게이지
struct UsageRing: View {
    let percent: Double
    var lineWidth: CGFloat = 8

    var body: some View {
        ZStack {
            Circle().stroke(Color.primary.opacity(0.1), lineWidth: lineWidth)
            Circle()
                .trim(from: 0, to: percent / 100)
                .stroke(Color.usageTint(percent), style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                .rotationEffect(.degrees(-90))
        }
    }
}

/// 한 구간의 제목 / 퍼센트 / 막대 / 초기화 시각
struct UsageRow: View {
    let window: UsageWindow
    let now: Date
    var showsReset = true

    var body: some View {
        let percent = window.utilization(at: now)
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Text(window.title)
                    .font(.caption)
                    .fontWeight(.medium)
                    .lineLimit(1)
                Spacer(minLength: 4)
                Text("\(Int(percent.rounded()))%")
                    .font(.caption.monospacedDigit())
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.usageTint(percent))
            }
            UsageBar(percent: percent)
            if showsReset {
                ResetLabel(date: window.resetsAt, now: now)
            }
        }
    }
}

struct ResetLabel: View {
    let date: Date?
    let now: Date

    var body: some View {
        Group {
            if let date, date > now {
                Text("\(date, style: .relative) 후 초기화")
            } else if date != nil {
                Text("초기화됨")
            } else {
                Text(" ")
            }
        }
        .font(.caption2)
        .foregroundStyle(.secondary)
        .lineLimit(1)
    }
}
