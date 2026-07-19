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
            Form {
                Section("Server") {
                    TextField("http://192.168.1.172:8787", text: $viewModel.serverAddress)
                        .keyboardType(.URL)
                        .textContentType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }

                Section(viewModel.setupRequired ? "Create Account" : "Sign In") {
                    TextField("Username", text: $viewModel.username)
                        .textContentType(.username)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()

                    SecureField("Password", text: $viewModel.password)
                        .textContentType(viewModel.setupRequired ? .newPassword : .password)

                    Button {
                        Task { await viewModel.connectOrSignIn() }
                    } label: {
                        Label(viewModel.setupRequired ? "Create Account" : "Sign In", systemImage: "person.crop.circle.badge.checkmark")
                    }
                    .disabled(viewModel.isBusy)
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
                .tabItem { Label("Cameras", systemImage: "video") }

            LiveView()
                .tabItem { Label("Live", systemImage: "dot.radiowaves.left.and.right") }

            RecordingsView()
                .tabItem { Label("Recordings", systemImage: "play.rectangle") }

            SettingsView()
                .tabItem { Label("Settings", systemImage: "gearshape") }
        }
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

    private var recorderIsRunning: Bool {
        recorder?.running == true && recorder?.paused != true
    }

    var body: some View {
        List {
            Section("Status") {
                Label(camera.enabled ? "Enabled" : "Disabled", systemImage: camera.enabled ? "checkmark.circle" : "pause.circle")
                Label(recorderIsRunning ? "Recording" : (recorder?.paused == true ? "Paused" : "Idle"), systemImage: recorderIsRunning ? "record.circle" : "moon")

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

            Section("Controls") {
                Toggle(
                    isOn: Binding(
                        get: { recorderIsRunning },
                        set: { isRunning in
                            Task { await viewModel.setRecorderRunning(isRunning, camera: camera) }
                        }
                    )
                ) {
                    Label("Recorder", systemImage: recorderIsRunning ? "record.circle" : "pause.circle")
                }
                .disabled(!camera.enabled)

                Button {
                    Task { await viewModel.restartRecorder(camera: camera) }
                } label: {
                    Label("Restart Recorder", systemImage: "arrow.clockwise.circle")
                }
                .disabled(!camera.enabled)
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
        .navigationBarTitleDisplayMode(.inline)
    }
}

struct LiveView: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel
    @Environment(\.verticalSizeClass) private var verticalSizeClass
    @State private var landscapeDigitalZoom: CGFloat = 1

    private var isLandscape: Bool {
        verticalSizeClass == .compact
    }

    var body: some View {
        NavigationStack {
            liveContent
            .navigationTitle("Live")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                if !isLandscape {
                    Button {
                        Task { await viewModel.restartLiveStream() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                }
            }
            .toolbar(isLandscape ? .hidden : .visible, for: .navigationBar)
            .toolbar(isLandscape ? .hidden : .visible, for: .tabBar)
            .statusBarHidden(isLandscape)
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
                LiveControlsView()
                    .padding(.horizontal)

                if let camera = viewModel.selectedCamera {
                    LivePlayerSurface(camera: camera)

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

            if let camera = viewModel.selectedCamera, viewModel.livePlaybackEnabled, let url = viewModel.liveURL(for: camera) {
                landscapeSurface(camera: camera, url: url)
                    .scaleEffect(landscapeDigitalZoom)
                    .ignoresSafeArea()

                if camera.supportsPTZ {
                    VStack {
                        Spacer()
                        HStack {
                            PTZVideoOverlay(camera: camera, digitalZoomAction: applyLandscapeDigitalZoom)
                                .padding(.leading, 14)
                                .padding(.bottom, 14)
                            Spacer()
                        }
                    }
                }

                if let message = viewModel.liveStatusMessage, !message.isEmpty {
                    VStack {
                        Text(message)
                            .font(.caption)
                            .foregroundStyle(.white)
                            .padding(10)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(.black.opacity(0.72), in: RoundedRectangle(cornerRadius: 8))
                            .padding()
                        Spacer()
                    }
                }
            } else if viewModel.selectedCamera != nil {
                ContentUnavailableView("Live Paused", systemImage: "pause.circle")
                    .foregroundStyle(.white)
            } else {
                ContentUnavailableView("Stream Unavailable", systemImage: "wifi.exclamationmark")
                    .foregroundStyle(.white)
            }
        }
        .ignoresSafeArea()
        .onChange(of: viewModel.selectedCamera?.id) { _, _ in
            landscapeDigitalZoom = 1
        }
    }

    @ViewBuilder
    private func landscapeSurface(camera: Camera, url: URL) -> some View {
        LivePlayerView(
            url: url,
            rotationDegrees: camera.normalizedViewRotation,
            onStatus: viewModel.updateLivePlayerStatus,
            onFailure: viewModel.updateLivePlayerFailure
        )
    }

    private func applyLandscapeDigitalZoom(_ action: String) {
        withAnimation(.spring(response: 0.22, dampingFraction: 0.82)) {
            switch action {
            case "zoom_in":
                landscapeDigitalZoom = min(4, landscapeDigitalZoom + 0.25)
            case "zoom_out":
                landscapeDigitalZoom = max(1, landscapeDigitalZoom - 0.25)
            default:
                landscapeDigitalZoom = 1
            }
        }
    }
}

struct LiveControlsView: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel

    var body: some View {
        VStack(spacing: 12) {
            HStack(spacing: 12) {
                CameraPicker(loadRecordings: false)

                Spacer()

                Toggle(
                    "Live",
                    isOn: Binding(
                        get: { viewModel.livePlaybackEnabled },
                        set: { enabled in
                            Task { await viewModel.setLivePlaybackEnabled(enabled) }
                        }
                    )
                )
            }

            HStack(spacing: 12) {
                Text(viewModel.selectedCamera?.liveModeLabel ?? "Live")
                    .font(.headline)
                    .foregroundStyle(.secondary)

                Button {
                    Task { await viewModel.restartLiveStream() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .accessibilityLabel("Restart Live")
                .buttonStyle(.bordered)
            }

        }
        .padding(12)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 8))
    }
}

struct PTZPressButton: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel

    let systemName: String
    let action: String
    let label: String
    let size: CGFloat
    let continuous: Bool
    var overlayStyle = false

    @State private var isPressed = false
    @State private var startTask: Task<Void, Never>?

    var body: some View {
        Image(systemName: systemName)
            .font(.system(size: overlayStyle ? 15 : 17, weight: .semibold))
            .foregroundStyle(.blue)
            .frame(width: size, height: size)
            .background(overlayStyle ? Color.black.opacity(0.62) : Color.secondary.opacity(0.08))
            .clipShape(RoundedRectangle(cornerRadius: overlayStyle ? size / 2 : 8))
            .overlay {
                if !overlayStyle {
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(.quaternary, lineWidth: 1)
                }
            }
            .scaleEffect(isPressed ? 0.92 : 1)
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in
                        guard !isPressed else { return }
                        isPressed = true
                        if continuous {
                            startTask = Task {
                                await viewModel.beginPTZ(action: action)
                            }
                        }
                    }
                    .onEnded { _ in
                        let pendingStart = startTask
                        isPressed = false
                        startTask = nil
                        if continuous {
                            Task {
                                await pendingStart?.value
                                await viewModel.stopPTZ()
                            }
                        } else {
                            Task { await viewModel.sendPTZ(action: action) }
                        }
                    }
            )
            .accessibilityLabel(label)
            .accessibilityAddTraits(.isButton)
            .accessibilityAction {
                Task { await viewModel.sendPTZ(action: action) }
            }
    }
}

