import AVKit
import SwiftUI

struct MacRecordingsView: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel
    @State private var player = AVPlayer()

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Picker("Camera", selection: Binding(
                    get: { viewModel.selectedCameraID ?? viewModel.cameras.first?.id ?? "" },
                    set: { id in Task { await viewModel.selectCamera(id, loadRecordings: true) } }
                )) {
                    ForEach(viewModel.cameras) { Text($0.name).tag($0.id) }
                }
                DatePicker("Date", selection: $viewModel.selectedRecordingDate, displayedComponents: .date)
                    .onChange(of: viewModel.selectedRecordingDate) { _, _ in Task { try? await viewModel.refreshSegments() } }
                Button("Load") { Task { await viewModel.refreshCoverageAndSegments() } }
            }
            .padding(.horizontal)

            HSplitView {
                List(viewModel.segments, selection: Binding(
                    get: { viewModel.activeSegment?.id },
                    set: { id in
                        guard let id, let segment = viewModel.segments.first(where: { $0.id == id }) else { return }
                        viewModel.activeSegment = segment
                        if let url = viewModel.playbackURL(for: segment) { player.replaceCurrentItem(with: AVPlayerItem(url: url)); player.play() }
                    }
                )) { segment in
                    VStack(alignment: .leading, spacing: 3) {
                        Text(PlainNVRFormat.displayTime(segment.start)).font(.headline)
                        Text(ByteCountFormatter.string(fromByteCount: segment.size, countStyle: .file))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 4)
                    .tag(segment.id)
                }
                .frame(minWidth: 240, idealWidth: 300)

                MacAVPlayerSurface(player: player)
                    .frame(minWidth: 420, minHeight: 280)
                    .background(.black)
            }
            .padding(.horizontal)
        }
        .task { await viewModel.loadRecordingBrowserIfNeeded() }
        .navigationTitle("Recordings")
    }
}
