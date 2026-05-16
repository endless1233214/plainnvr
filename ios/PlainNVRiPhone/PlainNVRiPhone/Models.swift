import Foundation

struct AuthState: Decodable {
    let authenticated: Bool
    let setupRequired: Bool
    let username: String?
}

struct AuthResponse: Decodable {
    let ok: Bool
    let username: String
}

struct StatusResponse: Decodable {
    let cameras: [Camera]
    let recorders: [String: RecorderState]
    let disk: DiskStatus
    let events: [RecorderEvent]
    let streamToken: String
    let users: [UserAccount]?
    let username: String?
    let now: String?
}

struct Camera: Decodable, Identifiable, Hashable {
    let id: String
    let name: String
    let slug: String?
    let rtspUrl: String?
    let audioUrl: String?
    let enabled: Bool
    let segmentSeconds: Int
    let retentionDays: Int
    let schedule: CameraSchedule?
    let recordAudio: Bool?
    let rtspTransport: String?
    let createdAt: String?
    let updatedAt: String?

    var shortRetention: String {
        "\(retentionDays)d"
    }
}

struct CameraSchedule: Decodable, Hashable {
    let mode: String
    let days: [String: [ScheduleWindow]]
}

struct ScheduleWindow: Decodable, Hashable {
    let start: String
    let end: String
}

struct RecorderState: Decodable, Hashable {
    let running: Bool
    let pid: Int?
    let startedAt: String?
    let lastError: String?
}

struct DiskStatus: Decodable, Hashable {
    let total: Int64
    let used: Int64
    let free: Int64

    var usedFraction: Double {
        guard total > 0 else { return 0 }
        return min(1, max(0, Double(used) / Double(total)))
    }
}

struct RecorderEvent: Decodable, Identifiable, Hashable {
    let id: Int
    let cameraId: String
    let level: String
    let message: String
    let createdAt: String
}

struct UserAccount: Decodable, Identifiable, Hashable {
    let username: String
    let createdAt: String?
    let updatedAt: String?

    var id: String { username }
}

struct CoverageResponse: Decodable {
    let coverage: RecordingCoverage
}

struct RecordingCoverage: Decodable, Hashable {
    let cameraId: String
    let count: Int
    let totalSize: Int64
    let oldest: String?
    let newest: String?
    let dates: [String]
    let retentionDays: Int
}

struct SegmentsResponse: Decodable {
    let segments: [RecordingSegment]
}

struct RecordingSegment: Decodable, Identifiable, Hashable {
    let cameraId: String
    let cameraName: String
    let filename: String
    let start: String
    let approxEnd: String
    let size: Int64
    let url: String

    var id: String {
        "\(cameraId)/\(filename)"
    }
}

struct ServerErrorResponse: Decodable {
    let error: String
}

enum PlainNVRFormat {
    private static let isoWithFractionalSeconds: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    private static let isoWithoutFractionalSeconds: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    private static let localDateTime: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return formatter
    }()

    private static let dayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()

    static func apiDate(_ date: Date) -> String {
        dayFormatter.string(from: date)
    }

    static func date(fromAPI value: String) -> Date? {
        dayFormatter.date(from: value)
    }

    static func displayDate(_ value: String) -> String {
        guard let date = date(fromAPI: value) else { return value }
        return DateFormatter.localizedString(from: date, dateStyle: .medium, timeStyle: .none)
    }

    static func displayDateTime(_ value: String?) -> String {
        guard let value, let date = parseDateTime(value) else { return value ?? "Unknown" }
        return DateFormatter.localizedString(from: date, dateStyle: .short, timeStyle: .short)
    }

    static func displayTime(_ value: String?) -> String {
        guard let value, let date = parseDateTime(value) else { return value ?? "Unknown" }
        return DateFormatter.localizedString(from: date, dateStyle: .none, timeStyle: .short)
    }

    static func parseDateTime(_ value: String) -> Date? {
        isoWithFractionalSeconds.date(from: value)
            ?? isoWithoutFractionalSeconds.date(from: value)
            ?? localDateTime.date(from: value)
    }

    static func bytes(_ value: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: value, countStyle: .file)
    }
}