struct PTZControlPad: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel

    private let columns = Array(repeating: GridItem(.fixed(46), spacing: 8), count: 3)

    var body: some View {
        let camera = viewModel.selectedCamera
        let directStepper = camera?.usesDirectStepperPTZ == true
        let showHardwareZoom = camera?.usesHardwareZoom == true

        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .center, spacing: 16) {
                if camera?.supportsPanTilt == true {
                    LazyVGrid(columns: columns, spacing: 8) {
                        ptzButton("arrow.up.left", action: "up_left", label: "Up Left")
                        ptzButton("arrow.up", action: "up", label: "Up")
                        ptzButton("arrow.up.right", action: "up_right", label: "Up Right")
                        ptzButton("arrow.left", action: "left", label: "Left")
                        if directStepper || camera?.supportsHomePosition != true {
                            Color.clear
                                .frame(width: 42, height: 42)
                                .accessibilityHidden(true)
                        } else {
                            ptzButton("house", action: "home", label: "Home")
                        }
                        ptzButton("arrow.right", action: "right", label: "Right")
                        ptzButton("arrow.down.left", action: "down_left", label: "Down Left")
                        ptzButton("arrow.down", action: "down", label: "Down")
                        ptzButton("arrow.down.right", action: "down_right", label: "Down Right")
                    }
                }

                if showHardwareZoom {
                    VStack(spacing: 8) {
                        ptzButton("plus.magnifyingglass", action: "zoom_in", label: "Zoom In")
                        ptzButton("stop.fill", action: "stop", label: "Stop")
                        ptzButton("minus.magnifyingglass", action: "zoom_out", label: "Zoom Out")
                    }
                }
            }

            if let presets = camera?.ptzPresets, !presets.isEmpty {
                Menu {
                    ForEach(presets) { preset in
                        Button(preset.name) {
                            Task { await viewModel.goToPreset(preset) }
                        }
                    }
                } label: {
                    Label("Go to Preset", systemImage: "viewfinder")
                }
                .buttonStyle(.bordered)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func ptzButton(_ systemName: String, action: String, label: String) -> some View {
        let continuous = viewModel.selectedCamera?.usesContinuousONVIF == true
            && !["home", "stop"].contains(action)
        return PTZPressButton(
            systemName: systemName,
            action: action,
            label: label,
            size: 42,
            continuous: continuous
        )
    }
}

