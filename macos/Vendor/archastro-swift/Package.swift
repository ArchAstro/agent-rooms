// swift-tools-version: 6.0
// Vendored manifest — see scripts/vendor_sdk.sh. Library target only.
import PackageDescription

let package = Package(
    name: "archastro-swift",
    platforms: [
        .macOS(.v13),
        .iOS(.v16),
        .tvOS(.v16),
        .watchOS(.v9),
    ],
    products: [
        .library(name: "ArchAstroPlatform", targets: ["ArchAstroPlatform"])
    ],
    targets: [
        .target(
            name: "ArchAstroPlatform",
            path: "Sources/ArchAstroPlatform"
        )
    ]
)
