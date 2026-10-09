import AVFoundation
import AppKit
import CoreMedia
import CoreVideo
import Foundation

final class MicCapture: @unchecked Sendable {
    private let engine = AVAudioEngine()
    private var file: AVAudioFile?
    private(set) var voiceProcessingActive = false

    func start(to url: URL, voiceIsolation: Bool) throws {
        let input = engine.inputNode
        if voiceIsolation {
            do {
                try input.setVoiceProcessingEnabled(true)
                voiceProcessingActive = true
            } catch {
                voiceProcessingActive = false
            }
        }
        let format = input.outputFormat(forBus: 0)
        file = try AVAudioFile(forWriting: url, settings: format.settings)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
            try? self?.file?.write(from: buffer)
        }
        try engine.start()
    }

    func stop() {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        if voiceProcessingActive { try? engine.inputNode.setVoiceProcessingEnabled(false) }
        file = nil
        voiceProcessingActive = false
    }
}

final class RecordingEngine: AndroidAudioConsumer, @unchecked Sendable {
    private final class SendableSample: @unchecked Sendable {
        let value: CMSampleBuffer
        init(_ value: CMSampleBuffer) { self.value = value }
    }
    private let renderer: ThorRenderer
    private let state: StudioState
    private let queue = DispatchQueue(label: "com.emufusion.thorstudio.recorder", qos: .userInitiated)
    private var writer: AVAssetWriter?
    private var videoInput: AVAssetWriterInput?
    private var audioInput: AVAssetWriterInput?
    private var adaptor: AVAssetWriterInputPixelBufferAdaptor?
    private var timer: DispatchSourceTimer?
    private var frameIndex: Int64 = 0
    private var fps: Int32 = 120
    private var firstAndroidAudioPTS: CMTime?
    private var intermediateURL: URL?
    private var finalURL: URL?
    private var micURL: URL?
    private let micCapture = MicCapture()
    private var micEnabled = false
    private var recording = false
    var onStatus: ((String) -> Void)?
    var onFinished: ((URL?, String?) -> Void)?

    init(renderer: ThorRenderer, state: StudioState) {
        self.renderer = renderer
        self.state = state
    }

