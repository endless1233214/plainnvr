import AVFAudio
@preconcurrency import WebRTC

/// WebRTC's default iOS VoiceProcessingIO device opens an input even for a
/// receive-only peer. This device only connects a source node to the output.
/// All control methods run on WebRTC's audio thread; rendering is real-time.
final class PlaybackAudioDevice: NSObject, RTCAudioDevice {
    private var delegate: RTCAudioDeviceDelegate?
    private var engine: AVAudioEngine?
    private var observers: [NSObjectProtocol] = []
    private var interrupted = false
    private(set) var isInitialized = false
    private(set) var isPlayoutInitialized = false
    private(set) var isPlaying = false

    let deviceInputSampleRate: Double = 48_000
    let inputIOBufferDuration: TimeInterval = 0.01
    let inputNumberOfChannels = 1
    let inputLatency: TimeInterval = 0
    let deviceOutputSampleRate: Double = 48_000
    var outputIOBufferDuration: TimeInterval { AVAudioSession.sharedInstance().ioBufferDuration }
    let outputNumberOfChannels = 1
    var outputLatency: TimeInterval { AVAudioSession.sharedInstance().outputLatency }
    let isRecordingInitialized = false
    let isRecording = false

    func initialize(with delegate: RTCAudioDeviceDelegate) -> Bool {
        self.delegate = delegate
        isInitialized = true
        return true
    }

    func initializePlayout() -> Bool {
        guard !isPlayoutInitialized else { return true }
        guard let delegate, let format = AVAudioFormat(
            standardFormatWithSampleRate: deviceOutputSampleRate,
            channels: AVAudioChannelCount(outputNumberOfChannels)
        ) else { return false }
        let samples = PlaybackSamples()
        let getPlayout = delegate.getPlayoutData
        let source = AVAudioSourceNode(format: format) { _, timestamp, frames, output in
            let buffers = UnsafeMutableAudioBufferListPointer(output)
            // Bound the scratch buffer, and always initialize the output even
            // if WebRTC has no PCM yet or the hardware requests a large block.
            for buffer in buffers {
                if let data = buffer.mData { memset(data, 0, Int(buffer.mDataByteSize)) }
            }
            guard frames <= samples.capacity else { return noErr }
            var flags = AudioUnitRenderActionFlags()
            var pcm = AudioBufferList(mNumberBuffers: 1, mBuffers: AudioBuffer(
                mNumberChannels: 1, mDataByteSize: frames * 2, mData: samples.pointer
            ))
            let result = getPlayout(&flags, timestamp, 0, frames, &pcm)
            guard result == noErr else { return result }
            for buffer in buffers {
                guard let data = buffer.mData else { continue }
                let floats = data.assumingMemoryBound(to: Float.self)
                let count = min(Int(frames), Int(buffer.mDataByteSize) / MemoryLayout<Float>.size)
                for index in 0..<count { floats[index] = Float(samples.pointer[index]) / 32768 }
            }
            return noErr
        }
        let engine = AVAudioEngine()
        engine.attach(source)
        engine.connect(source, to: engine.mainMixerNode, format: format)
        self.engine = engine
        observers.append(NotificationCenter.default.addObserver(
            forName: .AVAudioEngineConfigurationChange, object: engine, queue: nil
        ) { [weak self, weak delegate] _ in
            delegate?.dispatchAsync { [weak self] in self?.resumeAfterConfigurationChange() }
        })
        observers.append(NotificationCenter.default.addObserver(
            forName: AVAudioSession.interruptionNotification, object: nil, queue: nil
        ) { [weak self, weak delegate] notification in
            let type = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
            delegate?.dispatchAsync { [weak self] in
                guard let self else { return }
                self.interrupted = type == AVAudioSession.InterruptionType.began.rawValue
                if self.interrupted { self.engine?.stop() }
                else { self.resumeAfterConfigurationChange() }
            }
        })
        isPlayoutInitialized = true
        return true
    }

    func startPlayout() -> Bool {
        guard let engine else { return false }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playback, mode: .moviePlayback)
            try session.setPreferredIOBufferDuration(0.01)
            try session.setActive(true)
            delegate?.notifyAudioOutputParametersChange()
            delegate?.notifyAudioOutputInterrupted()
            try engine.start()
            isPlaying = true
            return true
        } catch {
            return false
        }
    }

    func stopPlayout() -> Bool {
        isPlaying = false
        engine?.stop()
        delegate?.notifyAudioOutputInterrupted()
        // AVPlayer shares this session during fallback; do not deactivate it.
        return true
    }

    private func resumeAfterConfigurationChange() {
        guard isPlaying, !interrupted, let engine, !engine.isRunning else { return }
        _ = startPlayout()
    }

    func terminateDevice() -> Bool {
        _ = stopPlayout()
        for observer in observers { NotificationCenter.default.removeObserver(observer) }
        observers = []
        engine = nil
        delegate = nil
        isInitialized = false
        isPlayoutInitialized = false
        interrupted = false
        return true
    }

    func initializeRecording() -> Bool { false }
    func startRecording() -> Bool { false }
    func stopRecording() -> Bool { true }
}

private final class PlaybackSamples {
    let capacity: UInt32 = 16_384
    let pointer: UnsafeMutablePointer<Int16>
    init() {
        pointer = .allocate(capacity: Int(capacity))
        pointer.initialize(repeating: 0, count: Int(capacity))
    }
    deinit { pointer.deallocate() }
}
