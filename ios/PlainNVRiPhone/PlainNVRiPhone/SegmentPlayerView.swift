import AVKit
import SwiftUI
import UIKit

struct SegmentPlayerView: View {
    let url: URL
    let title: String
    let segment: RecordingSegment
    let rotationDegrees: Int

    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var viewModel: PlainNVRViewModel
    @State private var player = AVPlayer()
    @State private var isPreparingShare = false
    @State private var shareItem: ShareItem?
    @State private var message: String?

    var body: some View {
        NavigationStack {
            playerView
        }
    }

    private var playerView: some View {
        GeometryReader { proxy in
            let rotation = normalizedRotation(rotationDegrees)
            let fitScale = rotationFitScale(rotation, size: proxy.size)

            ZStack {
                Color.black

                VideoPlayer(player: player)
                    .rotationEffect(.degrees(Double(rotation)))
                    .scaleEffect(fitScale)
            }
        }
            .background(.black)
            .ignoresSafeArea(edges: .bottom)
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItemGroup(placement: .navigationBarLeading) {
                    saveButton
                    shareButton
                }

                ToolbarItem(placement: .navigationBarTrailing) {
                    closeButton
                }
            }
            .onAppear(perform: startPlayback)
            .onDisappear(perform: stopPlayback)
            .sheet(item: $shareItem) { item in
                ShareSheet(activityItems: [item.url])
            }
            .alert("PlainNVR", isPresented: messageBinding) {
                Button("OK", role: .cancel) {}
            } message: {
                Text(message ?? "")
            }
    }

    private var saveButton: some View {
        Button {
            Task { await saveToPhotos() }
        } label: {
            Image(systemName: "square.and.arrow.down")
        }
        .disabled(isPreparingShare)
    }

    private var shareButton: some View {
        Button {
            Task { await prepareShare() }
        } label: {
            Image(systemName: "square.and.arrow.up")
        }
        .disabled(isPreparingShare)
    }

    private var closeButton: some View {
        Button {
            dismiss()
        } label: {
            Image(systemName: "xmark")
        }
    }

    private var messageBinding: Binding<Bool> {
        Binding {
            message != nil
        } set: { isPresented in
            if !isPresented {
                message = nil
            }
        }
    }

    private func startPlayback() {
        player.replaceCurrentItem(with: AVPlayerItem(url: url))
        player.play()
    }

    private func stopPlayback() {
        player.pause()
        player.replaceCurrentItem(with: nil)
    }

    private func saveToPhotos() async {
        await runPreparation {
            try await viewModel.saveSegmentToPhotos(segment)
            message = "Saved to Photos."
        }
    }

    private func prepareShare() async {
        await runPreparation {
            shareItem = ShareItem(url: try await viewModel.downloadSegment(segment))
        }
    }

    private func runPreparation(_ operation: () async throws -> Void) async {
        isPreparingShare = true
        defer { isPreparingShare = false }
        do {
            try await operation()
        } catch {
            if let localized = error as? LocalizedError, let description = localized.errorDescription {
                message = description
            } else {
                message = error.localizedDescription
            }
        }
    }
}

struct LivePlayerView: View {
    let url: URL
    var relayPort: Int?
    var isMuted = false
    var volume: Float = 0.85
    var rotationDegrees = 0
    var viewerZoomEnabled = true
    var onZoomGesture: (String) -> Void = { _ in }
    var onTap: () -> Void = {}
    var onStatus: (String?) -> Void = { _ in }
    var onFailure: (String) -> Void = { _ in }

    @State private var player = AVPlayer()
    @StateObject private var nativeSession = NativeLiveSession()
    @Environment(\.scenePhase) private var scenePhase
    @State private var usingHLS = true
    @State private var suspended = false
    @State private var statusObservation: NSKeyValueObservation?
    @State private var errorLogObserver: NSObjectProtocol?
    @State private var playbackStalledObserver: NSObjectProtocol?
    @State private var playbackFailedObserver: NSObjectProtocol?
    @State private var liveEdgeTimer: Timer?
    @State private var retryTask: Task<Void, Never>?
    @State private var isActive = false
    @State private var lastPlaybackTime: Double?
    @State private var lastPlaybackProgressAt = Date()
    @State private var playbackOpenedAt = Date()
    @State private var baseScale: CGFloat = 1
    @GestureState private var gestureScale: CGFloat = 1
    @State private var baseOffset: CGSize = .zero
    @GestureState private var dragOffset: CGSize = .zero

    private let maximumScale: CGFloat = 6

