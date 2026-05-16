import AVKit
import SwiftUI
import UIKit

struct SegmentPlayerView: View {
    let url: URL
    let title: String
    let segment: RecordingSegment

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
        VideoPlayer(player: player)
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

    @State private var player = AVPlayer()

    var body: some View {
        VideoPlayer(player: player)
            .background(.black)
            .onAppear {
                player.replaceCurrentItem(with: AVPlayerItem(url: url))
                player.play()
            }
            .onChange(of: url) { _, newURL in
                player.replaceCurrentItem(with: AVPlayerItem(url: newURL))
                player.play()
            }
            .onDisappear {
                player.pause()
                player.replaceCurrentItem(with: nil)
            }
    }
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
