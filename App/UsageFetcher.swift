import Foundation

enum UsageError: LocalizedError {
    case noCredentials
    case unauthorized
    case rateLimited(retryAfter: TimeInterval?)
    case http(Int, String)
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .noCredentials:
            return "Claude Code 로그인 정보를 찾을 수 없습니다. 터미널에서 `claude`를 실행해 로그인하세요."
        case .unauthorized:
            return "토큰이 만료되었습니다. 터미널에서 `claude`를 한 번 실행하면 갱신됩니다."
        case .rateLimited:
            return "요청이 너무 잦아 잠시 후 다시 시도합니다."
        case let .http(code, body):
            return "HTTP \(code): \(body.prefix(120))"
        case .invalidResponse:
            return "사용량 응답을 해석할 수 없습니다."
        }
    }
}

/// Claude Code의 OAuth 토큰으로 구독 사용량(5시간/주간 한도)을 조회한다.
/// Claude Code의 `/usage` 명령과 같은 엔드포인트를 사용한다.
enum UsageFetcher {
    struct Result {
        let windows: [UsageWindow]
        let plan: String?
    }

    struct Credentials {
        let accessToken: String
        let subscriptionType: String?
    }

    static let endpoint = URL(string: "https://api.anthropic.com/api/oauth/usage")!
    static let keychainService = "Claude Code-credentials"

    static func fetch() async throws -> Result {
        let credentials = try loadCredentials()

        var request = URLRequest(url: endpoint)
        request.timeoutInterval = 20
        request.setValue("Bearer \(credentials.accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("oauth-2025-04-20", forHTTPHeaderField: "anthropic-beta")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("claude-usage-widget/1.0", forHTTPHeaderField: "User-Agent")

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw UsageError.invalidResponse }
        switch http.statusCode {
        case 200: break
        case 401, 403: throw UsageError.unauthorized
        case 429:
            let retryAfter = http.value(forHTTPHeaderField: "Retry-After").flatMap(TimeInterval.init)
            throw UsageError.rateLimited(retryAfter: retryAfter)
        default: throw UsageError.http(http.statusCode, String(decoding: data, as: UTF8.self))
        }

        return Result(windows: try parseWindows(data), plan: credentials.subscriptionType)
    }

    // MARK: - 응답 파싱

    /// 응답 예시:
    /// `{"five_hour":{"utilization":42.0,"resets_at":"2026-10-04T05:00:00.123+00:00"},"seven_day":{...},"seven_day_opus":null}`
    /// `utilization`을 가진 항목 중 표시 대상(`UsageWindow.isDisplayable`)만 수집한다.
    static func parseWindows(_ data: Data) throws -> [UsageWindow] {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw UsageError.invalidResponse
        }
        var windows: [UsageWindow] = []
        for (key, value) in root where UsageWindow.isDisplayable(key) {
            guard let dict = value as? [String: Any],
                  let utilization = (dict["utilization"] as? NSNumber)?.doubleValue
            else { continue }
            if let enabled = dict["is_enabled"] as? Bool, !enabled { continue }
            let resetsAt = (dict["resets_at"] as? String).flatMap(parseDate)
            windows.append(UsageWindow(id: key, utilization: utilization, resetsAt: resetsAt))
        }
        return windows.sorted {
            let (a, b) = (UsageWindow.sortKey($0.id), UsageWindow.sortKey($1.id))
            return a == b ? $0.id < $1.id : a < b
        }
    }

    static func parseDate(_ string: String) -> Date? {
        let withFraction = ISO8601DateFormatter()
        withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = withFraction.date(from: string) { return date }

        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        if let date = plain.date(from: string) { return date }

        // 마이크로초(6자리) 등 포맷터가 처리하지 못하는 소수점 이하를 제거하고 재시도
        let stripped = string.replacingOccurrences(of: #"\.\d+"#, with: "", options: .regularExpression)
        return plain.date(from: stripped)
    }

    // MARK: - 자격 증명

    static func loadCredentials() throws -> Credentials {
        if let json = readKeychain(), let credentials = parseCredentials(json) {
            return credentials
        }
        for url in credentialFileCandidates() {
            if let json = try? String(contentsOf: url, encoding: .utf8),
               let credentials = parseCredentials(json) {
                return credentials
            }
        }
        throw UsageError.noCredentials
    }

    static func parseCredentials(_ json: String) -> Credentials? {
        guard let data = json.data(using: .utf8),
              let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let oauth = root["claudeAiOauth"] as? [String: Any],
              let token = oauth["accessToken"] as? String, !token.isEmpty
        else { return nil }
        return Credentials(accessToken: token, subscriptionType: oauth["subscriptionType"] as? String)
    }

    /// Claude Code가 macOS 키체인에 저장한 자격 증명을 읽는다.
    /// Claude Code 자체가 `security` 도구로 항목을 만들기 때문에 같은 도구로 읽으면
    /// 별도의 키체인 접근 허용 창이 뜨지 않는 경우가 대부분이다.
    static func readKeychain() -> String? {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/security")
        process.arguments = ["find-generic-password", "-s", keychainService, "-w"]
        let output = Pipe()
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        do { try process.run() } catch { return nil }
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else { return nil }
        let value = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }

    static func credentialFileCandidates() -> [URL] {
        var dirs: [URL] = []
        if let custom = ProcessInfo.processInfo.environment["CLAUDE_CONFIG_DIR"], !custom.isEmpty {
            dirs.append(URL(fileURLWithPath: (custom as NSString).expandingTildeInPath))
        }
        dirs.append(FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".claude"))
        return dirs.map { $0.appendingPathComponent(".credentials.json") }
    }
}
