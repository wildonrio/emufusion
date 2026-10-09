import AppKit
import AVFoundation
import Foundation

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private var window: NSWindow!
    private let state = StudioState()
    private let bridge = ADBBridge()
    private lazy var renderer = ThorRenderer(state: state)
    private lazy var compositeView = ThorCompositeView(renderer: renderer)
    private lazy var capture = ScrcpyCaptureCoordinator(bridge: bridge, state: state)
    private lazy var inputMonitor = InputEventMonitor(bridge: bridge, state: state)
    private lazy var recorder = RecordingEngine(renderer: renderer, state: state)
    private let statusLabel = NSTextField(labelWithString: "Ready")
    private let recordButton = NSButton(title: "Record", target: nil, action: nil)
    private let connectButton = NSButton(title: "Connect Thor", target: nil, action: nil)
    private let micCheckbox = NSButton(checkboxWithTitle: "Mac microphone", target: nil, action: nil)
    private let isolationCheckbox = NSButton(checkboxWithTitle: "Voice isolation", target: nil, action: nil)
    private let autoAccentCheckbox = NSButton(checkboxWithTitle: "Match accent automatically", target: nil, action: nil)
    private let colorWell = NSColorWell()
    private var isRecording = false
    private var isConnected = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        buildMenu()
        buildWindow()
        capture.audioConsumer = recorder
        capture.onStatus = { [weak self] text in DispatchQueue.main.async { self?.statusLabel.stringValue = text } }
        recorder.onStatus = { [weak self] text in DispatchQueue.main.async { self?.statusLabel.stringValue = text } }
        recorder.onFinished = { [weak self] url, error in
            DispatchQueue.main.async {
                self?.isRecording = false
                self?.recordButton.title = "Record"
                self?.recordButton.contentTintColor = nil
                if let url {
                    self?.statusLabel.stringValue = "Saved • \(url.lastPathComponent)"
                    NSWorkspace.shared.activateFileViewerSelecting([url])
                } else {
                    self?.statusLabel.stringValue = "Recording failed • \(error ?? "Unknown error")"
                }
            }
        }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        connect()
    }

    func applicationWillTerminate(_ notification: Notification) {
        if isRecording { recorder.stop() }
        capture.stop(); inputMonitor.stop()
    }

    func windowWillClose(_ notification: Notification) { NSApp.terminate(nil) }

    private func buildWindow() {
        window = NSWindow(contentRect: CGRect(x: 0, y: 0, width: 1480, height: 850),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                          backing: .buffered, defer: false)
        window.title = "EmuFusion Thor Studio"
        window.titlebarAppearsTransparent = true
        window.minSize = CGSize(width: 1050, height: 650)
        window.center(); window.delegate = self

        let root = NSView(); root.wantsLayer = true; root.layer?.backgroundColor = NSColor(calibratedWhite: 0.055, alpha: 1).cgColor
        window.contentView = root
        let previewContainer = NSView(); previewContainer.wantsLayer = true
        previewContainer.layer?.backgroundColor = NSColor.black.cgColor
        previewContainer.layer?.cornerRadius = 16; previewContainer.layer?.masksToBounds = true
        let sidebar = NSVisualEffectView(); sidebar.material = .sidebar; sidebar.blendingMode = .behindWindow; sidebar.state = .active
        [previewContainer, sidebar].forEach { $0.translatesAutoresizingMaskIntoConstraints = false; root.addSubview($0) }
        compositeView.translatesAutoresizingMaskIntoConstraints = false; previewContainer.addSubview(compositeView)

        NSLayoutConstraint.activate([
            sidebar.trailingAnchor.constraint(equalTo: root.trailingAnchor), sidebar.topAnchor.constraint(equalTo: root.topAnchor), sidebar.bottomAnchor.constraint(equalTo: root.bottomAnchor), sidebar.widthAnchor.constraint(equalToConstant: 288),
            previewContainer.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 18), previewContainer.trailingAnchor.constraint(equalTo: sidebar.leadingAnchor, constant: -18),
            previewContainer.centerYAnchor.constraint(equalTo: root.centerYAnchor), previewContainer.heightAnchor.constraint(lessThanOrEqualTo: root.heightAnchor, constant: -36),
            previewContainer.widthAnchor.constraint(equalTo: previewContainer.heightAnchor, multiplier: 16.0 / 9.0),
            previewContainer.topAnchor.constraint(greaterThanOrEqualTo: root.topAnchor, constant: 18),
            compositeView.leadingAnchor.constraint(equalTo: previewContainer.leadingAnchor), compositeView.trailingAnchor.constraint(equalTo: previewContainer.trailingAnchor),
            compositeView.topAnchor.constraint(equalTo: previewContainer.topAnchor), compositeView.bottomAnchor.constraint(equalTo: previewContainer.bottomAnchor)
        ])
        buildSidebar(sidebar)
    }

    private func buildSidebar(_ sidebar: NSView) {
        let title = NSTextField(labelWithString: "THOR STUDIO")
        title.font = .systemFont(ofSize: 22, weight: .bold); title.textColor = .labelColor
        let subtitle = NSTextField(wrappingLabelWithString: "Live EmuFusion showcase capture")
        subtitle.font = .systemFont(ofSize: 12, weight: .medium); subtitle.textColor = .secondaryLabelColor

        connectButton.target = self; connectButton.action = #selector(toggleConnection); connectButton.bezelStyle = .rounded
        recordButton.target = self; recordButton.action = #selector(toggleRecording); recordButton.bezelStyle = .rounded
        recordButton.font = .systemFont(ofSize: 16, weight: .semibold); recordButton.heightAnchor.constraint(equalToConstant: 46).isActive = true

        micCheckbox.state = .on
        isolationCheckbox.state = .on
        autoAccentCheckbox.state = .on; autoAccentCheckbox.target = self; autoAccentCheckbox.action = #selector(accentModeChanged)
        colorWell.color = state.snapshot().accent; colorWell.target = self; colorWell.action = #selector(manualColorChanged); colorWell.isEnabled = false

        let accentRow = NSStackView(views: [NSTextField(labelWithString: "Manual color"), colorWell])
        accentRow.orientation = .horizontal; accentRow.distribution = .fill; accentRow.alignment = .centerY
        colorWell.widthAnchor.constraint(equalToConstant: 54).isActive = true

        statusLabel.font = .monospacedSystemFont(ofSize: 11, weight: .medium); statusLabel.textColor = .secondaryLabelColor
        statusLabel.maximumNumberOfLines = 4; statusLabel.lineBreakMode = .byWordWrapping
        let info = NSTextField(wrappingLabelWithString: "The recording contains only the Thor composition—not these controls. Top-display refresh rate sets the output cadence. The Thor is mirrored read-only.")
        info.font = .systemFont(ofSize: 11); info.textColor = .tertiaryLabelColor

        let divider1 = NSBox(); divider1.boxType = .separator
        let divider2 = NSBox(); divider2.boxType = .separator
        let stack = NSStackView(views: [title, subtitle, divider1, connectButton, recordButton, micCheckbox, isolationCheckbox, divider2, autoAccentCheckbox, accentRow, statusLabel, info])
        stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 13
        stack.setCustomSpacing(3, after: title); stack.setCustomSpacing(22, after: subtitle)
        stack.translatesAutoresizingMaskIntoConstraints = false; sidebar.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: sidebar.leadingAnchor, constant: 24), stack.trailingAnchor.constraint(equalTo: sidebar.trailingAnchor, constant: -24), stack.topAnchor.constraint(equalTo: sidebar.safeAreaLayoutGuide.topAnchor, constant: 34),
            connectButton.widthAnchor.constraint(equalTo: stack.widthAnchor), recordButton.widthAnchor.constraint(equalTo: stack.widthAnchor),
            divider1.widthAnchor.constraint(equalTo: stack.widthAnchor), divider2.widthAnchor.constraint(equalTo: stack.widthAnchor),
            statusLabel.widthAnchor.constraint(equalTo: stack.widthAnchor), info.widthAnchor.constraint(equalTo: stack.widthAnchor), accentRow.widthAnchor.constraint(equalTo: stack.widthAnchor)
        ])
    }

    @objc private func toggleConnection() {
        if isConnected {
            capture.stop(); inputMonitor.stop(); isConnected = false
            connectButton.title = "Connect Thor"; statusLabel.stringValue = "Disconnected"
        } else { connect() }
    }

    private func connect() {
        guard !isConnected else { return }
        guard bridge.isConnected() else { statusLabel.stringValue = "Thor 427c87b2 is not connected"; return }
        isConnected = true; connectButton.title = "Disconnect"
        inputMonitor.start(); capture.start()
    }

    @objc private func toggleRecording() {
        if isRecording {
            statusLabel.stringValue = "Finalizing video…"; recorder.stop(); return
        }
        let panel = NSSavePanel(); panel.allowedContentTypes = [.mpeg4Movie]; panel.nameFieldStringValue = "EmuFusion-Thor-Showcase-\(Self.dateStamp()).mp4"
        panel.directoryURL = FileManager.default.urls(for: .moviesDirectory, in: .userDomainMask).first
        panel.beginSheetModal(for: window) { [weak self] result in
            guard result == .OK, let url = panel.url, let self else { return }
            if self.micCheckbox.state == .on {
                AVCaptureDevice.requestAccess(for: .audio) { _ in DispatchQueue.main.async { self.beginRecording(to: url) } }
            } else { self.beginRecording(to: url) }
        }
    }

    private func beginRecording(to url: URL) {
        do {
            try recorder.start(outputURL: url, includeMic: micCheckbox.state == .on, voiceIsolation: isolationCheckbox.state == .on)
            isRecording = true; recordButton.title = "Stop Recording"; recordButton.contentTintColor = .systemRed
        } catch { statusLabel.stringValue = "Unable to record • \(error.localizedDescription)" }
    }

    @objc private func accentModeChanged() {
        let auto = autoAccentCheckbox.state == .on
        state.setAutoAccent(auto); colorWell.isEnabled = !auto
        if !auto { state.setAccent(colorWell.color) }
    }

    @objc private func manualColorChanged() { state.setAccent(colorWell.color) }

    private static func dateStamp() -> String {
        let formatter = DateFormatter(); formatter.dateFormat = "yyyy-MM-dd-HHmmss"; return formatter.string(from: Date())
    }

    private func buildMenu() {
        let menu = NSMenu(); let appItem = NSMenuItem(); menu.addItem(appItem)
        let appMenu = NSMenu(); appMenu.addItem(withTitle: "About EmuFusion Thor Studio", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator()); appMenu.addItem(withTitle: "Quit EmuFusion Thor Studio", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu; NSApp.mainMenu = menu
    }
}