struct LivePlayerSurface: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel
    let camera: Camera
    @State private var digitalZoom: CGFloat = 1

    var body: some View {
        VStack(spacing: 8) {
            if viewModel.livePlaybackEnabled, let url = viewModel.liveURL(for: camera) {
                liveSurface(url: url)
                .scaleEffect(digitalZoom)
                .frame(maxWidth: .infinity)
                .aspectRatio(16 / 9, contentMode: .fit)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .overlay {
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(.quaternary, lineWidth: 1)
                }
                .overlay(alignment: .bottomLeading) {
                    if camera.supportsPTZ {
                        PTZVideoOverlay(camera: camera, digitalZoomAction: applyDigitalZoom)
                            .padding(8)
                    }
                }

                if let message = viewModel.liveStatusMessage, !message.isEmpty {
                    Text(message)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                }
            } else {
                ContentUnavailableView("Live Paused", systemImage: "pause.circle")
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity)
                    .background(.black)
                    .aspectRatio(16 / 9, contentMode: .fit)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .overlay {
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(.quaternary, lineWidth: 1)
                    }
            }
        }
        .padding(.horizontal)
        .onChange(of: camera.id) { _, _ in
            digitalZoom = 1
        }
    }

    @ViewBuilder
    private func liveSurface(url: URL) -> some View {
        LivePlayerView(
            url: url,
            rotationDegrees: camera.normalizedViewRotation,
            onStatus: viewModel.updateLivePlayerStatus,
            onFailure: viewModel.updateLivePlayerFailure
        )
    }

    private func applyDigitalZoom(_ action: String) {
        withAnimation(.spring(response: 0.22, dampingFraction: 0.82)) {
            switch action {
            case "zoom_in":
                digitalZoom = min(4, digitalZoom + 0.25)
            case "zoom_out":
                digitalZoom = max(1, digitalZoom - 0.25)
            default:
                digitalZoom = 1
            }
        }
    }
}

