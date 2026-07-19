import Foundation
import Photos
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
    private static let defaultServerAddress = "http://192.168.1.172:8787"

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
    @Published var livePlaybackEnabled = true
    @Published var liveStatusMessage: String?
    @Published private(set) var liveReloadID = 0

    private var client: PlainNVRClient?

    init() {
        let savedServerAddress = UserDefaults.standard.string(forKey: Self.serverDefaultsKey)
        if savedServerAddress == nil || savedServerAddress?.contains("192.168.1.0") == true {
            serverAddress = Self.defaultServerAddress
            UserDefaults.standard.set(Self.defaultServerAddress, forKey: Self.serverDefaultsKey)
        } else {
            serverAddress = savedServerAddress ?? Self.defaultServerAddress
        }
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
        do {
            try await refreshCoverage()
            try await refreshSegments()
        } catch {
            errorMessage = userFacingError(error)
        }
    }

    func refreshCoverage() async throws {
        guard let client = client, let camera = selectedCamera else {
            coverage = nil
            return
        }
        coverage = try await client.coverage(cameraID: camera.id)
    }

    func refreshSegments() async throws {
        guard let client = client, let camera = selectedCamera else {
            segments = []
            return
        }
        segments = try await client.segments(cameraID: camera.id, date: selectedDateString)
    }

    func loadRecordingBrowserIfNeeded() async {
        guard coverage == nil, segments.isEmpty, selectedCamera != nil else { return }
        await refreshCoverageAndSegments()
    }

    func selectCamera(_ cameraID: String, loadRecordings: Bool = false) async {
        selectedCameraID = cameraID
        coverage = nil
        segments = []
        bumpLiveReload()
        if loadRecordings {
            await refreshCoverageAndSegments()
        }
    }

    func setLivePlaybackEnabled(_ enabled: Bool) async {
        livePlaybackEnabled = enabled
        if enabled {
            bumpLiveReload()
        } else {
            await stopLiveStream()
        }
    }

    func restartLiveStream() async {
        do {
            if let client, let camera = selectedCamera {
                try await client.restartLive(cameraID: camera.id)
            }
            livePlaybackEnabled = true
            liveStatusMessage = "Restarting live stream..."
            bumpLiveReload()
        } catch {
            errorMessage = userFacingError(error)
        }
    }

    func stopLiveStream() async {
        do {
            if let client, let camera = selectedCamera {
                try await client.stopLive(cameraID: camera.id)
            }
            livePlaybackEnabled = false
            liveStatusMessage = nil
        } catch {
            errorMessage = userFacingError(error)
        }
    }

    func sendPTZ(
        action: String,
        continuous: Bool = false,
        presetToken: String? = nil
    ) async {
        do {
            guard let client, let camera = selectedCamera else {
                throw PlainNVRClientError.invalidServerURL
            }
            guard camera.supportsPTZ else {
                throw PlainNVRClientError.server("PTZ is not enabled for this camera.")
            }
            let durationMs = ["stop", "home"].contains(action) ? 0 : 300
            try await client.sendPTZ(
                cameraID: camera.id,
                action: action,
                speed: camera.ptzSpeed ?? 0.55,
                durationMs: durationMs,
                continuous: continuous,
                presetToken: presetToken
            )
        } catch {
            errorMessage = userFacingError(error)
        }
    }

    func beginPTZ(action: String) async {
        await sendPTZ(action: action, continuous: true)
    }

    func stopPTZ() async {
        await sendPTZ(action: "stop")
    }

    func goToPreset(_ preset: PTZPreset) async {
        await sendPTZ(action: "preset", presetToken: preset.token)
    }

    func diagnoseLiveStream() async {
        liveStatusMessage = "Using go2rtc HLS from PlainNVR."
    }

    func updateLivePlayerStatus(_ message: String?) {
        liveStatusMessage = message
    }

    func updateLivePlayerFailure(_ message: String) {
        liveStatusMessage = "\(message)\nUsing go2rtc HLS from PlainNVR."
    }

    func setRecorderRunning(_ running: Bool, camera: Camera) async {
        do {
            guard let client else { throw PlainNVRClientError.invalidServerURL }
            if running {
                try await client.startRecorder(cameraID: camera.id)
            } else {
                try await client.stopRecorder(cameraID: camera.id)
            }
            try await refreshStatus(using: client)
        } catch {
            errorMessage = userFacingError(error)
        }
    }

    func restartRecorder(camera: Camera) async {
        do {
            guard let client else { throw PlainNVRClientError.invalidServerURL }
            try await client.restartRecorder(cameraID: camera.id)
            try await refreshStatus(using: client)
        } catch {
            errorMessage = userFacingError(error)
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
            activeSegment = nil
            livePlaybackEnabled = true
            password = ""
            connectionState = .signedOut
        }
    }

    func liveURL(for camera: Camera) -> URL? {
        guard livePlaybackEnabled else { return nil }
        return client?.liveStreamURL(
            camera: camera,
            streamToken: status?.streamToken ?? "",
            reloadID: liveReloadID
        )
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

    func saveSegmentToPhotos(_ segment: RecordingSegment) async throws {
        let fileURL = try await downloadSegment(segment)
        try await PhotoLibrarySaver.saveVideo(fileURL)
    }

    private func configuredClient() throws -> PlainNVRClient {
        let client = try PlainNVRClient(serverAddress: serverAddress)
        self.client = client
        serverAddress = client.serverAddress
        UserDefaults.standard.set(client.serverAddress, forKey: Self.serverDefaultsKey)
        return client
    }

    private func bumpLiveReload() {
        liveReloadID &+= 1
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
}

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
