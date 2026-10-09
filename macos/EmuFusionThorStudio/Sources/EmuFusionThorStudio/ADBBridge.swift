import AppKit
import Foundation

final class ADBBridge: @unchecked Sendable {
    let adbPath: String
    let serial: String

    init(adbPath: String = "/Users/tyleryoung/.codex/tools/android-platform-tools/adb", serial: String = "427c87b2") {
        self.adbPath = adbPath
        self.serial = serial
    }

    func command(_ arguments: [String], timeout: TimeInterval = 4) -> String? {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: adbPath)
        process.arguments = ["-s", serial] + arguments
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = Pipe()
        do {
            try process.run()
            let deadline = Date().addingTimeInterval(timeout)
            while process.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.02) }
            if process.isRunning { process.terminate() }
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            return String(data: data, encoding: .utf8)
        } catch {
            return nil
        }
    }

    func isConnected() -> Bool {
        command(["get-state"])?.trimmingCharacters(in: .whitespacesAndNewlines) == "device"
    }

    func activeRefreshRate() -> Double {
        guard let text = command(["shell", "dumpsys", "display"], timeout: 8) else { return 120 }
        // The first DisplayDeviceInfo row is the top panel. Resolve its active
        // mode ID against that row instead of accidentally taking the first
        // supported (usually 60 Hz) mode.
        if let line = text.split(separator: "\n").first(where: { $0.contains("DisplayDeviceInfo{\"Built-in Screen\"") }) {
            let value = String(line)
            let modePattern = #"modeId\s+([0-9]+)"#
            if let modeRegex = try? NSRegularExpression(pattern: modePattern),
               let modeMatch = modeRegex.firstMatch(in: value, range: NSRange(value.startIndex..., in: value)),
               let modeRange = Range(modeMatch.range(at: 1), in: value) {
                let modeID = String(value[modeRange])
                let fpsPattern = #"id="# + NSRegularExpression.escapedPattern(for: modeID) + #",\s*width=[0-9]+,\s*height=[0-9]+,\s*fps=([0-9.]+)"#
                if let fpsRegex = try? NSRegularExpression(pattern: fpsPattern),
                   let fpsMatch = fpsRegex.firstMatch(in: value, range: NSRange(value.startIndex..., in: value)),
                   let fpsRange = Range(fpsMatch.range(at: 1), in: value),
                   let rate = Double(value[fpsRange]) { return rate }
            }
        }
        return 120
    }
}

final class InputEventMonitor: @unchecked Sendable {
    private let bridge: ADBBridge
    private let state: StudioState
    private var process: Process?
    private var buffer = Data()
    private let queue = DispatchQueue(label: "com.emufusion.thorstudio.input")
    private var selectIsDown = false
    private var selectPressGeneration = 0

    init(bridge: ADBBridge, state: StudioState) {
        self.bridge = bridge
        self.state = state
    }

    func start() {
        stop()
        let process = Process()
        process.executableURL = URL(fileURLWithPath: bridge.adbPath)
        process.arguments = ["-s", bridge.serial, "shell", "getevent", "-lt", "/dev/input/event9"]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = Pipe()
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            guard let monitor = self else { return }
            monitor.queue.async { monitor.consume(data) }
        }
        do { try process.run(); self.process = process } catch { self.process = nil }
    }

    func stop() {
        process?.terminate()
        process = nil
    }

    private func consume(_ data: Data) {
        buffer.append(data)
        while let newline = buffer.firstRange(of: Data([0x0a])) {
            let lineData = buffer[..<newline.lowerBound]
            buffer.removeSubrange(...newline.lowerBound)
            guard let line = String(data: lineData, encoding: .utf8) else { continue }
            parse(line)
        }
    }

    private func parse(_ line: String) {
        let pieces = line.split(whereSeparator: { $0 == " " || $0 == "\t" })
        guard pieces.count >= 3 else { return }
        let type = String(pieces[pieces.count - 3])
        let code = String(pieces[pieces.count - 2])
        let valueText = String(pieces[pieces.count - 1])
        let value = Int32(valueText, radix: 16) ?? Int32(valueText) ?? 0

        if type == "EV_KEY", code == "BTN_SELECT" {
            handleSelect(value: value)
        } else if type == "EV_KEY", let control = keyMap[code] {
            state.updateController { snapshot in
                if value != 0 { snapshot.pressed.insert(control) }
                else { snapshot.pressed.remove(control) }
            }
        } else if type == "EV_ABS" {
            let normalized = CGFloat(value) / 32767.0
            state.updateController { snapshot in
                switch code {
                case "ABS_X": snapshot.leftStick.x = normalized.clamped(to: -1...1)
                case "ABS_Y": snapshot.leftStick.y = normalized.clamped(to: -1...1)
                case "ABS_Z": snapshot.rightStick.x = normalized.clamped(to: -1...1)
                case "ABS_RZ": snapshot.rightStick.y = normalized.clamped(to: -1...1)
                case "ABS_GAS": snapshot.rightTrigger = normalized.clamped(to: 0...1)
                case "ABS_BRAKE": snapshot.leftTrigger = normalized.clamped(to: 0...1)
                case "ABS_HAT0X":
                    snapshot.pressed.remove(.dpadLeft); snapshot.pressed.remove(.dpadRight)
                    if value < 0 { snapshot.pressed.insert(.dpadLeft) }
                    if value > 0 { snapshot.pressed.insert(.dpadRight) }
                case "ABS_HAT0Y":
                    snapshot.pressed.remove(.dpadUp); snapshot.pressed.remove(.dpadDown)
                    if value < 0 { snapshot.pressed.insert(.dpadUp) }
                    if value > 0 { snapshot.pressed.insert(.dpadDown) }
                default: break
                }
            }
        }
    }

    private func handleSelect(value: Int32) {
        if value != 0 {
            guard !selectIsDown else { return }
            selectIsDown = true
            selectPressGeneration += 1
            let generation = selectPressGeneration
            state.updateController { $0.pressed.insert(.select) }
            queue.asyncAfter(deadline: .now() + 1.0) { [weak self] in
                guard let self, self.selectIsDown, self.selectPressGeneration == generation else { return }
                self.state.updateController { $0.pressed.insert(.stop) }
            }
        } else {
            selectIsDown = false
            selectPressGeneration += 1
            state.updateController {
                $0.pressed.remove(.select)
                $0.pressed.remove(.stop)
            }
        }
    }

    private let keyMap: [String: ThorControl] = [
        "BTN_GAMEPAD": .a, "BTN_EAST": .b, "BTN_NORTH": .x, "BTN_WEST": .y,
        "BTN_TL": .l1, "BTN_TR": .r1, "BTN_TL2": .l2, "BTN_TR2": .r2,
        "BTN_START": .start, "BTN_MODE": .home,
        "KEY_HOME": .home, "KEY_BACK": .back, "KEY_APPSELECT": .stop,
        "BTN_THUMBL": .leftStickClick, "BTN_THUMBR": .rightStickClick,
        "BTN_DPAD_UP": .dpadUp, "BTN_DPAD_DOWN": .dpadDown,
        "BTN_DPAD_LEFT": .dpadLeft, "BTN_DPAD_RIGHT": .dpadRight
    ]
}

private extension Comparable {
    func clamped(to range: ClosedRange<Self>) -> Self { min(max(self, range.lowerBound), range.upperBound) }
}
