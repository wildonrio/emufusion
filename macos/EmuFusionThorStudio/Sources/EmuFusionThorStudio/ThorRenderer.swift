import AppKit
import CoreGraphics
import Foundation

enum ThorGeometry {
    static let designSize = CGSize(width: 1920, height: 1080)
    // Physical calibration: the shell is 150 x 94 mm, represented by
    // 870 x 545.2 units. Active panel sizes are derived from their published
    // diagonals and native aspect ratios rather than estimated from a photo.
    static let topScreen = CGRect(x: 574.8, y: 64.8, width: 770.4, height: 433.35)
    static let bottomScreen = CGRect(x: 742.25, y: 565, width: 435.5, height: 379.3)
    static let leftStick = CGPoint(x: 636, y: 681)
    static let rightStick = CGPoint(x: 1284, y: 829)

    static let controls: [ThorControl: CGRect] = [
        .a: CGRect(x: 1308, y: 672, width: 48, height: 48),
        .b: CGRect(x: 1260, y: 720, width: 48, height: 48),
        .x: CGRect(x: 1260, y: 624, width: 48, height: 48),
        .y: CGRect(x: 1212, y: 672, width: 48, height: 48),
        .dpadUp: CGRect(x: 620, y: 785, width: 32, height: 48),
        .dpadDown: CGRect(x: 620, y: 833, width: 32, height: 48),
        .dpadLeft: CGRect(x: 588, y: 817, width: 48, height: 32),
        .dpadRight: CGRect(x: 636, y: 817, width: 48, height: 32),
        // The square Stop key is Select on a tap and Stop on a hold.
        .select: CGRect(x: 611, y: 552, width: 50, height: 50),
        .stop: CGRect(x: 611, y: 552, width: 50, height: 50),
        .start: CGRect(x: 1259, y: 552, width: 50, height: 50),
        .home: CGRect(x: 617, y: 958, width: 38, height: 38),
        .back: CGRect(x: 1265, y: 958, width: 38, height: 38),
        .leftStickClick: CGRect(x: 580, y: 625, width: 112, height: 112),
        .rightStickClick: CGRect(x: 1228, y: 773, width: 112, height: 112)
    ]
}

final class ThorRenderer {
    private let state: StudioState
    private let shell: CGImage?

    init(state: StudioState) {
        self.state = state
        let packaged = Bundle.main.resourceURL?
            .appendingPathComponent("EmuFusionThorStudio_EmuFusionThorStudio.bundle", isDirectory: true)
            .appendingPathComponent("thor-open-front.svg")
        let development = Bundle.module.url(forResource: "thor-open-front", withExtension: "svg")
        let image = (packaged.flatMap(NSImage.init(contentsOf:))) ?? development.flatMap(NSImage.init(contentsOf:))
        var proposed = CGRect(origin: .zero, size: ThorGeometry.designSize)
        shell = image?.cgImage(forProposedRect: &proposed, context: nil, hints: [.interpolation: NSImageInterpolation.high])
    }

    func draw(in context: CGContext, size: CGSize) {
        let scale = min(size.width / ThorGeometry.designSize.width, size.height / ThorGeometry.designSize.height)
        let offset = CGPoint(
            x: (size.width - ThorGeometry.designSize.width * scale) / 2,
            y: (size.height - ThorGeometry.designSize.height * scale) / 2
        )
        context.saveGState()
        context.translateBy(x: offset.x, y: offset.y)
        context.scaleBy(x: scale, y: scale)
        let snap = state.snapshot()

        if let shell { drawUpright(shell, in: CGRect(origin: .zero, size: ThorGeometry.designSize), context: context) }

        drawScreen(snap.top, in: ThorGeometry.topScreen, context: context, fallback: "TOP DISPLAY • CONNECTING")
        drawScreen(snap.bottom, in: ThorGeometry.bottomScreen, context: context, fallback: "LOWER DISPLAY")
        drawStickGlow(center: ThorGeometry.leftStick, stick: snap.controller.leftStick, color: snap.accent, context: context)
        drawStickGlow(center: ThorGeometry.rightStick, stick: snap.controller.rightStick, color: snap.accent, context: context)
        drawPressedControls(snap.controller, color: snap.accent, context: context)
        drawShoulderBadges(snap.controller, color: snap.accent, context: context)
        context.restoreGState()
    }

    func makeImage(size: CGSize = CGSize(width: 1920, height: 1080)) -> CGImage? {
        guard let bitmap = CGContext(
            data: nil, width: Int(size.width), height: Int(size.height), bitsPerComponent: 8,
            bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue
        ) else { return nil }
        bitmap.translateBy(x: 0, y: size.height)
        bitmap.scaleBy(x: 1, y: -1)
        draw(in: bitmap, size: size)
        return bitmap.makeImage()
    }

