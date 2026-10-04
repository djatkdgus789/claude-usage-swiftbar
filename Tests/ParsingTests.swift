import XCTest

final class ParsingTests: XCTestCase {
    func testParsesUsageResponse() throws {
        let json = """
        {
          "five_hour": {"utilization": 42.0, "resets_at": "2026-10-04T05:00:00.123456+00:00"},
          "seven_day": {"utilization": 18, "resets_at": "2026-10-08T00:00:00+00:00"},
          "seven_day_oauth_apps": null,
          "seven_day_opus": {"utilization": 7.5, "resets_at": null},
          "seven_day_new_limit": {"utilization": 3, "resets_at": "2026-10-08T00:00:00Z"},
          "iguana_necktie": {"utilization": 5, "resets_at": null},
          "extra_usage": {"is_enabled": false, "utilization": null}
        }
        """
        let windows = try UsageFetcher.parseWindows(Data(json.utf8))

        XCTAssertEqual(windows.map(\.id), ["five_hour", "seven_day", "seven_day_opus", "seven_day_new_limit"])
        XCTAssertEqual(windows[0].utilization, 42)
        XCTAssertEqual(windows[0].resetsAt, Date(timeIntervalSince1970: 1_791_090_000.123), accuracy: 0.01)
        XCTAssertEqual(windows[1].resetsAt, Date(timeIntervalSince1970: 1_791_417_600))
        XCTAssertNil(windows[2].resetsAt)
        XCTAssertEqual(windows[3].title, "Seven Day New Limit")
    }

    func testExtraUsageEnabledIsIncluded() throws {
        let json = #"{"extra_usage": {"is_enabled": true, "utilization": 12.5, "monthly_limit": 5000}}"#
        let windows = try UsageFetcher.parseWindows(Data(json.utf8))
        XCTAssertEqual(windows.map(\.id), ["extra_usage"])
        XCTAssertNil(windows[0].resetsAt)
    }

    func testInvalidResponseThrows() {
        XCTAssertThrowsError(try UsageFetcher.parseWindows(Data("[]".utf8)))
        XCTAssertThrowsError(try UsageFetcher.parseWindows(Data("not json".utf8)))
    }

    func testParseDateVariants() {
        let expected = Date(timeIntervalSince1970: 1_791_090_000)
        for string in [
            "2026-10-04T05:00:00Z",
            "2026-10-04T05:00:00+00:00",
            "2026-10-04T14:00:00+09:00",
            "2026-10-04T05:00:00.000Z",
            "2026-10-04T05:00:00.000000+00:00",
        ] {
            let date = UsageFetcher.parseDate(string)
            XCTAssertNotNil(date, string)
            XCTAssertEqual(date!.timeIntervalSince1970, expected.timeIntervalSince1970, accuracy: 0.01, string)
        }
        XCTAssertNil(UsageFetcher.parseDate("garbage"))
    }

    func testParseCredentials() {
        let json = #"{"claudeAiOauth":{"accessToken":"sk-ant-oat01-abc","refreshToken":"r","expiresAt":1791090000000,"scopes":["user:inference"],"subscriptionType":"max"}}"#
        let credentials = UsageFetcher.parseCredentials(json)
        XCTAssertEqual(credentials?.accessToken, "sk-ant-oat01-abc")
        XCTAssertEqual(credentials?.subscriptionType, "max")

        XCTAssertNil(UsageFetcher.parseCredentials("{}"))
        XCTAssertNil(UsageFetcher.parseCredentials(#"{"claudeAiOauth":{"accessToken":""}}"#))
        XCTAssertNil(UsageFetcher.parseCredentials("not json"))
    }

    func testUtilizationResetsToZeroAfterResetTime() {
        let reset = Date(timeIntervalSince1970: 1000)
        let window = UsageWindow(id: "five_hour", utilization: 80, resetsAt: reset)
        XCTAssertEqual(window.utilization(at: reset.addingTimeInterval(-1)), 80)
        XCTAssertEqual(window.utilization(at: reset), 0)
        XCTAssertEqual(UsageWindow(id: "x", utilization: 150, resetsAt: nil).utilization(at: reset), 100)
    }

    func testSnapshotRoundTripsThroughJSON() throws {
        let snapshot = UsageSnapshot.preview
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let decoded = try decoder.decode(UsageSnapshot.self, from: encoder.encode(snapshot))
        XCTAssertEqual(decoded.windows.map(\.id), snapshot.windows.map(\.id))
        XCTAssertEqual(decoded.planDisplayName, "Max")
        XCTAssertEqual(decoded.primary?.id, "five_hour")
    }
}

private func XCTAssertEqual(_ a: Date?, _ b: Date, accuracy: TimeInterval, file: StaticString = #filePath, line: UInt = #line) {
    guard let a else { return XCTFail("date is nil", file: file, line: line) }
    XCTAssertEqual(a.timeIntervalSince1970, b.timeIntervalSince1970, accuracy: accuracy, file: file, line: line)
}
