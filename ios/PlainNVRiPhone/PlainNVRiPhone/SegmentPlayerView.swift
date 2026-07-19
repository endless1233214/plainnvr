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
    var isMuted = false
    var volume: Float = 0.85
    var rotationDegrees = 0
    var onStatus: (String?) -> Void = { _ in }
    var onFailure: (String) -> Void = { _ in }

    @State private var player = AVPlayer()
    @State private var statusObservation: NSKeyValueObservation?
    @State private var errorLogObserver: NSObjectProtocol?
    @State private var playbackStalledObserver: NSObjectProtocol?
    @State private var playbackFailedObserver: NSObjectProtocol?
    @State private var liveEdgeTimer: Timer?
    @State private var retryTask: Task<Void, Never>?
    @State private var isActive = false
    @State private var lastPlaybackTime: Double?
    @State private var lastPlaybackProgressAt = Date()
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

                VideoPlayer(player: player)
                    .rotationEffect(.degrees(Double(rotation)))
                    .scaleEffect(scale)
                    .offset(offset)
            }
            .clipped()
            .contentShape(Rectangle())
            .gesture(magnificationGesture(size: proxy.size))
            .simultaneousGesture(dragGesture(size: proxy.size))
            .onTapGesture(count: 2) {
                withAnimation(.spring(response: 0.28, dampingFraction: 0.85)) {
                    resetZoom()
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
        .onDisappear {
            isActive = false
            stopPlayback()
        }
    }

    private func startPlayback(_ url: URL) {
        retryTask?.cancel()
        retryTask = nil
        clearObservers()
        stopLiveEdgeTimer()
        lastPlaybackTime = nil
        lastPlaybackProgressAt = Date()
        onStatus("Opening live stream...")
        let item = AVPlayerItem(url: url)
        item.preferredForwardBufferDuration = 0.25
        item.canUseNetworkResourcesForLiveStreamingWhilePaused = true
        statusObservation = item.observe(\.status, options: [.new]) { item, _ in
            DispatchQueue.main.async {
                switch item.status {
                case .readyToPlay:
                    onStatus(nil)
                case .failed:
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
            guard let event = item.errorLog()?.events.last else { return }
            let details = event.errorComment ?? event.errorStatusCode.description
            scheduleRetry(url, message: "Player error \(event.errorStatusCode): \(details)")
        }
        playbackStalledObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemPlaybackStalled,
            object: item,
            queue: .main
        ) { _ in
            scheduleRetry(url, message: "Live playback stalled.")
        }
        playbackFailedObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemFailedToPlayToEndTime,
            object: item,
            queue: .main
        ) { notification in
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
        guard let item = player.currentItem,
              item.status == .readyToPlay,
              let range = item.seekableTimeRanges.last?.timeRangeValue
        else {
            return
        }

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
        player.seek(to: target, toleranceBefore: .zero, toleranceAfter: .zero)
    }

    private func scheduleRetry(_ url: URL, message: String) {
        guard isActive, retryTask == nil else { return }
        onFailure("\(message) Retrying...")
        retryTask = Task { @MainActor in
            try? await Task.sleep(for: .seconds(3))
            guard !Task.isCancelled, isActive else { return }
            startPlayback(url)
        }
    }

    private func applyAudioSettings() {
        player.isMuted = isMuted
        player.volume = min(max(volume, 0), 1)
    }

    private func magnificationGesture(size: CGSize) -> some Gesture {
        MagnificationGesture()
            .updating($gestureScale) { value, state, _ in
                state = value
            }
            .onEnded { value in
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
                guard baseScale * gestureScale > 1 else {
                    state = .zero
                    return
                }
                state = value.translation
            }
            .onEnded { value in
                guard baseScale > 1 else {
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
