import SwiftUI

@main
struct PlainNVRMacApp: App {
    @StateObject private var viewModel = PlainNVRViewModel()

    var body: some Scene {
        WindowGroup("PlainNVR") {
            MacContentView()
                .environmentObject(viewModel)
                .frame(minWidth: 980, minHeight: 640)
        }
        .windowResizability(.contentSize)
    }
}
