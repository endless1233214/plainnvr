import Foundation
import SwiftUI
@preconcurrency import WebRTC
#if os(iOS)
import AVFAudio
import UIKit
#else
import AppKit
#endif

/// A receive-only camera session. Media never passes through a web view.
@MainActor
final class NativeLiveSession: NSObject, ObservableObject {
    @Published private(set) var videoTrack: RTCVideoTrack?
    @Published private(set) var status = "Connecting live video…"
    @Published private(set) var failure: String?
    @Published private(set) var hasVideo = false

    private static let factory: RTCPeerConnectionFactory = {
        RTCInitializeSSL()
        #if os(iOS)
        return RTCPeerConnectionFactory(
            encoderFactory: RTCDefaultVideoEncoderFactory(),
            decoderFactory: RTCDefaultVideoDecoderFactory(),
            audioDevice: PlaybackAudioDevice()
        )
        #else
        return RTCPeerConnectionFactory(
            encoderFactory: RTCDefaultVideoEncoderFactory(),
            decoderFactory: RTCDefaultVideoDecoderFactory()
        )
        #endif
    }()

    private var peer: RTCPeerConnection?
    private var socket: URLSessionWebSocketTask?
    private var connectionSession: URLSession?
    private var receiveTask: Task<Void, Never>?
    private var retryTask: Task<Void, Never>?
    private var retryURL: URL?
    private var retryRelayPort: Int?
    private var watchdog: Timer?
    private var generation = UUID()
    private var openedAt = Date()
    private var lastFrameAt = Date()
    private var frameMonitor: LiveFrameMonitor?
    private var audioTrack: RTCAudioTrack?
    private var localCandidates: [RTCIceCandidate] = []
    private var remoteCandidates: [RTCIceCandidate] = []
    private var offerSent = false
    private var muted = false
    private var volume: Float = 0.85
    private var serverCandidates: [RTCIceCandidate] = []

