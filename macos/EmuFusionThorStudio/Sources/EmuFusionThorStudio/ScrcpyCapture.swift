import AppKit
import CoreImage
import CoreMedia
import Foundation
import ScreenCaptureKit

protocol AndroidAudioConsumer: AnyObject {
    func consumeAndroidAudio(_ sampleBuffer: CMSampleBuffer)
}

final class ScrcpyProcess: @unchecked Sendable {
    enum Display { case top, bottom }

    let display: Display
    let windowTitle: String
    private let bridge: ADBBridge
    private var process: Process?

    init(display: Display, bridge: ADBBridge) {
        self.display = display
        self.bridge = bridge
        self.windowTitle = display == .top ? "EmuFusion Thor • Top Feed" : "EmuFusion Thor • Lower Feed"
    }

    func start() throws {
        stop()
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/opt/homebrew/bin/scrcpy")
        let displayID = display == .top ? "0" : "4"
        let dimensions = display == .top ? ["--window-width=1920", "--window-height=1080"] : ["--window-width=1240", "--window-height=1080"]
        var arguments = [
            "-s", bridge.serial, "--display-id=\(displayID)", "--no-control", "--no-power-on",
            "--no-clipboard-autosync", "--window-borderless", "--window-title=\(windowTitle)",
            "--window-x=-5000", "--window-y=100", "--max-fps=120", "--video-bit-rate=32M",
            "--video-codec=h265", "--no-mipmaps"
        ] + dimensions
        if display == .top {
            // Playback capture + duplication records the Thor without muting its speakers.
            arguments += ["--audio-source=playback", "--audio-codec=raw", "--audio-dup", "--audio-buffer=20"]
        } else {
            arguments += ["--no-audio"]
        }
        process.arguments = arguments
        var environment = ProcessInfo.processInfo.environment
        environment["ADB"] = bridge.adbPath
        environment["PATH"] = "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        process.environment = environment
        process.standardOutput = Pipe()
        process.standardError = Pipe()
        try process.run()
        self.process = process
    }

    func stop() {
        guard let process else { return }
        process.terminate()
        self.process = nil
    }
}

final class WindowCaptureFeed: NSObject, SCStreamOutput, SCStreamDelegate, @unchecked Sendable {
    enum Kind { case top, bottom }

    private let kind: Kind
    private let state: StudioState
    private let ciContext = CIContext(options: [.cacheIntermediates: false])
    private var stream: SCStream?
    weak var audioConsumer: AndroidAudioConsumer?
    var onError: ((String) -> Void)?
    private var accentCounter = 0

    init(kind: Kind, state: StudioState) {
        self.kind = kind
        self.state = state
    }

    @MainActor
    func start(window: SCWindow, fps: Double) async throws {
        let filter = SCContentFilter(desktopIndependentWindow: window)
        let configuration = SCStreamConfiguration()
        if kind == .top {
            configuration.width = 1920; configuration.height = 1080
            configuration.capturesAudio = true
            configuration.sampleRate = 48_000
            configuration.channelCount = 2
            configuration.excludesCurrentProcessAudio = true
        } else {
            configuration.width = 1240; configuration.height = 1080
            configuration.capturesAudio = false
        }
        configuration.pixelFormat = kCVPixelFormatType_32BGRA
        configuration.minimumFrameInterval = CMTime(value: 1, timescale: CMTimeScale(max(24, min(120, fps))))
        configuration.queueDepth = 6
        configuration.showsCursor = false
        let stream = SCStream(filter: filter, configuration: configuration, delegate: self)
        try stream.addStreamOutput(self, type: .screen, sampleHandlerQueue: DispatchQueue(label: "com.emufusion.thorstudio.capture.\(kind)"))
        if kind == .top {
            try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: DispatchQueue(label: "com.emufusion.thorstudio.android-audio"))
        }
        self.stream = stream
        try await stream.startCapture()
    }

    func stop() {
        guard let stream else { return }
        Task { try? await stream.stopCapture() }
        self.stream = nil
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of outputType: SCStreamOutputType) {
        guard sampleBuffer.isValid else { return }
        if outputType == .audio {
            audioConsumer?.consumeAndroidAudio(sampleBuffer)
            return
        }
        guard outputType == .screen,
              let imageBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let image = CIImage(cvPixelBuffer: imageBuffer)
        guard let cgImage = ciContext.createCGImage(image, from: image.extent) else { return }
        if kind == .top {
            state.setTopFrame(cgImage)
            accentCounter += 1
            if accentCounter >= 20 {
                accentCounter = 0
                if let accent = AccentSampler.sample(from: cgImage) { state.applySampledAccent(accent) }
            }
        } else {
            state.setBottomFrame(cgImage)
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: any Error) {
        onError?(error.localizedDescription)
    }
}

