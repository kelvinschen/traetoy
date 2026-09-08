import Foundation
import Darwin

enum LocalSocket {
    static func address(_ path: String) throws -> sockaddr_un {
        var addr = sockaddr_un(); addr.sun_family = sa_family_t(AF_UNIX)
        let bytes = Array(path.utf8) + [0]
        guard bytes.count <= MemoryLayout.size(ofValue: addr.sun_path) else { throw failure("工作区路径过长") }
        withUnsafeMutableBytes(of: &addr.sun_path) { $0.copyBytes(from: bytes + Array(repeating: 0, count: $0.count - bytes.count)) }
        addr.sun_len = UInt8(MemoryLayout<sockaddr_un>.size); return addr
    }
    static func failure(_ text: String) -> NSError { NSError(domain: "Passport", code: 1, userInfo: [NSLocalizedDescriptionKey: text]) }
    static func connect(_ path: String) throws -> Int32 {
        let fd = socket(AF_UNIX, SOCK_STREAM, 0); guard fd >= 0 else { throw failure("无法创建本地连接") }
        var addr = try address(path)
        let rc = withUnsafePointer(to: &addr) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.connect(fd, $0, socklen_t(MemoryLayout<sockaddr_un>.size)) } }
        guard rc == 0 else { close(fd); throw failure("服务未连接") }
        var uid: uid_t = 0; var gid: gid_t = 0
        guard getpeereid(fd, &uid, &gid) == 0 && uid == geteuid() else { close(fd); throw failure("连接身份不匹配") }
        var yes: Int32 = 1; setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &yes, socklen_t(MemoryLayout.size(ofValue: yes)))
        return fd
    }
    static func send(_ fd: Int32, _ value: [String: Any]) throws {
        var data = try JSONSerialization.data(withJSONObject: value); data.append(10)
        try data.withUnsafeBytes { bytes in
            var n = 0
            while n < bytes.count { let wrote = Darwin.write(fd, bytes.baseAddress!.advanced(by: n), bytes.count-n); if wrote <= 0 { throw failure("连接已关闭") }; n += wrote }
        }
    }
    static func line(_ fd: Int32, limit: Int = 65536) throws -> [String: Any] {
        var data = Data(); var b: UInt8 = 0
        while data.count < limit {
            let n = Darwin.read(fd, &b, 1); if n < 0 && errno == EINTR { continue }
            guard n == 1 else { throw failure("连接已关闭") }
            if b == 10 { guard let value = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw failure("状态格式错误") }; return value }; data.append(b)
        }
        throw failure("状态消息过大")
    }
    static func request(_ path: String, _ op: String) throws -> [String: Any] {
        let fd = try connect(path); defer { close(fd) }; var timeout = timeval(tv_sec: 4, tv_usec: 0)
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout.size(ofValue: timeout)))
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, socklen_t(MemoryLayout.size(ofValue: timeout)))
        try send(fd, ["v": 1, "op": op]); return try line(fd)
    }
    static func serve(_ path: String, action: @escaping (String) -> [String: Any]) throws -> Int32 {
        unlink(path); let fd = socket(AF_UNIX, SOCK_STREAM, 0); var addr = try address(path)
        let rc = withUnsafePointer(to: &addr) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(fd, $0, socklen_t(MemoryLayout<sockaddr_un>.size)) } }
        guard rc == 0 else { close(fd); throw failure("无法创建应用控制接口") }; chmod(path, 0o600); listen(fd, 4)
        DispatchQueue.global(qos: .utility).async {
            while true {
                let client = accept(fd, nil, nil); if client < 0 { break }
                defer { close(client) }; var uid: uid_t = 0; var gid: gid_t = 0
                guard getpeereid(client, &uid, &gid) == 0 && uid == geteuid() else { continue }
                var timeout = timeval(tv_sec: 2, tv_usec: 0); setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout.size(ofValue: timeout)))
                var yes: Int32 = 1; setsockopt(client, SOL_SOCKET, SO_NOSIGPIPE, &yes, socklen_t(MemoryLayout.size(ofValue: yes)))
                if let v = try? line(client, limit: 4096), v["v"] as? Int == 1, let op = v["op"] as? String { try? send(client, action(op)) }
            }
        }; return fd
    }
}