    func start(hlsURL: URL, isMuted: Bool, volume: Float, relayPort: Int? = nil) {
        stop()
        retryURL = hlsURL
        retryRelayPort = relayPort
        self.muted = isMuted
        self.volume = volume
        failure = nil
        status = "Connecting live video…"
        openedAt = Date()
        lastFrameAt = openedAt
        let currentGeneration = generation
        if let relayPort, (1...65535).contains(relayPort), let host = hlsURL.host {
            // Docker/TrueNAS can advertise only a container address. Also try
            // the configured media port on the same server the user signed in to.
            serverCandidates = [
                RTCIceCandidate(sdp: "candidate:plainnvr-udp 1 udp 2130706431 \(host) \(relayPort) typ host", sdpMLineIndex: 0, sdpMid: "0"),
                RTCIceCandidate(sdp: "candidate:plainnvr-tcp 1 tcp 2130706430 \(host) \(relayPort) typ host tcptype passive", sdpMLineIndex: 0, sdpMid: "0"),
            ]
        }
        let parts = hlsURL.pathComponents
        guard let liveIndex = parts.firstIndex(of: "live"), parts.count > liveIndex + 1,
              var components = URLComponents(url: hlsURL, resolvingAgainstBaseURL: false) else {
            fail("Live connection URL is invalid.")
            return
        }
        components.scheme = hlsURL.scheme == "https" ? "wss" : "ws"
        components.path = "/go2rtc/api/ws"
        components.queryItems = [URLQueryItem(name: "src", value: "plainnvr_" + parts[liveIndex + 1])]
        guard let socketURL = components.url else { return }

        let config = RTCConfiguration()
        config.sdpSemantics = .unifiedPlan
        config.continualGatheringPolicy = .gatherContinually
        // LAN/VPN playback does not require contacting a public STUN service.
        config.iceServers = []
        let constraints = RTCMediaConstraints(mandatoryConstraints: nil, optionalConstraints: nil)
        guard let connection = Self.factory.peerConnection(with: config, constraints: constraints, delegate: self) else {
            fail("The native video decoder could not start.")
            return
        }
        peer = connection
        let direction = RTCRtpTransceiverInit()
        direction.direction = .recvOnly
        connection.addTransceiver(of: .video, init: direction)
        connection.addTransceiver(of: .audio, init: direction)

        var request = URLRequest(url: socketURL)
        request.timeoutInterval = 10
        // Use only the cookies applicable to this server; never copy credentials
        // to a different host or place the stream token in diagnostic output.
        let cookies = HTTPCookieStorage.shared.cookies(for: hlsURL) ?? []
        for (key, value) in HTTPCookie.requestHeaderFields(with: cookies) {
            request.setValue(value, forHTTPHeaderField: key)
        }
        diagnostic("signaling-cookies-\(cookies.count)")
        let session = URLSession(configuration: .default)
        connectionSession = session
        let ws = session.webSocketTask(with: request)
        socket = ws
        ws.resume()
        receiveTask = Task { [weak self] in
            do {
                while !Task.isCancelled {
                    let message = try await ws.receive()
                    guard let self, self.generation == currentGeneration else { return }
                    let data: Data
                    switch message {
                    case .string(let text): data = Data(text.utf8)
                    case .data(let bytes): data = bytes
                    @unknown default: continue
                    }
                    self.diagnostic("message-\(data.count)")
                    guard data.first == 123 else {
                        self.diagnostic("message-not-json")
                        continue
                    }
                    guard let response = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                          let type = response["type"] as? String,
                          let value = response["value"] as? String else {
                        self.diagnostic("message-json-fail")
                        continue
                    }
                    self.diagnostic("received-\(type)")
                    self.handle(type: type, value: value, generation: currentGeneration)
                }
            } catch {
                guard let self, self.generation == currentGeneration, !Task.isCancelled else { return }
                self.diagnostic("signaling-error-\((error as NSError).domain)-\((error as NSError).code)")
                self.fail("Live signaling disconnected.")
            }
        }
        connection.offer(for: constraints) { [weak self] description, error in
            Task { @MainActor in
                guard let self, self.generation == currentGeneration else { return }
                self.diagnostic("offer-created")
                guard let description, error == nil else {
                    self.fail("The camera connection could not be negotiated.")
                    return
                }
                do {
                    try await connection.setLocalDescription(description)
                } catch {
                    guard self.generation == currentGeneration else { return }
                    self.fail("Local video negotiation failed.")
                    return
                }
                self.diagnostic("local-description-set")
                do {
                    try await self.waitForSocketOpen(ws)
                    try await self.send(type: "webrtc/offer", value: description.sdp, generation: currentGeneration)
                    self.diagnostic("offer-sent")
                    guard self.generation == currentGeneration else { return }
                    self.offerSent = true
                    let pending = self.localCandidates
                    self.localCandidates = []
                    for candidate in pending {
                        try await self.send(type: "webrtc/candidate", value: candidate.sdp, generation: currentGeneration)
                    }
                } catch {
                    if self.generation == currentGeneration { self.fail("Live signaling failed.") }
                }
            }
        }
        watchdog = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                let age = Date().timeIntervalSince(self.lastFrameAt)
                if !self.hasVideo {
                    self.diagnostic("connecting-http-\((self.socket?.response as? HTTPURLResponse)?.statusCode ?? 0)")
                }
                if age > (self.hasVideo ? 6 : 15) {
                    self.fail(self.hasVideo ? "Live video stopped arriving." : "Low-latency video is unavailable on this connection.")
                }
            }
        }
        diagnostic("open")
    }

    func setAudio(isMuted: Bool, volume: Float) {
        muted = isMuted
        self.volume = volume
        audioTrack?.isEnabled = !isMuted
        audioTrack?.source.volume = Double(min(max(volume, 0), 1))
    }

    func stop() {
        generation = UUID()
        retryTask?.cancel()
        retryTask = nil
        retryURL = nil
        retryRelayPort = nil
        watchdog?.invalidate()
        watchdog = nil
        receiveTask?.cancel()
        receiveTask = nil
        socket?.cancel(with: .goingAway, reason: nil)
        socket = nil
        connectionSession?.invalidateAndCancel()
        connectionSession = nil
        if let frameMonitor { videoTrack?.remove(frameMonitor) }
        frameMonitor = nil
        videoTrack = nil
        audioTrack = nil
        peer?.close()
        peer = nil
        localCandidates = []
        remoteCandidates = []
        serverCandidates = []
        offerSent = false
        hasVideo = false
    }

    private func send(type: String, value: String, generation expectedGeneration: UUID) async throws {
        guard generation == expectedGeneration, let socket else { throw CancellationError() }
        let data = try JSONSerialization.data(withJSONObject: ["type": type, "value": value])
        try await socket.send(.string(String(decoding: data, as: UTF8.self)))
    }

    private func waitForSocketOpen(_ socket: URLSessionWebSocketTask) async throws {
        for _ in 0..<30 {
            if Task.isCancelled { throw CancellationError() }
            do {
                try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                    socket.sendPing { error in
                        if let error { continuation.resume(throwing: error) }
                        else { continuation.resume() }
                    }
                }
                diagnostic("socket-ready")
                return
            } catch {
                try await Task.sleep(nanoseconds: 100_000_000)
            }
        }
        throw URLError(.cannotConnectToHost)
    }

    private func handle(type: String, value: String, generation currentGeneration: UUID) {
        guard let peer else { return }
        switch type {
        case "webrtc/answer":
            peer.setRemoteDescription(RTCSessionDescription(type: .answer, sdp: value)) { [weak self] error in
                Task { @MainActor in
                    guard let self, self.generation == currentGeneration else { return }
                    guard error == nil else { self.fail("The camera's video format could not be negotiated."); return }
                    for candidate in self.serverCandidates { try? await peer.add(candidate) }
                    for candidate in self.remoteCandidates { try? await peer.add(candidate) }
                    self.remoteCandidates = []
                }
            }
        case "webrtc/candidate":
            guard !value.isEmpty else { return }
            let candidate = RTCIceCandidate(sdp: value, sdpMLineIndex: 0, sdpMid: "0")
            if peer.remoteDescription == nil { remoteCandidates.append(candidate) }
            else { peer.add(candidate) { _ in } }
        case "error":
            fail("The server could not provide low-latency video.")
        default: break
        }
    }

    private func fail(_ message: String) {
        diagnostic("failed")
        let url = retryURL
        let relayPort = retryRelayPort
        stop()
        failure = message
        status = message
        // Keep HLS visible while periodically trying the preferred transport.
        // Closing the viewer cancels this retry through stop().
        guard let url else { return }
        let stoppedGeneration = generation
        retryTask = Task { [weak self] in
            do { try await Task.sleep(for: .seconds(15)) }
            catch { return }
            guard let self, self.generation == stoppedGeneration else { return }
            self.start(hlsURL: url, isMuted: true, volume: self.volume, relayPort: relayPort)
        }
    }

    private func received(track: RTCMediaStreamTrack, from connection: RTCPeerConnection) {
        guard connection === peer else { return }
        if let video = track as? RTCVideoTrack {
            if let frameMonitor { videoTrack?.remove(frameMonitor) }
            videoTrack = video
            let currentGeneration = generation
            let monitor = LiveFrameMonitor { [weak self] in
                Task { @MainActor in
                    guard let self, self.generation == currentGeneration else { return }
                    self.lastFrameAt = Date()
                    if !self.hasVideo {
                        self.hasVideo = true
                        self.status = "Live · WebRTC"
                        self.diagnostic("first-frame")
                    }
                }
            }
            frameMonitor = monitor
            video.add(monitor)
        } else if let audio = track as? RTCAudioTrack {
            audioTrack = audio
            setAudio(isMuted: muted, volume: volume)
        }
    }

    private func diagnostic(_ event: String) {
        #if DEBUG
        guard ProcessInfo.processInfo.environment["PLAINNVR_STREAM_DIAGNOSTICS"] == "1" else { return }
        print("PlainNVR.RTC event=\(event) elapsed=\(String(format: "%.3f", Date().timeIntervalSince(openedAt)))")
        #endif
    }
}

