import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel

    var body: some View {
        Group {
            if viewModel.connectionState == .signedIn {
                MainTabView()
            } else {
                SignInView()
            }
        }
        .task {
            if viewModel.connectionState == .checking {
                await viewModel.bootstrap()
            }
        }
        .alert(
            "PlainNVR",
            isPresented: Binding(
                get: { viewModel.errorMessage != nil },
                set: { isPresented in
                    if !isPresented {
                        viewModel.errorMessage = nil
                    }
                }
            )
        ) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(viewModel.errorMessage ?? "")
        }
    }
}

struct SignInView: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                BrandHeader()
                    .padding(.horizontal, 20)
                    .padding(.top, 18)
                    .padding(.bottom, 10)

                Form {
                    Section("Server") {
                        TextField("http://192.168.1.172:8787", text: $viewModel.serverAddress)
                            .plainNVRURLInput()
                    }

                    Section(viewModel.setupRequired ? "Create Account" : "Sign In") {
                        TextField("Username", text: $viewModel.username)
                            .plainNVRUsernameInput()

                        SecureField("Password", text: $viewModel.password)
                            .plainNVRPasswordInput(isNewPassword: viewModel.setupRequired)

                        Button {
                            Task { await viewModel.connectOrSignIn() }
                        } label: {
                            Label(viewModel.setupRequired ? "Create Account" : "Sign In", systemImage: "person.crop.circle.badge.checkmark")
                        }
                        .disabled(viewModel.isBusy)
                    }
                }
            }
            .navigationTitle("PlainNVR")
            .toolbar {
                if viewModel.isBusy {
                    ProgressView()
                }
            }
        }
    }
}

struct MainTabView: View {
    var body: some View {
        TabView {
            CamerasView()
                .tabItem { Label("Cameras", image: "PlainNVRCameraSymbol") }

            LiveView()
                .tabItem { Label("Live", image: "PlainNVRGridSymbol") }

            RecordingsView()
                .tabItem { Label("Recordings", image: "PlainNVRRecordingSymbol") }

            SettingsView()
                .tabItem { Label("Settings", systemImage: "gearshape") }
        }
    }
}

struct BrandHeader: View {
    var body: some View {
        Image("PlainNVRBanner")
            .resizable()
            .scaledToFit()
            .frame(maxWidth: 420, maxHeight: 150)
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            .accessibilityLabel("PlainNVR")
    }
}

struct CamerasView: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel

    var body: some View {
        NavigationStack {
            List {
                if let disk = viewModel.status?.disk {
                    Section("Storage") {
                        DiskUsageView(disk: disk)
                    }
                }

                Section("Cameras") {
                    if viewModel.cameras.isEmpty {
                        ContentUnavailableView("No Cameras", systemImage: "video.slash")
                    } else {
                        ForEach(viewModel.cameras) { camera in
                            NavigationLink {
                                CameraDetailView(camera: camera)
                            } label: {
                                CameraRow(camera: camera, recorder: viewModel.status?.recorders[camera.id])
                            }
                        }
                    }
                }

                if let events = viewModel.status?.events, !events.isEmpty {
                    Section("Recent Events") {
                        ForEach(events.prefix(8)) { event in
                            EventRow(event: event)
                        }
                    }
                }
            }
            .navigationTitle("PlainNVR")
            .toolbar {
                Button {
                    Task { await viewModel.refreshAll() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .disabled(viewModel.isBusy)
            }
            .refreshable {
                await viewModel.refreshAll()
            }
        }
    }
}

struct CameraDetailView: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel
    let camera: Camera

    private var recorder: RecorderState? {
        viewModel.status?.recorders[camera.id]
    }

    var body: some View {
        List {
            Section("Status") {
                Label(camera.enabled ? "Enabled" : "Disabled", systemImage: camera.enabled ? "checkmark.circle" : "pause.circle")
                Label(recorder?.running == true ? "Recording" : "Idle", systemImage: recorder?.running == true ? "record.circle" : "moon")

                if let lastError = recorder?.lastError, !lastError.isEmpty {
                    Label(lastError, systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.red)
                }
            }

            Section("Recording") {
                LabeledContent("Segments", value: "\(camera.segmentSeconds)s")
                LabeledContent("Retention", value: camera.shortRetention)
                LabeledContent("Transport", value: (camera.rtspTransport ?? "tcp").uppercased())
                LabeledContent("Audio", value: camera.recordAudio == true ? "On" : "Off")
            }

            if let startedAt = recorder?.startedAt {
                Section("Recorder") {
                    LabeledContent("Started", value: PlainNVRFormat.displayDateTime(startedAt))
                    if let pid = recorder?.pid {
                        LabeledContent("PID", value: "\(pid)")
                    }
                }
            }
        }
        .navigationTitle(camera.name)
        .plainNVRInlineNavigationTitle()
    }
}

