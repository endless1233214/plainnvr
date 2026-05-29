import Foundation

enum PlainNVRClientError: LocalizedError {
    case invalidServerURL
    case invalidResponse
    case server(String)
    case emptyBody

    var errorDescription: String? {
        switch self {
        case .invalidServerURL:
            return "Enter a valid PlainNVR server URL."
        case .invalidResponse:
            return "PlainNVR returned an invalid response."
        case .server(let message):
            return message
        case .emptyBody:
            return "PlainNVR returned an empty response."
        }
    }
}

struct OKResponse: Decodable {
    let ok: Bool
}

final class PlainNVRClient {
    let baseURL: URL
    let serverAddress: String

    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder = JSONEncoder()

    init(serverAddress: String) throws {
        let normalized = try Self.normalizedServerAddress(serverAddress)
        guard let url = URL(string: normalized) else {
            throw PlainNVRClientError.invalidServerURL
        }

        self.baseURL = url
        self.serverAddress = normalized

        let configuration = URLSessionConfiguration.default
        configuration.waitsForConnectivity = false
        configuration.timeoutIntervalForRequest = 6
        configuration.timeoutIntervalForResource = 120
        configuration.httpShouldSetCookies = true
        configuration.httpCookieAcceptPolicy = .always
        configuration.httpCookieStorage = .shared
        self.session = URLSession(configuration: configuration)

        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        self.decoder = decoder
    }

    static func normalizedServerAddress(_ value: String) throws -> String {
        var trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw PlainNVRClientError.invalidServerURL }

        if !trimmed.contains("://") {
            trimmed = "http://\(trimmed)"
        }

        guard var components = URLComponents(string: trimmed),
              let scheme = components.scheme?.lowercased(),
              ["http", "https"].contains(scheme),
              let host = components.host,
              !host.isEmpty
        else {
            throw PlainNVRClientError.invalidServerURL
        }

        if let lastOctet = host.split(separator: ".").last,
           host.split(separator: ".").count == 4,
           lastOctet == "0" || lastOctet == "255" {
            throw PlainNVRClientError.server("\(host) looks like a network or broadcast address. Use the PlainNVR server IP, usually 192.168.1.172.")
        }

        components.scheme = scheme
        while components.path.hasSuffix("/") && components.path != "/" {
            components.path.removeLast()
        }
        if components.path == "/" {
            components.path = ""
        }