extension NativeLiveSession: RTCPeerConnectionDelegate {
    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didChange stateChanged: RTCSignalingState) {}
    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didAdd stream: RTCMediaStream) {}
    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didRemove stream: RTCMediaStream) {}
    nonisolated func peerConnectionShouldNegotiate(_ peerConnection: RTCPeerConnection) {}
    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCIceGatheringState) {}
    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didRemove candidates: [RTCIceCandidate]) {}
    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didOpen dataChannel: RTCDataChannel) {}
    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCIceConnectionState) {
        Task { @MainActor in
            guard peerConnection === self.peer else { return }
            self.diagnostic("ice-\(newState.rawValue)")
            if newState == .failed { self.fail("The camera's live media connection failed.") }
        }
    }
    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didGenerate candidate: RTCIceCandidate) {
        Task { @MainActor in
            guard peerConnection === self.peer else { return }
            if !self.offerSent { self.localCandidates.append(candidate); return }
            do { try await self.send(type: "webrtc/candidate", value: candidate.sdp, generation: self.generation) }
            catch { if peerConnection === self.peer { self.fail("Live signaling failed.") } }
        }
    }
    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didAdd rtpReceiver: RTCRtpReceiver, streams: [RTCMediaStream]) {
        Task { @MainActor in
            if let track = rtpReceiver.track { self.received(track: track, from: peerConnection) }
        }
    }
}

private final class LiveFrameMonitor: NSObject, RTCVideoRenderer {
    private let onFrame: () -> Void
    init(onFrame: @escaping () -> Void) { self.onFrame = onFrame }
    func setSize(_ size: CGSize) {}
    func renderFrame(_ frame: RTCVideoFrame?) { if frame != nil { onFrame() } }
}

#if os(iOS)
struct NativeVideoSurface: UIViewRepresentable {
    let track: RTCVideoTrack?
    func makeUIView(context: Context) -> RTCMTLVideoView {
        let view = RTCMTLVideoView(frame: .zero)
        view.videoContentMode = .scaleAspectFit
        return view
    }
    func updateUIView(_ view: RTCMTLVideoView, context: Context) {
        guard context.coordinator.track !== track else { return }
        context.coordinator.track?.remove(view)
        context.coordinator.track = track
        track?.add(view)
    }
    static func dismantleUIView(_ view: RTCMTLVideoView, coordinator: Coordinator) { coordinator.track?.remove(view) }
    func makeCoordinator() -> Coordinator { Coordinator() }
    final class Coordinator { var track: RTCVideoTrack? }
}
#else
struct NativeVideoSurface: NSViewRepresentable {
    let track: RTCVideoTrack?
    func makeNSView(context: Context) -> RTCMTLNSVideoView { RTCMTLNSVideoView(frame: .zero) }
    func updateNSView(_ view: RTCMTLNSVideoView, context: Context) {
        guard context.coordinator.track !== track else { return }
        context.coordinator.track?.remove(view)
        context.coordinator.track = track
        track?.add(view)
    }
    static func dismantleNSView(_ view: RTCMTLNSVideoView, coordinator: Coordinator) { coordinator.track?.remove(view) }
    func makeCoordinator() -> Coordinator { Coordinator() }
    final class Coordinator { var track: RTCVideoTrack? }
}
#endif