struct LiveView: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel
    #if os(iOS)
    @Environment(\.verticalSizeClass) private var verticalSizeClass
    #endif

    private var isLandscape: Bool {
        #if os(iOS)
        verticalSizeClass == .compact
        #else
        false
        #endif
    }

    var body: some View {
        NavigationStack {
            liveContent
            .navigationTitle("Live")
            .plainNVRInlineNavigationTitle()
            .toolbar {
                if !isLandscape {
                    Button {
                        Task { await viewModel.refreshAll() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .disabled(viewModel.isBusy)
                }
            }
            .plainNVRLiveChromeHidden(isLandscape)
        }
    }

    @ViewBuilder
    private var liveContent: some View {
        if isLandscape {
            landscapeLiveView
        } else {
            portraitLiveView
        }
    }

    private var portraitLiveView: some View {
        VStack(spacing: 16) {
            if viewModel.cameras.isEmpty {
                ContentUnavailableView("No Cameras", systemImage: "video.slash")
            } else {
                CameraPicker()

                if let camera = viewModel.selectedCamera, let url = viewModel.liveURL(for: camera) {
                    LivePlayerView(url: url)
                        .aspectRatio(16 / 9, contentMode: .fit)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                        .overlay {
                            RoundedRectangle(cornerRadius: 8)
                                .stroke(.quaternary, lineWidth: 1)
                        }

                    CameraRow(camera: camera, recorder: viewModel.status?.recorders[camera.id])
                        .padding(.horizontal)
                } else {
                    ContentUnavailableView("Stream Unavailable", systemImage: "wifi.exclamationmark")
                }
            }

            Spacer()
        }
        .padding(.top, 16)
    }

    private var landscapeLiveView: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            if let camera = viewModel.selectedCamera, let url = viewModel.liveURL(for: camera) {
                LivePlayerView(url: url)
                    .ignoresSafeArea()
            } else {
                ContentUnavailableView("Stream Unavailable", systemImage: "wifi.exclamationmark")
                    .foregroundStyle(.white)
            }
        }
        .ignoresSafeArea()
    }
}

struct RecordingsView: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel

    var body: some View {
        NavigationStack {
            List {
                if viewModel.cameras.isEmpty {
                    ContentUnavailableView("No Cameras", systemImage: "video.slash")
                } else {
                    Section("Camera") {
                        CameraPicker()
                    }

                    Section("Date") {
                        DatePicker(
                            "Recording Date",
                            selection: Binding(
                                get: { viewModel.selectedRecordingDate },
                                set: { date in
                                    viewModel.selectedRecordingDate = date
                                    Task { await viewModel.refreshCoverageAndSegments() }
                                }
                            ),
                            displayedComponents: .date
                        )
                    }

                    if let coverage = viewModel.coverage {
                        Section("Coverage") {
                            CoverageView(coverage: coverage)
                        }
                    }

                    Section("Segments") {
                        if viewModel.segments.isEmpty {
                            ContentUnavailableView("No Recordings", systemImage: "play.slash")
                        } else {
                            ForEach(viewModel.segments) { segment in
                                Button {
                                    viewModel.activeSegment = segment
                                } label: {
                                    SegmentRow(segment: segment)
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                }
            }
            .navigationTitle("Recordings")
            .toolbar {
                Button {
                    Task { await viewModel.refreshCoverageAndSegments() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .disabled(viewModel.isBusy)
            }
            .sheet(item: $viewModel.activeSegment) { segment in
                if let url = viewModel.playbackURL(for: segment) {
                    SegmentPlayerView(url: url, title: PlainNVRFormat.displayTime(segment.start), segment: segment)
                } else {
                    ContentUnavailableView("Video Unavailable", systemImage: "exclamationmark.triangle")
                }
            }
        }
    }
}

struct SettingsView: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel
    @Environment(\.openURL) private var openURL

    var body: some View {
        NavigationStack {
            Form {
                Section("PlainNVR") {
                    HStack(spacing: 12) {
                        Image("PlainNVRMark")
                            .resizable()
                            .scaledToFit()
                            .frame(width: 32, height: 32)
                            .foregroundStyle(Color.accentColor)

                        Text("PlainNVR")
                            .font(.headline)
                    }
                    .accessibilityElement(children: .combine)
                }

                Section("Server") {
                    TextField("Server URL", text: $viewModel.serverAddress)
                        .plainNVRURLInput()

                    Button {
                        Task { await viewModel.bootstrap() }
                    } label: {
                        Label("Reconnect", systemImage: "arrow.triangle.2.circlepath")
                    }

                    if let url = URL(string: viewModel.serverAddress) {
                        Button {
                            openURL(url)
                        } label: {
                            Label("Open Web UI", systemImage: "safari")
                        }
                    }
                }

                Section("Account") {
                    LabeledContent("Signed In", value: viewModel.currentUsername)

                    Button(role: .destructive) {
                        Task { await viewModel.logout() }
                    } label: {
                        Label("Sign Out", systemImage: "rectangle.portrait.and.arrow.right")
                    }
                }
            }
            .navigationTitle("Settings")
        }
    }
}

struct CameraPicker: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel

    var body: some View {
        Picker(
            "Camera",
            selection: Binding(
                get: { viewModel.selectedCameraID ?? viewModel.cameras.first?.id ?? "" },
                set: { cameraID in
                    Task { await viewModel.selectCamera(cameraID) }
                }
            )
        ) {
            ForEach(viewModel.cameras) { camera in
                Text(camera.name).tag(camera.id)
            }
        }
        .pickerStyle(.menu)
    }
}

struct DiskUsageView: View {
    let disk: DiskStatus

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ProgressView(value: disk.usedFraction)
                .tint(.accentColor)

            HStack {
                Label(PlainNVRFormat.bytes(disk.used), systemImage: "externaldrive.fill")
                Spacer()
                Text("\(PlainNVRFormat.bytes(disk.free)) free")
                    .foregroundStyle(.secondary)
            }
            .font(.footnote)
        }
        .accessibilityElement(children: .combine)
    }
}

struct CameraRow: View {
    let camera: Camera
    let recorder: RecorderState?

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: recorder?.running == true ? "record.circle.fill" : "video.circle")
                .font(.title2)
                .foregroundStyle(recorder?.running == true ? .red : .secondary)

            VStack(alignment: .leading, spacing: 4) {
                Text(camera.name)
                    .font(.headline)
                    .lineLimit(1)

                HStack(spacing: 8) {
                    Label(camera.enabled ? "Enabled" : "Disabled", systemImage: camera.enabled ? "checkmark.circle" : "pause.circle")
                    Text(camera.shortRetention)
                    Text("\(camera.segmentSeconds)s")
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            Spacer()
        }
        .contentShape(Rectangle())
    }
}

