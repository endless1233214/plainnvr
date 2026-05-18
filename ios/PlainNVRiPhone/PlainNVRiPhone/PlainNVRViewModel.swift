import Foundation
#if os(iOS) && !targetEnvironment(macCatalyst)
import Photos
#endif
import SwiftUI

enum PlainNVRConnectionState: Equatable {
    case checking
    case signedOut
    case setupRequired
    case signedIn
}

@MainActor
final class PlainNVRViewModel: ObservableObject {
    private static let serverDefaultsKey = "PlainNVRServerAddress"
    private static let defaultServerAddress = "http://192.168.1.0:8787"

    @Published var serverAddress: String
    @Published var username = ""
    @Published var password = ""
    @Published var isBusy = false
    @Published var errorMessage: String?
    @Published var connectionState: PlainNVRConnectionState = .checking
    @Published private(set) var authState: AuthState?
    @Published private(set) var status: StatusResponse?
    @Published private(set) var coverage: RecordingCoverage?
    @Published private(set) var segments: [RecordingSegment] = []
    @Published var selectedCameraID: String?
    @Published var selectedRecordingDate = Date()
    @Published var activeSegment: RecordingSegment?

    private var client: PlainNVRClient?
    private var loadedRecordingKey: String?
    private var loadingRecordingKey: String?

    init() {
        serverAddress = UserDefaults.standard.string(forKey: Self.serverDefaultsKey) ?? Self.defaultServerAddress
    }

    var cameras: [Camera] {
        status?.cameras ?? []
    }

    var selectedCamera: Camera? {
        guard let selectedCameraID else { return cameras.first }
        return cameras.first { $0.id == selectedCameraID } ?? cameras.first
    }

    var currentUsername: String {
        status?.username ?? authState?.username ?? username
    }

    var setupRequired: Bool {
        authState?.setupRequired == true || connectionState == .setupRequired
    }

    var selectedDateString: String {
        PlainNVRFormat.apiDate(selectedRecordingDate)
    }

    func bootstrap() async {
        await runBusy {
            do {
                let client = try configuredClient()
                let state = try await client.authState()
                authState = state
                username = state.username ?? username
                connectionState = state.authenticated ? .signedIn : (state.setupRequired ? .setupRequired : .signedOut)

                if state.authenticated {
                    try await refreshStatus(using: client)
                }
            } catch {
                connectionState = .signedOut
                errorMessage = userFacingError(error)
            }
        }
    }

    func connectOrSignIn() async {
        await runBusy {
            do {
                let client = try configuredClient()
                let state = try await client.authState()
                authState = state

                if state.authenticated {
                    connectionState = .signedIn
                    try await refreshStatus(using: client)
                    return
                }

                let trimmedUsername = username.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !trimmedUsername.isEmpty, !password.isEmpty else {
                    connectionState = state.setupRequired ? .setupRequired : .signedOut
                    errorMessage = "Enter your PlainNVR username and password."
                    return
                }

                let response = try await client.login(
                    username: trimmedUsername,
                    password: password,
                    setupRequired: state.setupRequired
                )
                password = ""
                username = response.username
                authState = AuthState(authenticated: true, setupRequired: false, username: response.username)
                connectionState = .signedIn
                try await refreshStatus(using: client)
            } catch {
                connectionState = .signedOut
                errorMessage = userFacingError(error)
            }
        }
    }

    func refreshAll(includeRecordings: Bool = false) async {
        await runBusy {
            do {
                let client = try configuredClient()
                try await refreshStatus(using: client)
                if includeRecordings {
                    await refreshCoverageAndSegments()
                }
            } catch {
                errorMessage = userFacingError(error)
            }
        }
    }

    func refreshCoverageAndSegments() async {
        guard let client, let camera = selectedCamera else {
            coverage = nil
            segments = []
            loadedRecordingKey = nil
            return
        }

        let dateString = selectedDateString
        let loadKey = recordingLoadKey(cameraID: camera.id, dateString: dateString)
        guard loadingRecordingKey != loadKey else { return }
        loadingRecordingKey = loadKey
        defer {
            if loadingRecordingKey == loadKey {
                loadingRecordingKey = nil
            }
        }

        do {
            let coverageResponse = try await client.coverage(cameraID: camera.id)
            let segmentsResponse = try await client.segments(cameraID: camera.id, date: dateString)
            guard recordingLoadKey == loadKey else { return }
            coverage = coverageResponse
            segments = segmentsResponse
            loadedRecordingKey = loadKey
        } catch {
            if recordingLoadKey == loadKey {
                errorMessage = userFacingError(error)
            }
        }
    }

    func loadRecordingBrowserIfNeeded() async {
        guard loadedRecordingKey != recordingLoadKey else { return }
        await refreshCoverageAndSegments()
    }

