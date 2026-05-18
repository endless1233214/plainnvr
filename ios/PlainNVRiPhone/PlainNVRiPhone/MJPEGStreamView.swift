import Foundation
import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

#if os(iOS)
typealias PlainNVRPlatformImage = UIImage
#elseif os(macOS)
typealias PlainNVRPlatformImage = NSImage
#endif

final class MJPEGStreamModel: NSObject, ObservableObject, URLSessionDataDelegate {
    @Published var image: PlainNVRPlatformImage?
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

            if let image = PlainNVRPlatformImage(data: jpegData) {
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

    var body: some View {
        ZStack {
            Rectangle()
                .fill(.black)

            if let image = stream.image {
                #if os(iOS)
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
                #elseif os(macOS)
                Image(nsImage: image)
                    .resizable()
                    .scaledToFit()
                #endif
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
        .onAppear {
            stream.start(url: url)
        }
        .onChange(of: url) { _, newURL in
            stream.start(url: newURL)
        }
        .onDisappear {
            stream.stop()
        }
    }
}