        guard let url = components.url else {
            throw PlainNVRClientError.invalidServerURL
        }
        var normalized = url.absoluteString
        while normalized.hasSuffix("/") {
            normalized.removeLast()
        }
        return normalized
    }

    func authState() async throws -> AuthState {
        try await get("/api/auth/state")
    }

    func login(username: String, password: String, setupRequired: Bool) async throws -> AuthResponse {
        let endpoint = setupRequired ? "/api/auth/setup" : "/api/auth/login"
        return try await post(endpoint, body: ["username": username, "password": password])
    }

    func logout() async throws {
        let _: OKResponse = try await post("/api/auth/logout", body: [String: String]())
    }

    func status() async throws -> StatusResponse {
        try await get("/api/status")
    }

    func coverage(cameraID: String) async throws -> RecordingCoverage {
        let path = "/api/coverage?camera_id=\(cameraID.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? cameraID)"
        let response: CoverageResponse = try await get(path)
        return response.coverage
    }

    func segments(cameraID: String, date: String) async throws -> [RecordingSegment] {
        let encodedCamera = cameraID.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? cameraID
        let encodedDate = date.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? date
        let response: SegmentsResponse = try await get("/api/segments?camera_id=\(encodedCamera)&date=\(encodedDate)")
        return response.segments
    }

    func absoluteURL(for serverPath: String) -> URL? {
        URL(string: serverPath, relativeTo: baseURL)?.absoluteURL
    }

    func liveStreamURL(
        camera: Camera,
        streamToken: String,
        reloadID: Int
    ) -> URL? {
        guard let rootURL = absoluteURL(for: "/ha/\(camera.id)/stream.mjpeg"),
              var components = URLComponents(url: rootURL, resolvingAgainstBaseURL: false)
        else {
            return nil
        }

        var items = [
            URLQueryItem(name: "reload", value: String(reloadID))
        ]

        if !streamToken.isEmpty {
            items.append(URLQueryItem(name: "token", value: streamToken))
        }

        components.queryItems = items
        return components.url
    }

    func mediaURL(path: String, streamToken: String) -> URL? {
        urlWithOptionalToken(path: path, streamToken: streamToken)
    }

    func startRecorder(cameraID: String) async throws {
        try await cameraControl(cameraID: cameraID, target: "recorder", action: "start")
    }

    func stopRecorder(cameraID: String) async throws {
        try await cameraControl(cameraID: cameraID, target: "recorder", action: "stop")
    }

    func restartRecorder(cameraID: String) async throws {
        try await cameraControl(cameraID: cameraID, target: "recorder", action: "restart")
    }

    func stopLive(cameraID: String) async throws {
        try await cameraControl(cameraID: cameraID, target: "live", action: "stop")
    }

    func restartLive(cameraID: String) async throws {
        try await cameraControl(cameraID: cameraID, target: "live", action: "restart")
    }

    func downloadSegment(_ segment: RecordingSegment, streamToken: String) async throws -> URL {
        guard let url = mediaURL(path: segment.url, streamToken: streamToken) else {
            throw PlainNVRClientError.invalidServerURL
        }

        let (temporaryURL, response) = try await session.download(from: url)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw PlainNVRClientError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw PlainNVRClientError.server("PlainNVR returned HTTP \(httpResponse.statusCode).")
        }

        let destination = FileManager.default.temporaryDirectory
            .appendingPathComponent(segment.filename, conformingTo: .mpeg4Movie)
        try? FileManager.default.removeItem(at: destination)
        try FileManager.default.moveItem(at: temporaryURL, to: destination)
        return destination
    }

    private func urlWithOptionalToken(path: String, streamToken: String) -> URL? {
        guard let rootURL = absoluteURL(for: path),
              var components = URLComponents(url: rootURL, resolvingAgainstBaseURL: false)
        else {
            return nil
        }

        if !streamToken.isEmpty {
            var items = components.queryItems ?? []
            items.append(URLQueryItem(name: "token", value: streamToken))
            components.queryItems = items
        }
        return components.url
    }

    private func cameraControl(cameraID: String, target: String, action: String) async throws {
        let _: OKResponse = try await post(
            "/api/cameras/\(cameraID)/\(target)/\(action)",
            body: [String: String]()
        )
    }

    private func get<T: Decodable>(_ path: String) async throws -> T {
        try await request(path, method: "GET", bodyData: nil)
    }

    private func post<T: Decodable, Body: Encodable>(_ path: String, body: Body) async throws -> T {
        try await request(path, method: "POST", bodyData: encoder.encode(body))
    }

    private func request<T: Decodable>(_ path: String, method: String, bodyData: Data?) async throws -> T {
        guard let url = absoluteURL(for: path) else {
            throw PlainNVRClientError.invalidServerURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.cachePolicy = .reloadIgnoringLocalCacheData

        if let bodyData {
            request.httpBody = bodyData
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch let error as URLError {
            throw PlainNVRClientError.server(Self.userFacingNetworkMessage(error, serverAddress: serverAddress))
        }
        guard let httpResponse = response as? HTTPURLResponse else {
            throw PlainNVRClientError.invalidResponse
        }

        guard (200..<300).contains(httpResponse.statusCode) else {
            if let serverError = try? decoder.decode(ServerErrorResponse.self, from: data) {
                throw PlainNVRClientError.server(serverError.error)
            }
            throw PlainNVRClientError.server("PlainNVR returned HTTP \(httpResponse.statusCode).")
        }

        guard !data.isEmpty else {
            throw PlainNVRClientError.emptyBody
        }

        return try decoder.decode(T.self, from: data)
    }

    private static func userFacingNetworkMessage(_ error: URLError, serverAddress: String) -> String {
        switch error.code {
        case .timedOut:
            return "PlainNVR did not answer at \(serverAddress). Check the server IP and Wi-Fi, then try again."
        case .cannotConnectToHost, .cannotFindHost, .dnsLookupFailed:
            return "Could not reach PlainNVR at \(serverAddress)."
        case .notConnectedToInternet, .networkConnectionLost:
            return "The network connection dropped while talking to PlainNVR."
        default:
            return error.localizedDescription
        }
    }
}