    func selectCamera(_ cameraID: String, refreshRecordings: Bool = true) async {
        selectedCameraID = cameraID
        loadedRecordingKey = nil
        coverage = nil
        segments = []
        if refreshRecordings {
            await refreshCoverageAndSegments()
        }
    }

    func logout() async {
        await runBusy {
            do {
                if let client {
                    try await client.logout()
                }
            } catch {
                errorMessage = userFacingError(error)
            }

            authState = nil
            status = nil
            coverage = nil
            segments = []
            loadedRecordingKey = nil
            activeSegment = nil
            password = ""
            connectionState = .signedOut
        }
    }

    func liveURL(for camera: Camera) -> URL? {
        client?.liveHLSURL(camera: camera, streamToken: status?.streamToken ?? "")
    }

    func playbackURL(for segment: RecordingSegment) -> URL? {
        client?.mediaURL(path: segment.url, streamToken: status?.streamToken ?? "")
    }

    func downloadSegment(_ segment: RecordingSegment) async throws -> URL {
        guard let client else {
            throw PlainNVRClientError.invalidServerURL
        }
        return try await client.downloadSegment(segment, streamToken: status?.streamToken ?? "")
    }

    #if os(iOS) && !targetEnvironment(macCatalyst)
    func saveSegmentToPhotos(_ segment: RecordingSegment) async throws {
        let fileURL = try await downloadSegment(segment)
        try await PhotoLibrarySaver.saveVideo(fileURL)
    }
    #endif

    #if targetEnvironment(macCatalyst) || os(macOS)
    func saveSegmentToDownloads(_ segment: RecordingSegment) async throws -> URL {
        let fileURL = try await downloadSegment(segment)
        guard let downloadsDirectory = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first else {
            throw PlainNVRClientError.server("Downloads folder is unavailable.")
        }

        let destination = uniqueDestination(
            in: downloadsDirectory,
            filename: segment.filename
        )
        try FileManager.default.copyItem(at: fileURL, to: destination)
        return destination
    }
    #endif

    private func configuredClient() throws -> PlainNVRClient {
        let client = try PlainNVRClient(serverAddress: serverAddress)
        self.client = client
        serverAddress = client.serverAddress
        UserDefaults.standard.set(client.serverAddress, forKey: Self.serverDefaultsKey)
        return client
    }

    private func refreshStatus(using client: PlainNVRClient) async throws {
        let response = try await client.status()
        status = response

        if let selectedCameraID, response.cameras.contains(where: { $0.id == selectedCameraID }) {
            return
        }
        selectedCameraID = response.cameras.first?.id
    }

    private func runBusy(_ operation: () async -> Void) async {
        guard !isBusy else { return }
        isBusy = true
        errorMessage = nil
        await operation()
        isBusy = false
    }

    private func userFacingError(_ error: Error) -> String {
        if let localized = error as? LocalizedError, let description = localized.errorDescription {
            return description
        }
        return error.localizedDescription
    }

    private var recordingLoadKey: String? {
        guard let camera = selectedCamera else { return nil }
        return recordingLoadKey(cameraID: camera.id, dateString: selectedDateString)
    }

    private func recordingLoadKey(cameraID: String, dateString: String) -> String {
        "\(cameraID)|\(dateString)"
    }

    #if targetEnvironment(macCatalyst) || os(macOS)
    private func uniqueDestination(in directory: URL, filename: String) -> URL {
        let original = directory.appendingPathComponent(filename, conformingTo: .mpeg4Movie)
        guard FileManager.default.fileExists(atPath: original.path) else {
            return original
        }

        let base = original.deletingPathExtension().lastPathComponent
        let pathExtension = original.pathExtension
        for index in 1...999 {
            let candidate = directory
                .appendingPathComponent("\(base)-\(index)")
                .appendingPathExtension(pathExtension)
            if !FileManager.default.fileExists(atPath: candidate.path) {
                return candidate
            }
        }
        return directory.appendingPathComponent("\(base)-\(UUID().uuidString)").appendingPathExtension(pathExtension)
    }
    #endif
}

#if os(iOS) && !targetEnvironment(macCatalyst)
enum PhotoLibrarySaver {
    static func saveVideo(_ fileURL: URL) async throws {
        let status = await PHPhotoLibrary.requestAuthorization(for: .addOnly)
        guard status == .authorized || status == .limited else {
            throw PlainNVRClientError.server("Photos access is needed to save video.")
        }

        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            PHPhotoLibrary.shared().performChanges {
                PHAssetChangeRequest.creationRequestForAssetFromVideo(atFileURL: fileURL)
            } completionHandler: { success, error in
                if let error {
                    continuation.resume(throwing: error)
                } else if success {
                    continuation.resume()
                } else {
                    continuation.resume(throwing: PlainNVRClientError.server("Photos did not save the video."))
                }
            }
        }
    }
}
#endif
