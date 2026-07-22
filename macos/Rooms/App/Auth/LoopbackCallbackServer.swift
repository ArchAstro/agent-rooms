import Foundation
import Network
import ArchAstroPlatform

/// One-shot HTTP server on a loopback port that waits for the browser
/// sign-in redirect — the macOS equivalent of the archagents CLI's
/// callback server (RFC 8252 loopback redirect for native apps).
///
/// Accepts a single `GET /callback?...` (or the portal's `sendBeacon`
/// POST when the user closes the tab), replies with a small HTML page,
/// and resolves the full callback URL.
final class LoopbackCallbackServer: @unchecked Sendable {
    enum ServerError: LocalizedError {
        case startFailed(String)
        case timeout
        case cancelled

        var errorDescription: String? {
            switch self {
            case .startFailed(let reason): "Could not start sign-in listener: \(reason)"
            case .timeout: "Timed out waiting for the browser sign-in to complete."
            case .cancelled: "Sign-in was cancelled."
            }
        }
    }

    var port: UInt16 { portBox.withLock { $0 } }
    var callbackURL: String { "http://localhost:\(port)/callback" }

    private let portBox = Locked<UInt16>(0)
    private let listener: NWListener
    private let queue = DispatchQueue(label: "ai.archastro.Rooms.loopback")

    private struct State {
        var continuation: CheckedContinuation<URL, any Error>?
        var connections: [NWConnection] = []
        var finished = false
    }

    private let state = Locked(State())

    private init(listener: NWListener) {
        self.listener = listener
    }

    /// Bind an ephemeral loopback port and start listening — the CLI's
    /// findAvailablePort equivalent (the auth handoff accepts any
    /// localhost port).
    static func start() async throws -> LoopbackCallbackServer {
        // Loopback-only: the listener must never be reachable from other
        // machines.
        let parameters = NWParameters.tcp
        parameters.requiredInterfaceType = .loopback
        let listener: NWListener
        do {
            listener = try NWListener(using: parameters, on: .any)
        } catch {
            throw ServerError.startFailed(String(describing: error))
        }

        // The connection handler must be wired before start — a TCP
        // listener started without one fails with EINVAL.
        let server = LoopbackCallbackServer(listener: listener)
        listener.newConnectionHandler = { [weak server] connection in
            server?.accept(connection)
        }

        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, any Error>) in
            let resumed = Locked(false)
            listener.stateUpdateHandler = { newState in
                let first = resumed.withLock { done -> Bool in
                    guard !done else { return false }
                    switch newState {
                    case .ready, .failed:
                        done = true
                        return true
                    default:
                        return false
                    }
                }
                guard first else { return }
                switch newState {
                case .ready:
                    continuation.resume(returning: ())
                case .failed(let error):
                    continuation.resume(throwing: ServerError.startFailed(String(describing: error)))
                default:
                    break
                }
            }
            listener.start(queue: server.queue)
        }

        listener.stateUpdateHandler = nil
        server.portBox.withLock { $0 = listener.port?.rawValue ?? 0 }
        return server
    }

    /// Await the browser redirect. Mirrors the CLI's 5-minute default.
    func waitForCallback(timeout: TimeInterval = 300) async throws -> URL {
        try await withThrowingTaskGroup(of: URL.self) { group in
            group.addTask {
                try await withTaskCancellationHandler {
                    try await withCheckedThrowingContinuation { continuation in
                        let alreadyDone = self.state.withLock { state -> Bool in
                            guard !state.finished, state.continuation == nil else { return true }
                            state.continuation = continuation
                            return false
                        }
                        if alreadyDone {
                            continuation.resume(throwing: ServerError.cancelled)
                        }
                    }
                } onCancel: {
                    self.cancel()
                }
            }
            group.addTask {
                try await Task.sleep(nanoseconds: UInt64(timeout * 1_000_000_000))
                throw ServerError.timeout
            }
            do {
                guard let url = try await group.next() else { throw ServerError.timeout }
                group.cancelAll()
                return url
            } catch {
                group.cancelAll()
                self.cancel()
                throw error
            }
        }
    }

    /// Stop listening and fail any pending wait.
    func cancel() {
        finish(with: .failure(ServerError.cancelled))
    }

    // MARK: Internals

    private func accept(_ connection: NWConnection) {
        state.withLock { $0.connections.append(connection) }
        connection.start(queue: queue)
        receiveRequest(connection, buffer: Data())
    }

    private func receiveRequest(_ connection: NWConnection, buffer: Data) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 64 * 1024) {
            [weak self] data, _, isComplete, error in
            guard let self else { return }
            var buffer = buffer
            if let data { buffer.append(data) }

            if buffer.range(of: Data("\r\n\r\n".utf8)) != nil || isComplete || error != nil {
                self.handleRequest(connection, requestData: buffer)
            } else if buffer.count > 128 * 1024 {
                connection.cancel()
            } else {
                self.receiveRequest(connection, buffer: buffer)
            }
        }
    }

    private func handleRequest(_ connection: NWConnection, requestData: Data) {
        let head = String(decoding: requestData, as: UTF8.self)
        guard
            let requestLine = head.components(separatedBy: "\r\n").first,
            requestLine.components(separatedBy: " ").count >= 2
        else {
            respond(connection, status: "400 Bad Request", html: "<html><body>Bad request</body></html>")
            return
        }
        let target = requestLine.components(separatedBy: " ")[1]
        guard
            let url = URL(string: "http://localhost:\(port)\(target)"),
            url.path == "/callback"
        else {
            respond(connection, status: "404 Not Found", html: "<html><body>Not found</body></html>")
            return
        }

        let isError = URLComponents(url: url, resolvingAgainstBaseURL: false)?
            .queryItems?
            .contains { $0.name == "error" } ?? false

        let html = isError
            ? "<html><body><h1>Sign-in Failed</h1><p>You can close this window.</p></body></html>"
            : "<html><body><h1>Signed In</h1><p>You can close this window and return to Rooms.</p></body></html>"
        respond(connection, status: "200 OK", html: html)
        finish(with: .success(url))
    }

    private func respond(_ connection: NWConnection, status: String, html: String) {
        let body = Data(html.utf8)
        let head = [
            "HTTP/1.1 \(status)",
            "Content-Type: text/html; charset=utf-8",
            "Content-Length: \(body.count)",
            "Access-Control-Allow-Origin: *",
            "Access-Control-Allow-Methods: GET, POST",
            "Connection: close",
            "", "",
        ].joined(separator: "\r\n")
        var response = Data(head.utf8)
        response.append(body)
        connection.send(content: response, completion: .contentProcessed { _ in
            connection.cancel()
        })
    }

    private func finish(with result: Result<URL, any Error>) {
        let (continuation, connections) = state.withLock { state -> (CheckedContinuation<URL, any Error>?, [NWConnection]) in
            guard !state.finished else { return (nil, []) }
            state.finished = true
            let pending = state.continuation
            state.continuation = nil
            let open = state.connections
            state.connections = []
            return (pending, open)
        }
        switch result {
        case .success(let url):
            continuation?.resume(returning: url)
        case .failure(let error):
            continuation?.resume(throwing: error)
        }
        // Give the response a beat to flush before tearing down.
        queue.asyncAfter(deadline: .now() + 0.5) { [listener] in
            for connection in connections { connection.cancel() }
            listener.cancel()
        }
    }
}
