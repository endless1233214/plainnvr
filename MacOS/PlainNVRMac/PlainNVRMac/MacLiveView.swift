import AVKit
import SwiftUI

struct MacLiveView: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Picker("Camera", selection: Binding(
                    get: { viewModel.selectedCameraID ?? viewModel.cameras.first?.id ?? "" },
                    set: { id in Task { await viewModel.selectCamera(id) } }
                )) {
                    ForEach(viewModel.cameras) { camera in
                        Text(camera.name).tag(camera.id)
                    }
                }
                .frame(maxWidth: 280)
                Spacer()
                Button { Task { await viewModel.restartLiveStream() } } label: {
                    Label("Reconnect", systemImage: "arrow.clockwise")
                }
            }
            .padding(.horizontal)

            if let camera = viewModel.selectedCamera, let url = viewModel.liveURL(for: camera) {
                MacLivePlayerView(
                    url: url,
                    relayPort: viewModel.status?.go2rtc?.webrtcPort,
                    onStatus: { viewModel.updateLivePlayerStatus($0) }
                )
                .clipShape(RoundedRectangle(cornerRadius: 12))
                .padding(.horizontal)
            } else {
                ContentUnavailableView("No live camera selected", systemImage: "video.slash")
            }

            if let message = viewModel.liveStatusMessage, !message.isEmpty {
                Label(message, systemImage: "info.circle")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal)
            }
            Spacer(minLength: 0)
        }
        .padding(.top)
        .navigationTitle("Live")
    }
}

private struct MacLivePlayerView: View {
    let url: URL
    let relayPort: Int?
    var onStatus: (String?) -> Void
    @State private var player = AVPlayer()
    @StateObject private var nativeSession = NativeLiveSession()
    @State private var usingHLS = true
    @State private var hlsPlaying = false
    @State private var isMuted = true

    var body: some View {
        ZStack {
            Color.black
            if usingHLS {
                MacAVPlayerSurface(player: player)
            } else {
                NativeVideoSurface(track: nativeSession.videoTrack)
            }
            if !nativeSession.hasVideo && usingHLS && !hlsPlaying {
                ProgressView("Opening live video…").tint(.white)
            }
        }
        .aspectRatio(16 / 9, contentMode: .fit)
        .overlay(alignment: .bottomTrailing) {
            Button {
                isMuted.toggle()
                player.isMuted = isMuted
                nativeSession.setAudio(isMuted: isMuted, volume: 0.85)
            } label: {
                Label(isMuted ? "Unmute" : "Mute", systemImage: isMuted ? "speaker.slash.fill" : "speaker.wave.2.fill")
            }
            .buttonStyle(.borderedProminent)
            .padding(16)
        }
        .onAppear { start() }
        .onChange(of: url) { _, _ in start() }
        .onReceive(player.publisher(for: \.timeControlStatus)) { status in
            hlsPlaying = status == .playing
        }
        .onChange(of: nativeSession.hasVideo) { _, hasVideo in
            guard hasVideo else { return }
            usingHLS = false
            player.pause()
            player.replaceCurrentItem(with: nil)
            nativeSession.setAudio(isMuted: isMuted, volume: 0.85)
            onStatus("Live · WebRTC")
        }
        .onChange(of: nativeSession.failure) { _, failure in
            guard failure != nil else { return }
            if !usingHLS { startHLS() }
            usingHLS = true
            onStatus("Live · HLS compatibility")
        }
        .onDisappear {
            nativeSession.stop()
            player.pause()
            player.replaceCurrentItem(with: nil)
        }
    }

    private func start() {
        usingHLS = true
        startHLS()
        nativeSession.start(hlsURL: url, isMuted: true, volume: 0.85, relayPort: relayPort)
        onStatus(nil)
    }

    private func startHLS() {
        hlsPlaying = false
        player.isMuted = isMuted
        let item = AVPlayerItem(url: url)
        item.preferredForwardBufferDuration = 0.25
        player.replaceCurrentItem(with: item)
        player.play()
    }
}

struct MacAVPlayerSurface: NSViewRepresentable {
    let player: AVPlayer
    func makeNSView(context: Context) -> AVPlayerView {
        let view = AVPlayerView()
        view.player = player
        view.controlsStyle = .floating
        view.showsFullScreenToggleButton = true
        return view
    }
    func updateNSView(_ view: AVPlayerView, context: Context) { view.player = player }
}