@MainActor
final class ScrcpyCaptureCoordinator {
    private let bridge: ADBBridge
    private let state: StudioState
    private let topProcess: ScrcpyProcess
    private let bottomProcess: ScrcpyProcess
    private let topFeed: WindowCaptureFeed
    private let bottomFeed: WindowCaptureFeed
    weak var audioConsumer: AndroidAudioConsumer? {
        didSet { topFeed.audioConsumer = audioConsumer }
    }
    var onStatus: ((String) -> Void)?

    init(bridge: ADBBridge, state: StudioState) {
        self.bridge = bridge
        self.state = state
        topProcess = ScrcpyProcess(display: .top, bridge: bridge)
        bottomProcess = ScrcpyProcess(display: .bottom, bridge: bridge)
        topFeed = WindowCaptureFeed(kind: .top, state: state)
        bottomFeed = WindowCaptureFeed(kind: .bottom, state: state)
    }

    func start() {
        guard bridge.isConnected() else { onStatus?("Thor not connected"); return }
        let fps = bridge.activeRefreshRate()
        state.setRefreshRate(fps)
        do {
            try topProcess.start(); try bottomProcess.start()
        } catch {
            onStatus?("Unable to start read-only Thor feeds: \(error.localizedDescription)")
            return
        }
        onStatus?("Starting \(Int(fps.rounded())) fps Thor feeds…")
        Task {
            do {
                let windows = try await waitForWindows()
                try await topFeed.start(window: windows.top, fps: fps)
                try await bottomFeed.start(window: windows.bottom, fps: fps)
                onStatus?("Live • \(Int(fps.rounded())) fps • Android stereo")
            } catch {
                onStatus?("Screen Recording permission is required: \(error.localizedDescription)")
            }
        }
    }

    func stop() {
        topFeed.stop(); bottomFeed.stop()
        topProcess.stop(); bottomProcess.stop()
    }

    private func waitForWindows() async throws -> (top: SCWindow, bottom: SCWindow) {
        for _ in 0..<24 {
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
            let top = content.windows.first { $0.title == topProcess.windowTitle }
            let bottom = content.windows.first { $0.title == bottomProcess.windowTitle }
            if let top, let bottom { return (top, bottom) }
            try await Task.sleep(for: .milliseconds(250))
        }
        throw NSError(domain: "EmuFusionThorStudio", code: 12, userInfo: [NSLocalizedDescriptionKey: "Timed out waiting for hidden scrcpy feeds"])
    }
}

enum AccentSampler {
    static func sample(from image: CGImage) -> NSColor? {
        let width = 40, height = 24
        var pixels = [UInt8](repeating: 0, count: width * height * 4)
        guard let context = CGContext(data: &pixels, width: width, height: height, bitsPerComponent: 8,
                                      bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
                                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
        context.interpolationQuality = .low
        context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
        var bins = [(weight: Double, r: Double, g: Double, b: Double)](repeating: (0, 0, 0, 0), count: 24)
        for index in stride(from: 0, to: pixels.count, by: 4) {
            let r = Double(pixels[index]) / 255, g = Double(pixels[index + 1]) / 255, b = Double(pixels[index + 2]) / 255
            let maxV = max(r, g, b), minV = min(r, g, b), delta = maxV - minV
            guard maxV > 0.28, delta > 0.16 else { continue }
            let hue: Double
            if delta == 0 { hue = 0 }
            else if maxV == r { hue = ((g - b) / delta).truncatingRemainder(dividingBy: 6) / 6 }
            else if maxV == g { hue = ((b - r) / delta + 2) / 6 }
            else { hue = ((r - g) / delta + 4) / 6 }
            let wrappedHue = hue < 0 ? hue + 1 : hue
            let bin = min(23, max(0, Int(wrappedHue * 24)))
            let weight = delta * (0.35 + maxV)
            bins[bin].weight += weight; bins[bin].r += r * weight; bins[bin].g += g * weight; bins[bin].b += b * weight
        }
        guard let best = bins.max(by: { $0.weight < $1.weight }), best.weight > 1 else { return nil }
        return NSColor(calibratedRed: best.r / best.weight, green: best.g / best.weight, blue: best.b / best.weight, alpha: 1)
    }
}