    var body: some View {
        GeometryReader { proxy in
            let rotation = normalizedRotation(rotationDegrees)
            let fitScale = rotationFitScale(rotation, size: proxy.size)
            let scale = clampedScale(baseScale * gestureScale) * fitScale
            let offset = clampedOffset(
                CGSize(
                    width: baseOffset.width + dragOffset.width,
                    height: baseOffset.height + dragOffset.height
                ),
                scale: scale,
                size: proxy.size
            )

            ZStack {
                Color.black

                Group {
                    if usingHLS {
                        HLSVideoSurface(player: player)
                    } else {
                        NativeVideoSurface(track: nativeSession.videoTrack)
                    }
                }
                    .rotationEffect(.degrees(Double(rotation)))
                    .scaleEffect(scale)
                    .offset(offset)
            }
            .clipped()
            .contentShape(Rectangle())
            .highPriorityGesture(magnificationGesture(size: proxy.size))
            .simultaneousGesture(dragGesture(size: proxy.size))
            .simultaneousGesture(
                TapGesture()
                    .onEnded {
                        onTap()
                    }
            )
            .onTapGesture(count: 2) {
                if viewerZoomEnabled {
                    withAnimation(.spring(response: 0.28, dampingFraction: 0.85)) {
                        resetZoom()
                    }
                }
            }
        }
        .background(.black)
        .onAppear {
            isActive = true
            startPlayback(url)
        }
        .onChange(of: url) { _, newURL in
            resetZoom()
            startPlayback(newURL)
        }
        .onChange(of: isMuted) { _, _ in
            applyAudioSettings()
        }
        .onChange(of: volume) { _, _ in
            applyAudioSettings()
        }
        .onChange(of: nativeSession.hasVideo) { _, hasVideo in
            guard isActive, hasVideo else { return }
            usingHLS = false
            stopHLSPlayback()
            nativeSession.setAudio(isMuted: isMuted, volume: volume)
            onStatus("Live · WebRTC")
        }
        .onChange(of: nativeSession.failure) { _, failure in
            guard isActive, let failure else { return }
            if !usingHLS {
                usingHLS = true
                startHLSPlayback(url)
            }
            // HLS is already the reliable compatibility path. Keep the
            // transport negotiation detail out of the live-view surface so a
            // transient WebRTC capability issue does not look like a camera
            // failure to the user.
            _ = failure
            onStatus(nil)
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .background {
                suspended = true
                stopPlayback()
            } else if phase == .active, suspended, isActive {
                suspended = false
                startPlayback(url)
            }
        }
        .onDisappear {
            isActive = false
            stopPlayback()
        }
    }

    private func startPlayback(_ url: URL) {
        usingHLS = true
        startHLSPlayback(url)
        nativeSession.start(hlsURL: url, isMuted: true, volume: volume, relayPort: relayPort)
    }