    func start(outputURL: URL, includeMic: Bool, voiceIsolation: Bool) throws {
        guard !recording else { return }
        let actualFPS = Int32(state.snapshot().refreshRate.rounded())
        fps = max(24, min(120, actualFPS))
        finalURL = outputURL
        let folder = outputURL.deletingLastPathComponent()
        let stem = outputURL.deletingPathExtension().lastPathComponent
        intermediateURL = folder.appendingPathComponent(".\(stem)-android.mov")
        micURL = folder.appendingPathComponent(".\(stem)-mic.caf")
        if let intermediateURL { try? FileManager.default.removeItem(at: intermediateURL) }
        try? FileManager.default.removeItem(at: outputURL)

        let writer = try AVAssetWriter(outputURL: intermediateURL!, fileType: .mov)
        let videoSettings: [String: Any] = [
            AVVideoCodecKey: AVVideoCodecType.hevc,
            AVVideoWidthKey: 1920,
            AVVideoHeightKey: 1080,
            AVVideoCompressionPropertiesKey: [
                AVVideoAverageBitRateKey: fps >= 100 ? 52_000_000 : 32_000_000,
                AVVideoExpectedSourceFrameRateKey: fps,
                AVVideoMaxKeyFrameIntervalKey: fps * 2,
                AVVideoAllowFrameReorderingKey: false
            ]
        ]
        let videoInput = AVAssetWriterInput(mediaType: .video, outputSettings: videoSettings)
        videoInput.expectsMediaDataInRealTime = true
        let attributes: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
            kCVPixelBufferWidthKey as String: 1920,
            kCVPixelBufferHeightKey as String: 1080,
            kCVPixelBufferIOSurfacePropertiesKey as String: [:]
        ]
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: videoInput, sourcePixelBufferAttributes: attributes)
        let audioSettings: [String: Any] = [
            AVFormatIDKey: kAudioFormatMPEG4AAC,
            AVSampleRateKey: 48_000,
            AVNumberOfChannelsKey: 2,
            AVEncoderBitRateKey: 256_000
        ]
        let audioInput = AVAssetWriterInput(mediaType: .audio, outputSettings: audioSettings)
        audioInput.expectsMediaDataInRealTime = true
        guard writer.canAdd(videoInput), writer.canAdd(audioInput) else {
            throw NSError(domain: "EmuFusionThorStudio", code: 30, userInfo: [NSLocalizedDescriptionKey: "The Mac could not configure the HEVC/stereo recorder"])
        }
        writer.add(videoInput); writer.add(audioInput)
        guard writer.startWriting() else { throw writer.error ?? NSError(domain: "EmuFusionThorStudio", code: 31) }
        writer.startSession(atSourceTime: .zero)
        self.writer = writer; self.videoInput = videoInput; self.audioInput = audioInput; self.adaptor = adaptor
        frameIndex = 0; firstAndroidAudioPTS = nil; recording = true; micEnabled = includeMic

        if includeMic, let micURL {
            try? FileManager.default.removeItem(at: micURL)
            try micCapture.start(to: micURL, voiceIsolation: voiceIsolation)
        }
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now(), repeating: 1.0 / Double(fps), leeway: .microseconds(300))
        timer.setEventHandler { [weak self] in self?.appendVideoFrame() }
        self.timer = timer
        timer.resume()
        onStatus?("Recording • \(fps) fps • Android stereo\(includeMic ? " + mic" : "")")
    }

    func stop() {
        guard recording else { return }
        recording = false
        timer?.cancel(); timer = nil
        micCapture.stop()
        queue.async { [weak self] in
            guard let self else { return }
            self.videoInput?.markAsFinished(); self.audioInput?.markAsFinished()
            self.writer?.finishWriting {
                self.finishFile()
            }
        }
    }

    func consumeAndroidAudio(_ sampleBuffer: CMSampleBuffer) {
        let sample = SendableSample(sampleBuffer)
        queue.async { [weak self] in
            guard let self, self.recording, let input = self.audioInput, input.isReadyForMoreMediaData else { return }
            let pts = CMSampleBufferGetPresentationTimeStamp(sample.value)
            if self.firstAndroidAudioPTS == nil { self.firstAndroidAudioPTS = pts }
            guard let origin = self.firstAndroidAudioPTS,
                  let shifted = self.retimed(sample.value, subtracting: origin) else { return }
            input.append(shifted)
        }
    }

    private func appendVideoFrame() {
        guard recording, let input = videoInput, input.isReadyForMoreMediaData,
              let adaptor, let pool = adaptor.pixelBufferPool else { return }
        var buffer: CVPixelBuffer?
        guard CVPixelBufferPoolCreatePixelBuffer(nil, pool, &buffer) == kCVReturnSuccess,
              let pixelBuffer = buffer else { return }
        CVPixelBufferLockBaseAddress(pixelBuffer, [])
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, []) }
        guard let base = CVPixelBufferGetBaseAddress(pixelBuffer),
              let context = CGContext(data: base, width: 1920, height: 1080, bitsPerComponent: 8,
                                      bytesPerRow: CVPixelBufferGetBytesPerRow(pixelBuffer),
                                      space: CGColorSpaceCreateDeviceRGB(),
                                      bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue) else { return }
        context.translateBy(x: 0, y: 1080); context.scaleBy(x: 1, y: -1)
        renderer.draw(in: context, size: CGSize(width: 1920, height: 1080))
        let time = CMTime(value: frameIndex, timescale: fps)
        if adaptor.append(pixelBuffer, withPresentationTime: time) { frameIndex += 1 }
    }

    private func retimed(_ sample: CMSampleBuffer, subtracting origin: CMTime) -> CMSampleBuffer? {
        var count = 0
        guard CMSampleBufferGetSampleTimingInfoArray(sample, entryCount: 0, arrayToFill: nil, entriesNeededOut: &count) == noErr else { return nil }
        var timing = [CMSampleTimingInfo](repeating: CMSampleTimingInfo(), count: count)
        guard CMSampleBufferGetSampleTimingInfoArray(sample, entryCount: count, arrayToFill: &timing, entriesNeededOut: &count) == noErr else { return nil }
        for index in timing.indices {
            timing[index].presentationTimeStamp = CMTimeSubtract(timing[index].presentationTimeStamp, origin)
            if timing[index].decodeTimeStamp.isValid { timing[index].decodeTimeStamp = CMTimeSubtract(timing[index].decodeTimeStamp, origin) }
        }
        var copy: CMSampleBuffer?
        let status = CMSampleBufferCreateCopyWithNewTiming(allocator: kCFAllocatorDefault, sampleBuffer: sample,
                                                            sampleTimingEntryCount: timing.count, sampleTimingArray: &timing,
                                                            sampleBufferOut: &copy)
        return status == noErr ? copy : nil
    }

    private func finishFile() {
        guard let intermediateURL, let finalURL else { return }
        if micEnabled, let micURL, FileManager.default.fileExists(atPath: micURL.path) {
            mixWithFFmpeg(video: intermediateURL, mic: micURL, output: finalURL)
        } else {
            do {
                try? FileManager.default.removeItem(at: finalURL)
                try FileManager.default.moveItem(at: intermediateURL, to: finalURL)
                onFinished?(finalURL, nil)
            } catch { onFinished?(nil, error.localizedDescription) }
        }
    }

    private func mixWithFFmpeg(video: URL, mic: URL, output: URL) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/opt/homebrew/bin/ffmpeg")
        process.arguments = [
            "-y", "-i", video.path, "-i", mic.path,
            "-filter_complex", "[1:a]highpass=f=90,lowpass=f=12500,acompressor=threshold=-24dB:ratio=3:attack=8:release=140[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]",
            "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", output.path
        ]
        process.standardOutput = Pipe(); process.standardError = Pipe()
        do {
            try process.run(); process.waitUntilExit()
            guard process.terminationStatus == 0 else { throw NSError(domain: "EmuFusionThorStudio", code: 40, userInfo: [NSLocalizedDescriptionKey: "ffmpeg could not mix the microphone track"] ) }
            try? FileManager.default.removeItem(at: video); try? FileManager.default.removeItem(at: mic)
            onFinished?(output, nil)
        } catch { onFinished?(nil, error.localizedDescription) }
    }
}
