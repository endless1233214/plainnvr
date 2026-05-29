import Foundation
import SwiftUI
import UIKit

final class MJPEGStreamModel: NSObject, ObservableObject, URLSessionDataDelegate {
    @Published var image: UIImage?
    @Published var isConnected = false
    @Published var errorMessage: String?

    private let startMarker = Data([0xFF, 0xD8])
    private let endMarker = Data([0xFF, 0xD9])
    private let maxBufferSize = 6 * 1024 * 1024

    private var buffer = Data()
    private var session: URLSession?
    private var task: URLSessionDataTask?
    private var currentURL: URL?

    func start(url: URL) {
        if currentURL == url, task != nil {
            return
        }

        stop()
        currentURL = url

        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 30
        configuration.timeoutIntervalForResource = 60 * 60
        configuration.httpShouldSetCookies = true
        configuration.httpCookieStorage = .shared
        configuration.waitsForConnectivity = true

        let session = URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
        self.session = session
        task = session.dataTask(with: url)
        task?.resume()
    }

    func stop() {
        task?.cancel()
        session?.invalidateAndCancel()
        task = nil
        session = nil
        currentURL = nil
        buffer.removeAll(keepingCapacity: true)

        DispatchQueue.main.async {
            self.isConnected = false
        }
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        buffer.append(data)
        parseFrames()
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let error else { return }
        let nsError = error as NSError
        guard nsError.code != NSURLErrorCancelled else { return }

        DispatchQueue.main.async {
            self.errorMessage = error.localizedDescription
            self.isConnected = false
        }
    }

    private func parseFrames() {
        while true {
            guard let startRange = buffer.range(of: startMarker) else {
                trimOversizedBuffer()
                return
            }

            if startRange.lowerBound > buffer.startIndex {
                buffer.removeSubrange(buffer.startIndex..<startRange.lowerBound)
            }

            guard buffer.count >= 4 else { return }
            let searchStart = buffer.index(buffer.startIndex, offsetBy: 2)
            guard let endRange = buffer.range(of: endMarker, options: [], in: searchStart..<buffer.endIndex) else {
                trimOversizedBuffer()
                return
            }

            let frameRange = buffer.startIndex..<endRange.upperBound
            let jpegData = Data(buffer[frameRange])
            buffer.removeSubrange(frameRange)

            if let image = UIImage(data: jpegData) {
                DispatchQueue.main.async {
                    self.image = image
                    self.errorMessage = nil
                    self.isConnected = true
                }
            }
        }
    }

    private func trimOversizedBuffer() {
        guard buffer.count > maxBufferSize else { return }
        buffer.removeFirst(buffer.count - 2)
    }
}

struct MJPEGStreamView: View {
    let url: URL
    @StateObject private var stream = MJPEGStreamModel()
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
                Rectangle()
                    .fill(.black)

                if let image = stream.image {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFit()
                        .scaleEffect(scale)
                        .offset(offset)
                } else {
                    VStack(spacing: 12) {
                        ProgressView()
                            .tint(.white)
                        Image(systemName: "video")
                            .font(.largeTitle)
                            .foregroundStyle(.white.opacity(0.7))
                    }
                }

                if let errorMessage = stream.errorMessage {
                    VStack {
                        Spacer()
                        Label(errorMessage, systemImage: "wifi.exclamationmark")
                            .font(.caption)
                            .padding(10)
                            .foregroundStyle(.white)
                            .background(.black.opacity(0.72), in: RoundedRectangle(cornerRadius: 8))
                            .padding(10)
                    }
                }
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
        .onAppear {
            stream.start(url: url)
        }
        .onChange(of: url) { _, newURL in
            resetZoom()
            stream.start(url: newURL)
        }
        .onDisappear {
            stream.stop()
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
