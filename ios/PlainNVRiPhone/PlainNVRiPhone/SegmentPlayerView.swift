import AVKit
import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

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
            .plainNVRInlineNavigationTitle()
            .toolbar {
                #if os(iOS)
                ToolbarItemGroup(placement: .navigationBarLeading) {
                    saveButton
                    shareButton
                }

                ToolbarItem(placement: .navigationBarTrailing) {
                    closeButton
                }
                #else
                ToolbarItemGroup {
                    saveButton
                    shareButton
                    closeButton
                }
                #endif
            }
            .onAppear(perform: startPlayback)
            .onDisappear(perform: stopPlayback)
            .sheet(item: $shareItem) { item in
                #if os(iOS)
                ShareSheet(activityItems: [item.url])
                #else
                MacShareView(url: item.url)
                #endif
            }
            .alert("PlainNVR", isPresented: messageBinding) {
                Button("OK", role: .cancel) {}
            } message: {
                Text(message ?? "")
            }
    }

    private var saveButton: some View {
        Button {
            Task { await saveRecording() }
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

    private func saveRecording() async {
        #if os(iOS)
        await runPreparation {
            try await viewModel.saveSegmentToPhotos(segment)
            message = "Saved to Photos."
        }
        #else
        await runPreparation {
            let destination = try await viewModel.saveSegmentToDownloads(segment)
            message = "Saved to \(destination.lastPathComponent) in Downloads."
        }
        #endif
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
    @State private var baseScale: CGFloat = 1
    @GestureState private var gestureScale: CGFloat = 1
    @State private var baseOffset: CGSize = .zero
    @GestureState private var dragOffset: CGSize = .zero

    private let maximumScale: CGFloat = 6

    var body: some View {
        GeometryReader { proxy in
            let scale = clampedScale(baseScale * gestureScale)
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
            player.replaceCurrentItem(with: AVPlayerItem(url: url))
            player.play()
        }
        .onChange(of: url) { _, newURL in
            resetZoom()
            player.replaceCurrentItem(with: AVPlayerItem(url: newURL))
            player.play()
        }
        .onDisappear {
            player.pause()
            player.replaceCurrentItem(with: nil)
        }
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

struct ShareItem: Identifiable {
    let url: URL
    var id: String { url.absoluteString }
}

#if os(iOS)
struct ShareSheet: UIViewControllerRepresentable {
    let activityItems: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: activityItems, applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {
    }
}
#elseif os(macOS)
struct MacShareView: View {
    let url: URL
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 16) {
            ShareLink(item: url) {
                Label("Share Recording", systemImage: "square.and.arrow.up")
            }

            Button {
                NSWorkspace.shared.activateFileViewerSelecting([url])
            } label: {
                Label("Show in Finder", systemImage: "folder")
            }

            Button("Done") {
                dismiss()
            }
            .keyboardShortcut(.defaultAction)
        }
        .padding(24)
        .frame(width: 280)
    }
}
#endif
