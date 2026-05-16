import SwiftUI

@main
struct PlainNVRiPhoneApp: App {
    @StateObject private var viewModel = PlainNVRViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(viewModel)
        }
    }
}
