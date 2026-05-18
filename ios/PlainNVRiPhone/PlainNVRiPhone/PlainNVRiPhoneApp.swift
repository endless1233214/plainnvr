import SwiftUI

@main
struct PlainNVRCompainionApp: App {
    @StateObject private var viewModel = PlainNVRViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(viewModel)
        }
    }
}
