import SwiftUI

struct MacContentView: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel

    var body: some View {
        Group {
            if viewModel.connectionState == .signedIn {
                MacMainView()
            } else {
                MacSignInView()
            }
        }
        .task {
            if viewModel.connectionState == .checking {
                await viewModel.bootstrap()
            }
        }
        .alert("PlainNVR", isPresented: Binding(
            get: { viewModel.errorMessage != nil },
            set: { if !$0 { viewModel.errorMessage = nil } }
        )) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(viewModel.errorMessage ?? "")
        }
    }
}

private struct MacSignInView: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel

    var body: some View {
        VStack(spacing: 22) {
            Image(systemName: "video.fill")
                .font(.system(size: 44))
                .foregroundStyle(.blue)
            VStack(spacing: 6) {
                Text("PlainNVR").font(.largeTitle.bold())
                Text("Your cameras, on your Mac.").foregroundStyle(.secondary)
            }
            Form {
                TextField("Server address", text: $viewModel.serverAddress)
                    .textFieldStyle(.roundedBorder)
                TextField("Username", text: $viewModel.username)
                    .textFieldStyle(.roundedBorder)
                SecureField("Password", text: $viewModel.password)
                    .textFieldStyle(.roundedBorder)
                HStack {
                    Button("Test Connection") { Task { await viewModel.testConnection() } }
                    Spacer()
                    Button(viewModel.setupRequired ? "Create Account" : "Sign In") {
                        Task { await viewModel.connectOrSignIn() }
                    }
                    .buttonStyle(.borderedProminent)
                }
                if viewModel.isBusy { ProgressView().controlSize(.small) }
            }
            .frame(width: 390)
        }
        .padding(44)
    }
}

enum MacSection: Hashable {
    case live, cameras, recordings, settings
}

private struct MacMainView: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel
    @State private var section: MacSection? = .live

    var body: some View {
        NavigationSplitView {
            List(selection: $section) {
                Section("PlainNVR") {
                    Label("Live", systemImage: "dot.radiowaves.left.and.right")
                        .tag(MacSection.live)
                    Label("Cameras", systemImage: "video")
                        .tag(MacSection.cameras)
                    Label("Recordings", systemImage: "play.rectangle")
                        .tag(MacSection.recordings)
                }
                Section {
                    Label("Settings", systemImage: "gearshape")
                        .tag(MacSection.settings)
                }
            }
            .listStyle(.sidebar)
            .navigationTitle("PlainNVR")
        } detail: {
            switch section ?? .live {
            case .live: MacLiveView()
            case .cameras: MacCamerasView()
            case .recordings: MacRecordingsView()
            case .settings: MacSettingsView()
            }
        }
        .toolbar {
            ToolbarItem {
                Button { Task { await viewModel.refreshAll() } } label: {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
                .disabled(viewModel.isBusy)
            }
        }
    }
}

private struct MacCamerasView: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel

    var body: some View {
        List {
            Section("Cameras") {
                ForEach(viewModel.cameras) { camera in
                    HStack(spacing: 12) {
                        Image(systemName: camera.enabled ? "video.fill" : "video.slash")
                            .foregroundStyle(camera.enabled ? .blue : .secondary)
                        VStack(alignment: .leading) {
                            Text(camera.name).font(.headline)
                            Text("\(camera.liveModeLabel) · \(camera.retentionDays)d retention")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        if let recorder = viewModel.status?.recorders[camera.id] {
                            Toggle("Recording", isOn: Binding(
                                get: { recorder.running && recorder.paused != true },
                                set: { value in Task { await viewModel.setRecorderRunning(value, camera: camera) } }
                            ))
                            .toggleStyle(.switch)
                            .labelsHidden()
                        }
                    }
                    .padding(.vertical, 5)
                }
            }
        }
        .navigationTitle("Cameras")
        .overlay {
            if viewModel.cameras.isEmpty { ContentUnavailableView("No Cameras", systemImage: "video.slash") }
        }
    }
}

private struct MacSettingsView: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel

    var body: some View {
        Form {
            Section("Connection") {
                LabeledContent("Server", value: viewModel.serverAddress)
                LabeledContent("Account", value: viewModel.currentUsername.isEmpty ? "Not signed in" : viewModel.currentUsername)
                Button("Sign Out") { Task { await viewModel.logout() } }
            }
            Section("About") {
                Text("PlainNVR for Mac")
                Text("Live playback prefers native WebRTC and falls back to HLS.")
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .padding()
        .navigationTitle("Settings")
    }
}