    private func drawScreen(_ image: CGImage?, in rect: CGRect, context: CGContext, fallback: String) {
        context.saveGState()
        let path = CGPath(roundedRect: rect, cornerWidth: 10, cornerHeight: 10, transform: nil)
        context.addPath(path); context.clip()
        if let image {
            let imageSize = CGSize(width: image.width, height: image.height)
            let target = aspectFit(imageSize, in: rect)
            context.setFillColor(NSColor.black.cgColor); context.fill(rect)
            // The renderer uses a top-left coordinate system; CGImage pixel rows are
            // bottom-left based, so flip only the live frame inside its target rect.
            drawUpright(image, in: target, context: context)
        } else {
            let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: [
                NSColor(calibratedWhite: 0.025, alpha: 1).cgColor,
                NSColor(calibratedRed: 0.03, green: 0.055, blue: 0.09, alpha: 1).cgColor
            ] as CFArray, locations: [0, 1])!
            context.drawLinearGradient(gradient, start: rect.origin, end: CGPoint(x: rect.maxX, y: rect.maxY), options: [])
            drawLabel(fallback, at: CGPoint(x: rect.midX, y: rect.midY), size: 18, color: .white.withAlphaComponent(0.38), context: context)
        }
        context.restoreGState()
    }

    private func drawUpright(_ image: CGImage, in rect: CGRect, context: CGContext) {
        context.saveGState()
        context.translateBy(x: rect.minX, y: rect.maxY)
        context.scaleBy(x: 1, y: -1)
        context.draw(image, in: CGRect(origin: .zero, size: rect.size))
        context.restoreGState()
    }

    private func aspectFit(_ source: CGSize, in destination: CGRect) -> CGRect {
        let ratio = min(destination.width / source.width, destination.height / source.height)
        let size = CGSize(width: source.width * ratio, height: source.height * ratio)
        return CGRect(x: destination.midX - size.width / 2, y: destination.midY - size.height / 2, width: size.width, height: size.height)
    }

    private func drawStickGlow(center: CGPoint, stick: StickPosition, color: NSColor, context: CGContext) {
        let glow = color.withAlphaComponent(0.72).cgColor
        let clear = color.withAlphaComponent(0).cgColor
        let colors = [glow, color.withAlphaComponent(0.25).cgColor, clear] as CFArray
        let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: colors, locations: [0, 0.42, 1])!
        context.saveGState()
        context.setBlendMode(.screen)
        context.drawRadialGradient(gradient, startCenter: center, startRadius: 16, endCenter: center, endRadius: 102, options: [])
        context.restoreGState()

        let knob = CGPoint(x: center.x + stick.x * 13, y: center.y + stick.y * 13)
        context.saveGState()
        context.setStrokeColor(color.withAlphaComponent(0.96).cgColor)
        context.setLineWidth(5)
        context.strokeEllipse(in: CGRect(x: knob.x - 48, y: knob.y - 48, width: 96, height: 96))
        context.restoreGState()
    }

    private func drawPressedControls(_ snapshot: ControllerSnapshot, color: NSColor, context: CGContext) {
        context.saveGState()
        context.setBlendMode(.screen)
        for control in snapshot.pressed {
            guard let rect = ThorGeometry.controls[control] else { continue }
            let expanded = rect.insetBy(dx: -9, dy: -9)
            context.setFillColor(color.withAlphaComponent(0.42).cgColor)
            context.fillEllipse(in: expanded)
            context.setStrokeColor(NSColor.white.withAlphaComponent(0.95).cgColor)
            context.setLineWidth(4)
            context.strokeEllipse(in: expanded)
        }
        context.restoreGState()
    }

    private func drawShoulderBadges(_ snapshot: ControllerSnapshot, color: NSColor, context: CGContext) {
        let badges: [(ThorControl, String, CGRect, CGFloat)] = [
            (.l2, "L2", CGRect(x: 403, y: 590, width: 82, height: 42), snapshot.leftTrigger),
            (.l1, "L1", CGRect(x: 490, y: 548, width: 82, height: 42), snapshot.pressed.contains(.l1) ? 1 : 0),
            (.r1, "R1", CGRect(x: 1348, y: 548, width: 82, height: 42), snapshot.pressed.contains(.r1) ? 1 : 0),
            (.r2, "R2", CGRect(x: 1435, y: 590, width: 82, height: 42), snapshot.rightTrigger)
        ]
        for (control, label, rect, analog) in badges {
            let active = snapshot.pressed.contains(control) || analog > 0.08
            let path = CGPath(roundedRect: rect, cornerWidth: 15, cornerHeight: 15, transform: nil)
            context.setFillColor((active ? color.withAlphaComponent(0.9) : NSColor.black.withAlphaComponent(0.78)).cgColor)
            context.addPath(path); context.fillPath()
            context.setStrokeColor((active ? NSColor.white : NSColor.white.withAlphaComponent(0.25)).cgColor)
            context.setLineWidth(active ? 3 : 1.5); context.addPath(path); context.strokePath()
            drawLabel(label, at: CGPoint(x: rect.midX, y: rect.midY + 1), size: 21, color: .white, context: context)
            if analog > 0.08 {
                let meter = CGRect(x: rect.minX + 8, y: rect.maxY - 7, width: (rect.width - 16) * analog, height: 3)
                context.setFillColor(NSColor.white.cgColor); context.fill(meter)
            }
        }
    }

    private func drawLabel(_ text: String, at point: CGPoint, size: CGFloat, color: NSColor, context: CGContext) {
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: size, weight: .semibold), .foregroundColor: color,
            .kern: 1.2
        ]
        let string = NSAttributedString(string: text, attributes: attributes)
        let measured = string.size()
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: true)
        string.draw(at: CGPoint(x: point.x - measured.width / 2, y: point.y - measured.height / 2))
        NSGraphicsContext.restoreGraphicsState()
    }
}

final class ThorCompositeView: NSView {
    let renderer: ThorRenderer
    private var timer: Timer?

    init(renderer: ThorRenderer) {
        self.renderer = renderer
        super.init(frame: .zero)
        wantsLayer = true
        layer?.backgroundColor = NSColor.black.cgColor
        timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 120.0, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.needsDisplay = true }
        }
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override var isFlipped: Bool { true }

    override func draw(_ dirtyRect: NSRect) {
        guard let context = NSGraphicsContext.current?.cgContext else { return }
        renderer.draw(in: context, size: bounds.size)
    }
}