    private func startHLSPlayback(_ url: URL) {
        retryTask?.cancel()
        retryTask = nil
        clearObservers()
        stopLiveEdgeTimer()
        lastPlaybackTime = nil
        lastPlaybackProgressAt = Date()
        playbackOpenedAt = Date()
        onStatus("Opening live stream...")
        let item = AVPlayerItem(url: url)
        item.preferredForwardBufferDuration = 0.25
        item.canUseNetworkResourcesForLiveStreamingWhilePaused = false
        logLiveDiagnostics("open", item: item)
        statusObservation = item.observe(\.status, options: [.new]) { item, _ in
            DispatchQueue.main.async {
                guard isActive, !suspended, usingHLS, player.currentItem === item else { return }
                switch item.status {
                case .readyToPlay:
                    logLiveDiagnostics("ready", item: item)
                    player.play()
                    onStatus(nil)
                case .failed:
                    logLiveDiagnostics("failed", item: item)
                    scheduleRetry(
                        url,
                        message: "Player failed: \(item.error?.localizedDescription ?? "Unknown AVPlayer error")"
                    )
                case .unknown:
                    break
                @unknown default:
                    onFailure("Player failed with an unknown status.")
                }
            }
        }
        errorLogObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemNewErrorLogEntry,
            object: item,
            queue: .main
        ) { _ in
            guard isActive, usingHLS, player.currentItem === item else { return }
            guard let event = item.errorLog()?.events.last else { return }
            logLiveDiagnostics("error-\(event.errorStatusCode)", item: item)
            let details = event.errorComment ?? event.errorStatusCode.description
            scheduleRetry(url, message: "Player error \(event.errorStatusCode): \(details)")
        }
        playbackStalledObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemPlaybackStalled,
            object: item,
            queue: .main
        ) { _ in
            guard isActive, usingHLS, player.currentItem === item else { return }
            logLiveDiagnostics("stalled", item: item)
            scheduleRetry(url, message: "Live playback stalled.")
        }
        playbackFailedObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemFailedToPlayToEndTime,
            object: item,
            queue: .main
        ) { notification in
            guard isActive, usingHLS, player.currentItem === item else { return }
            let error = notification.userInfo?[AVPlayerItemFailedToPlayToEndTimeErrorKey] as? Error
            scheduleRetry(url, message: "Live playback stopped: \(error?.localizedDescription ?? "Unknown error")")
        }
        player.automaticallyWaitsToMinimizeStalling = false
        player.replaceCurrentItem(with: item)
        applyAudioSettings()
        player.playImmediately(atRate: 1)
        startLiveEdgeTimer()
    }

    private func stopPlayback() {
        nativeSession.stop()
        stopHLSPlayback()
    }

    private func stopHLSPlayback() {
        retryTask?.cancel()
        retryTask = nil
        clearObservers()
        stopLiveEdgeTimer()
        player.pause()
        player.replaceCurrentItem(with: nil)
    }

    private func clearObservers() {
        statusObservation?.invalidate()
        statusObservation = nil
        if let errorLogObserver {
            NotificationCenter.default.removeObserver(errorLogObserver)
            self.errorLogObserver = nil
        }
        if let playbackStalledObserver {
            NotificationCenter.default.removeObserver(playbackStalledObserver)
            self.playbackStalledObserver = nil
        }
        if let playbackFailedObserver {
            NotificationCenter.default.removeObserver(playbackFailedObserver)
            self.playbackFailedObserver = nil
        }
    }

    private func startLiveEdgeTimer() {
        stopLiveEdgeTimer()
        liveEdgeTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { _ in
            seekTowardLiveEdgeIfNeeded()
        }
    }

    private func stopLiveEdgeTimer() {
        liveEdgeTimer?.invalidate()
        liveEdgeTimer = nil
    }

    private func seekTowardLiveEdgeIfNeeded() {
        logLiveDiagnostics("tick", item: player.currentItem)
        guard let item = player.currentItem,
              item.status == .readyToPlay,
              let range = item.seekableTimeRanges.last?.timeRangeValue
        else {
            return
        }

        // A paused player must never be advanced by the live-edge timer.
        // Startup and lifecycle callbacks explicitly request playback.
        guard player.rate > 0 else { return }

        let liveEdge = range.start + range.duration
        let current = player.currentTime()
        let currentSeconds = CMTimeGetSeconds(current)
        if currentSeconds.isFinite,
           lastPlaybackTime == nil || currentSeconds > (lastPlaybackTime ?? 0) + 0.05 {
            lastPlaybackTime = currentSeconds
            lastPlaybackProgressAt = Date()
        } else if Date().timeIntervalSince(lastPlaybackProgressAt) > 12 {
            scheduleRetry(url, message: "Live video stopped advancing.")
            return
        }
        let lag = CMTimeGetSeconds(liveEdge - current)
        guard lag.isFinite, lag > 2.5 else { return }

        let target = liveEdge - CMTime(seconds: 0.5, preferredTimescale: 600)
        logLiveDiagnostics("seek-live-edge", item: item)
        player.seek(to: target, toleranceBefore: CMTime(seconds: 0.5, preferredTimescale: 600), toleranceAfter: .zero)
    }

    private func logLiveDiagnostics(_ event: String, item: AVPlayerItem?) {
        #if DEBUG
        guard ProcessInfo.processInfo.environment["PLAINNVR_STREAM_DIAGNOSTICS"] == "1" else { return }
        let current = player.currentTime().seconds
        let bufferedEnd = item?.loadedTimeRanges.last?.timeRangeValue.end.seconds
        let seekableEnd = item?.seekableTimeRanges.last?.timeRangeValue.end.seconds
        let access = item?.accessLog()?.events.last
        func number(_ value: Double?) -> String {
            guard let value, value.isFinite else { return "unknown" }
            return String(format: "%.3f", value)
        }
        // Deliberately omit media URLs, session tokens, and server addresses.
        print("PlainNVR.Live event=\(event) elapsed=\(number(Date().timeIntervalSince(playbackOpenedAt)))"
            + " time=\(number(current)) buffer=\(number(bufferedEnd.map { $0 - current }))"
            + " edgeLag=\(number(seekableEnd.map { $0 - current })) rate=\(player.rate)"
            + " control=\(player.timeControlStatus.rawValue) wait=\(player.reasonForWaitingToPlay?.rawValue ?? "none")"
            + " stalls=\(access?.numberOfStalls ?? 0) dropped=\(access?.numberOfDroppedVideoFrames ?? 0)"
            + " observedBitrate=\(number(access?.observedBitrate)) indicatedBitrate=\(number(access?.indicatedBitrate))")
        #endif
    }

    private func scheduleRetry(_ url: URL, message: String) {
        guard isActive, !suspended, usingHLS, retryTask == nil else { return }
        onFailure("\(message) Retrying...")
        retryTask = Task { @MainActor in
            try? await Task.sleep(for: .seconds(3))
            guard !Task.isCancelled, isActive, !suspended, usingHLS else { return }
            startHLSPlayback(url)
        }
    }

    private func applyAudioSettings() {
        player.isMuted = isMuted
        player.volume = min(max(volume, 0), 1)
        nativeSession.setAudio(isMuted: usingHLS || isMuted, volume: volume)
    }

    private func magnificationGesture(size: CGSize) -> some Gesture {
        MagnificationGesture()
            .updating($gestureScale) { value, state, _ in
                state = viewerZoomEnabled ? value : 1
            }
            .onEnded { value in
                guard viewerZoomEnabled else {
                    if value > 1.12 {
                        onZoomGesture("zoom_in")
                    } else if value < 0.88 {
                        onZoomGesture("zoom_out")
                    }
                    return
                }

                baseScale = clampedScale(baseScale * value)
                if baseScale == 1 {
                    baseOffset = .zero
                } else {
                    baseOffset = clampedOffset(baseOffset, scale: baseScale, size: size)
                }
            }
    }

    private func dragGesture(size: CGSize) -> some Gesture {
        DragGesture(minimumDistance: 0)
            .updating($dragOffset) { value, state, _ in
                guard viewerZoomEnabled, baseScale * gestureScale > 1 else {
                    state = .zero
                    return
                }
                state = value.translation
            }
            .onEnded { value in
                guard viewerZoomEnabled, baseScale > 1 else {
                    baseOffset = .zero
                    return
                }
                baseOffset = clampedOffset(
                    CGSize(
                        width: baseOffset.width + value.translation.width,
                        height: baseOffset.height + value.translation.height
                    ),
                    scale: baseScale,
                    size: size
                )
            }
    }

    private func clampedScale(_ value: CGFloat) -> CGFloat {
        min(max(value, 1), maximumScale)
    }

    private func clampedOffset(_ value: CGSize, scale: CGFloat, size: CGSize) -> CGSize {
        guard scale > 1 else { return .zero }
        let maxX = max(0, (size.width * scale - size.width) / 2)
        let maxY = max(0, (size.height * scale - size.height) / 2)
        return CGSize(
            width: min(max(value.width, -maxX), maxX),
            height: min(max(value.height, -maxY), maxY)
        )
    }

    private func resetZoom() {
        baseScale = 1
        baseOffset = .zero
    }
}

