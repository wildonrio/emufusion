import AppKit
import CoreGraphics
import CoreMedia
import Foundation

enum ThorControl: String, CaseIterable, Hashable {
    case a, b, x, y
    case dpadUp, dpadDown, dpadLeft, dpadRight
    case l1, l2, r1, r2
    case start, select, home, back, stop
    case leftStickClick, rightStickClick
}

struct StickPosition: Sendable {
    var x: CGFloat = 0
    var y: CGFloat = 0
}

struct ControllerSnapshot: Sendable {
    var pressed: Set<ThorControl> = []
    var leftStick = StickPosition()
    var rightStick = StickPosition()
    var leftTrigger: CGFloat = 0
    var rightTrigger: CGFloat = 0
}

final class StudioState: @unchecked Sendable {
    private let lock = NSLock()
    private var _topFrame: CGImage?
    private var _bottomFrame: CGImage?
    private var _controller = ControllerSnapshot()
    private var _accent = NSColor(calibratedRed: 0.23, green: 0.73, blue: 1.0, alpha: 1)
    private var _autoAccent = true
    private var _refreshRate: Double = 120

    func setTopFrame(_ frame: CGImage?) { lock.withLock { _topFrame = frame } }
    func setBottomFrame(_ frame: CGImage?) { lock.withLock { _bottomFrame = frame } }
    func updateController(_ body: (inout ControllerSnapshot) -> Void) { lock.withLock { body(&_controller) } }
    func setAccent(_ color: NSColor) { lock.withLock { _accent = color.usingColorSpace(.deviceRGB) ?? color } }
    func setAutoAccent(_ enabled: Bool) { lock.withLock { _autoAccent = enabled } }
    func applySampledAccent(_ color: NSColor) { lock.withLock { if _autoAccent { _accent = color.usingColorSpace(.deviceRGB) ?? color } } }
    func setRefreshRate(_ value: Double) { lock.withLock { _refreshRate = max(24, min(240, value)) } }

    func snapshot() -> (top: CGImage?, bottom: CGImage?, controller: ControllerSnapshot, accent: NSColor, refreshRate: Double) {
        lock.withLock { (_topFrame, _bottomFrame, _controller, _accent, _refreshRate) }
    }
}

extension NSLock {
    @discardableResult
    fileprivate func withLock<T>(_ body: () throws -> T) rethrows -> T {
        lock(); defer { unlock() }
        return try body()
    }
}
