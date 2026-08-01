import ArchAstroPlatform
import Foundation

struct MessageUpload: Equatable, Sendable {
    static let maximumCount = 10
    static let maximumBytes = 5_000_000

    var name: String
    var mimeType: String
    var data: Data

    var channelPayload: [String: JSONValue] {
        [
            "name": .string(name),
            "mime_type": .string(mimeType),
            "content": .string(data.base64EncodedString()),
        ]
    }
}