/// Live playback is owned by LivePlayerView, not by VideoPlayer's controller
/// lifecycle or its built-in pause button. The app supplies live controls.
private struct HLSVideoSurface: UIViewRepresentable {
    let player: AVPlayer

    final class Surface: UIView {
        override class var layerClass: AnyClass { AVPlayerLayer.self }
        var playerLayer: AVPlayerLayer { layer as! AVPlayerLayer }
    }

    func makeUIView(context: Context) -> Surface {
        let view = Surface()
        view.playerLayer.videoGravity = .resizeAspect
        view.playerLayer.player = player
        return view
    }

    func updateUIView(_ view: Surface, context: Context) {
        view.playerLayer.player = player
    }

    static func dismantleUIView(_ view: Surface, coordinator: ()) {
        view.playerLayer.player = nil
    }
}

private func normalizedRotation(_ value: Int) -> Int {
    switch value {
    case 90, 180, 270:
        return value
    default:
        return 0
    }
}

private func rotationFitScale(_ rotation: Int, size: CGSize) -> CGFloat {
    guard (rotation == 90 || rotation == 270), size.width > 0, size.height > 0 else {
        return 1
    }
    return max(0.35, min(size.width, size.height) / max(size.width, size.height))
}

struct ShareItem: Identifiable {
    let url: URL
    var id: String { url.absoluteString }
}

struct ShareSheet: UIViewControllerRepresentable {
    let activityItems: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: activityItems, applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {
    }
}