struct PTZVideoOverlay: View {
    @EnvironmentObject private var viewModel: PlainNVRViewModel
    let camera: Camera
    var digitalZoomAction: (String) -> Void = { _ in }

    private let columns = Array(repeating: GridItem(.fixed(34), spacing: 4), count: 3)

    var body: some View {
        let directStepper = camera.usesDirectStepperPTZ
        let showZoom = camera.usesDigitalZoom || camera.usesHardwareZoom

        HStack(alignment: .bottom, spacing: 8) {
            if camera.supportsPanTilt {
                LazyVGrid(columns: columns, spacing: 4) {
                    ptzButton("arrow.up.left", action: "up_left", label: "Up Left")
                    ptzButton("arrow.up", action: "up", label: "Up")
                    ptzButton("arrow.up.right", action: "up_right", label: "Up Right")
                    ptzButton("arrow.left", action: "left", label: "Left")
                    if directStepper || !camera.supportsHomePosition {
                        Color.clear
                            .frame(width: 34, height: 34)
                            .accessibilityHidden(true)
                    } else {
                        ptzButton("house", action: "home", label: "Home")
                    }
                    ptzButton("arrow.right", action: "right", label: "Right")
                    ptzButton("arrow.down.left", action: "down_left", label: "Down Left")
                    ptzButton("arrow.down", action: "down", label: "Down")
                    ptzButton("arrow.down.right", action: "down_right", label: "Down Right")
                }
            }

            if showZoom {
                VStack(spacing: 4) {
                    zoomButton("plus.magnifyingglass", action: "zoom_in", label: "Zoom In")
                    zoomButton("stop.fill", action: "stop", label: camera.usesDigitalZoom ? "Reset Zoom" : "Stop")
                    zoomButton("minus.magnifyingglass", action: "zoom_out", label: "Zoom Out")
                }
            }
        }
        .padding(6)
        .background(.black.opacity(0.38), in: RoundedRectangle(cornerRadius: 8))
    }

    private func ptzButton(_ systemName: String, action: String, label: String) -> some View {
        PTZPressButton(
            systemName: systemName,
            action: action,
            label: label,
            size: 34,
            continuous: camera.usesContinuousONVIF && !["home", "stop"].contains(action),
            overlayStyle: true
        )
    }

    @ViewBuilder
    private func zoomButton(_ systemName: String, action: String, label: String) -> some View {
        if camera.usesDigitalZoom {
            Button {
                digitalZoomAction(action)
            } label: {
                Image(systemName: systemName)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(.blue)
                    .frame(width: 34, height: 34)
                    .background(.black.opacity(0.62), in: Circle())
            }
            .accessibilityLabel(label)
            .buttonStyle(.plain)
        } else {
            PTZPressButton(
                systemName: systemName,
                action: action,
                label: label,
                size: 34,
                continuous: camera.usesContinuousONVIF && action != "stop",
                overlayStyle: true
            )
        }
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
                        CameraPicker(loadRecordings: true)
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
                    Task { await viewModel.refreshAll(includeRecordings: true) }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .disabled(viewModel.isBusy)
            }
            .task {
                await viewModel.loadRecordingBrowserIfNeeded()
            }
            .sheet(item: $viewModel.activeSegment) { segment in
                if let url = viewModel.playbackURL(for: segment) {
                    SegmentPlayerView(
                        url: url,
                        title: PlainNVRFormat.displayTime(segment.start),
                        segment: segment,
                        rotationDegrees: viewModel.cameras.first { $0.id == segment.cameraId }?.normalizedViewRotation ?? 0
                    )
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
                Section("Server") {
                    TextField("Server URL", text: $viewModel.serverAddress)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()

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
    var loadRecordings = false

    var body: some View {
        Picker(
            "Camera",
            selection: Binding(
                get: { viewModel.selectedCameraID ?? viewModel.cameras.first?.id ?? "" },
                set: { cameraID in
                    Task { await viewModel.selectCamera(cameraID, loadRecordings: loadRecordings) }
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