struct EventRow: View {
    let event: RecorderEvent

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Label(event.message, systemImage: event.level == "error" ? "exclamationmark.triangle" : "info.circle")
                .foregroundStyle(event.level == "error" ? .red : .primary)
            Text(PlainNVRFormat.displayDateTime(event.createdAt))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}

struct CoverageView: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel
    let coverage: RecordingCoverage

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("\(coverage.count)", systemImage: "film.stack")
                Spacer()
                Text(PlainNVRFormat.bytes(coverage.totalSize))
                    .foregroundStyle(.secondary)
            }

            if let oldest = coverage.oldest, let newest = coverage.newest {
                Text("\(PlainNVRFormat.displayDateTime(oldest)) to \(PlainNVRFormat.displayDateTime(newest))")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            if !coverage.dates.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack {
                        ForEach(Array(coverage.dates.suffix(14).reversed()), id: \.self) { date in
                            Button {
                                viewModel.selectedRecordingDate = PlainNVRFormat.date(fromAPI: date) ?? Date()
                                Task { await viewModel.refreshCoverageAndSegments() }
                            } label: {
                                Text(PlainNVRFormat.displayDate(date))
                                    .font(.caption)
                            }
                            .buttonStyle(.bordered)
                        }
                    }
                }
            }
        }
    }
}

struct SegmentRow: View {
    let segment: RecordingSegment

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "play.circle.fill")
                .font(.title2)
                .foregroundStyle(Color.accentColor)

            VStack(alignment: .leading, spacing: 4) {
                Text(PlainNVRFormat.displayTime(segment.start))
                    .font(.headline)
                Text("\(PlainNVRFormat.displayTime(segment.start)) to \(PlainNVRFormat.displayTime(segment.approxEnd))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Text(PlainNVRFormat.bytes(segment.size))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .contentShape(Rectangle())
    }
}

extension View {
    @ViewBuilder
    func plainNVRURLInput() -> some View {
        #if os(iOS)
        self
            .keyboardType(.URL)
            .textContentType(.URL)
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
        #else
        self
        #endif
    }

    @ViewBuilder
    func plainNVRUsernameInput() -> some View {
        #if os(iOS)
        self
            .textContentType(.username)
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
        #else
        self
        #endif
    }

    @ViewBuilder
    func plainNVRPasswordInput(isNewPassword: Bool) -> some View {
        #if os(iOS)
        self.textContentType(isNewPassword ? .newPassword : .password)
        #else
        self
        #endif
    }

    @ViewBuilder
    func plainNVRInlineNavigationTitle() -> some View {
        #if os(iOS)
        self.navigationBarTitleDisplayMode(.inline)
        #else
        self
        #endif
    }

    @ViewBuilder
    func plainNVRLiveChromeHidden(_ hidden: Bool) -> some View {
        #if os(iOS)
        self
            .toolbar(hidden ? .hidden : .visible, for: .navigationBar)
            .toolbar(hidden ? .hidden : .visible, for: .tabBar)
            .statusBarHidden(hidden)
        #else
        self
        #endif
    }
}
