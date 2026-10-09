// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "EmuFusionThorStudio",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "EmuFusionThorStudio", targets: ["EmuFusionThorStudio"])
    ],
    targets: [
        .executableTarget(
            name: "EmuFusionThorStudio",
            path: "Sources/EmuFusionThorStudio",
            resources: [.process("Resources")]
        )
    ]
)
