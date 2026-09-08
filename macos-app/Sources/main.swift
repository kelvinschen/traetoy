import AppKit
import ServiceManagement
import Darwin

let bundleRoot = Bundle.main.object(forInfoDictionaryKey: "PassportWorkspace") as? String
let arguments = CommandLine.arguments
let root = arguments.firstIndex(of: "--workspace").flatMap { $0+1 < arguments.count ? arguments[$0+1] : nil } ?? bundleRoot ?? FileManager.default.currentDirectoryPath
let controlDir = root + "/reports/control"
try FileManager.default.createDirectory(atPath: controlDir, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
let appSocket = controlDir + "/app.sock"
let backendSocket = controlDir + "/bridge.sock"
if let i = arguments.firstIndex(of: "--command"), i+1 < arguments.count {
    do { let result = try LocalSocket.request(appSocket, arguments[i+1]); print(String(data: try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]), encoding: .utf8)!); exit(arguments[i+1] == "status" || (result["error"] as? String ?? "").isEmpty ? 0 : 1) }
    catch { fputs("\(error.localizedDescription)\n", stderr); exit(1) }
}
// The lock also protects the socket from duplicate app launches with `open -n`.
let instanceLock = Darwin.open(controlDir + "/app.lock", O_CREAT | O_WRONLY, 0o600)
guard instanceLock >= 0 && flock(instanceLock, LOCK_EX | LOCK_NB) == 0 else { exit(0) }

final class Passport: NSObject, NSApplicationDelegate, NSMenuDelegate {
    var statusItem: NSStatusItem!
    var menu = NSMenu()
    var state: [String: Any] = [:]
    var desired = false
    var busy = false
    var quitting = false
    var quitRequested = false
    var fault = ""
    var retries: [Date] = []
    var connectionGeneration = 0
    var bridgePID: Int32 = 0
    var serverFD: Int32 = -1
    let work = DispatchQueue(label: "passport.lifecycle", qos: .utility)
    var service = NSMenuItem(); var device = NSMenuItem(); var firmware = NSMenuItem(); var sources = NSMenuItem(); var errorRow = NSMenuItem()
    var startItem = NSMenuItem(); var stopItem = NSMenuItem(); var restartItem = NSMenuItem(); var reconnectItem = NSMenuItem(); var loginItem = NSMenuItem(); var forceItem = NSMenuItem()
    func item(_ title: String, _ selector: Selector? = nil) -> NSMenuItem { let i = NSMenuItem(title: title, action: selector, keyEquivalent: ""); i.target = self; menu.addItem(i); return i }
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem.button?.image = NSImage(systemSymbolName: "rectangle.connected.to.line.below", accessibilityDescription: "Passport")
        menu.autoenablesItems = false; menu.delegate = self
        _ = item("Passport"); service = item("正在启动"); device = item("设备未连接"); firmware = item("固件：等待识别"); sources = item("采集源：等待同步"); errorRow = item("")
        menu.addItem(.separator()); startItem = item("启动服务", #selector(startAction)); stopItem = item("停止服务", #selector(stopAction)); restartItem = item("重启服务", #selector(restartAction)); reconnectItem = item("重新连接设备", #selector(reconnectAction)); forceItem = item("强制停止服务…", #selector(forceAction)); forceItem.isHidden = true
        menu.addItem(.separator()); loginItem = item("登录时启动", #selector(loginAction)); _ = item("查看日志…", #selector(logAction)); menu.addItem(.separator()); _ = item("退出 Passport", #selector(quitAction))
        statusItem.menu = menu
        do { serverFD = try LocalSocket.serve(appSocket) { [weak self] op in
            var reply: [String: Any] = [:]
            DispatchQueue.main.sync { guard let self else { return }; switch op {
                case "status": break
                case "start": self.startAction()
                case "stop": self.stopAction()
                case "restart": self.restartAction()
                case "reconnect": self.reconnectAction()
                case "quit": self.quitAction()
                case "login-enable": self.setLogin(true)
                case "login-disable": self.setLogin(false)
                default: reply = ["v": 1, "error": "unknown_operation"]; return
            }; reply = self.snapshot() }; return reply
        } } catch { fault = error.localizedDescription; update(); return }
        NSWorkspace.shared.notificationCenter.addObserver(self, selector: #selector(woke), name: NSWorkspace.didWakeNotification, object: nil)
        startAction()
    }
    func snapshot() -> [String: Any] { ["v": 1, "pid": ProcessInfo.processInfo.processIdentifier, "desired": desired, "busy": busy, "quitting": quitting, "loginEnabled": SMAppService.mainApp.status == .enabled, "loginApprovalRequired": SMAppService.mainApp.status == .requiresApproval, "error": fault, "backend": state] }
    func update() {
        service.title = busy ? (desired ? "正在启动服务…" : "正在停止服务…") : (desired && bridgePID > 0 ? "服务运行中" : "服务已停止")
        let d = state["device"] as? [String: Any] ?? [:]; let transport = d["transport"] as? String ?? "none"
        let compatibility = d["compatibility"] as? String ?? "disconnected"
        device.title = transport == "none" ? "设备未连接" : "设备已连接 · \(transport.uppercased())"
        if let f = d["firmware"] as? [String: Any] { firmware.title = "固件：\(f["id"] ?? "--") · \(f["version"] ?? "--")" }
        else { firmware.title = compatibility == "update_required" ? "固件：需要更新以支持识别" : "固件：等待识别" }
        if compatibility == "unsupported" { firmware.title += " · 不兼容" }
        let module = state["module"] as? [String: Any] ?? [:]; let rows = module["sources"] as? [[String: Any]] ?? []
        sources.title = rows.isEmpty ? "采集源：等待同步" : rows.map { "\(($0["name"] as? String ?? "").replacingOccurrences(of: "ssh:", with: "").replacingOccurrences(of: "local", with: "本机")) \(($0["healthy"] as? Bool ?? false) ? "正常" : "未连接")" }.joined(separator: " · ")
        let message = fault.isEmpty ? (state["error"] as? String ?? "") : fault
        errorRow.title = String(message.prefix(100)); errorRow.isHidden = message.isEmpty
        for i in [service, device, firmware, sources, errorRow] { i.isEnabled = false }
        startItem.isEnabled = !busy && !desired && bridgePID == 0; stopItem.isEnabled = !busy && (desired || bridgePID > 0); restartItem.isEnabled = !busy && desired; reconnectItem.isEnabled = !busy && desired && bridgePID > 0
        loginItem.state = SMAppService.mainApp.status == .enabled ? .on : .off
        statusItem.button?.appearsDisabled = !desired
        statusItem.button?.toolTip = "Passport · \(service.title) · \(device.title)"
    }
    func menuWillOpen(_ menu: NSMenu) { update() }
    func shell(_ op: String) -> (Int32, String) {
        let process = Process(); process.executableURL = URL(fileURLWithPath: root + "/scripts/bridge-service.sh"); process.arguments = [op]
        let pipe = Pipe(); process.standardOutput = pipe; process.standardError = pipe
        do { try process.run(); let data = pipe.fileHandleForReading.readDataToEndOfFile(); process.waitUntilExit(); return (process.terminationStatus, String(data: data, encoding: .utf8) ?? "") } catch { return (1, error.localizedDescription) }
    }
    @objc func startAction() { guard !busy && !desired else { return }; desired = true; fault = ""; retries = []; launch() }
    func launch() {
        busy = true; update(); connectionGeneration += 1; let generation = connectionGeneration
        work.async { let result = self.shell("backend-start"); DispatchQueue.main.async {
            guard generation == self.connectionGeneration else { return }
            if result.0 != 0 { self.busy = false; self.desired = false; self.fault = result.1; self.update(); if self.quitRequested { self.quitAction() }; return }
            self.watch(generation)
        } }
    }
    func watch(_ generation: Int) {
        DispatchQueue.global(qos: .utility).async {
            var fd: Int32 = -1
            for _ in 0..<100 { if let connected = try? LocalSocket.connect(backendSocket) { fd = connected; break }; Thread.sleep(forTimeInterval: 0.1) }
            if fd >= 0 {
                defer { close(fd) }
                do { try LocalSocket.send(fd, ["v": 1, "op": "subscribe", "owner": true])
                    while true { let value = try LocalSocket.line(fd); if value["error"] as? String == "owner_exists" { throw LocalSocket.failure("已有应用管理该服务") }
                        DispatchQueue.main.async { guard generation == self.connectionGeneration else { return }; self.state = value; self.fault = ""; self.bridgePID = (value["pid"] as? Int32) ?? 0; self.busy = false; self.update(); if self.quitRequested { self.quitAction() } }
                    }
                } catch { }
            }
            DispatchQueue.main.async { guard generation == self.connectionGeneration else { return }; self.bridgePID = 0; self.state = [:]; self.busy = false
                if self.quitRequested { self.quitAction(); return }
                guard self.desired && !self.quitting else { self.update(); return }
                self.retries = self.retries.filter { Date().timeIntervalSince($0) < 60 }
                if self.retries.count >= 3 { self.desired = false; self.fault = "服务连续异常退出，请查看日志后手动启动"; self.update(); return }
                self.retries.append(Date()); self.fault = "服务连接中断，正在恢复…"; self.update()
                DispatchQueue.main.asyncAfter(deadline: .now()+2) { if self.desired && !self.busy { self.launch() } }
            }
        }
    }
    func stop(restart: Bool = false, quit: Bool = false) {
        guard !busy else { return }; desired = false; busy = true; quitting = quit; connectionGeneration += 1; update()
        work.async { let result = self.shell("backend-stop"); DispatchQueue.main.async {
            self.busy = false
            if result.0 != 0 { self.fault = result.1; self.quitting = false; self.quitRequested = false; NSApp.reply(toApplicationShouldTerminate: false); self.forceItem.isHidden = false; self.update(); return }
            self.bridgePID = 0; self.state = [:]; self.forceItem.isHidden = true; self.fault = ""; self.update()
            if quit || self.quitRequested { self.quitting = true; NSApp.reply(toApplicationShouldTerminate: true); NSApp.terminate(nil) } else if restart { self.startAction() }
        } }
    }
    @objc func stopAction() { stop() }
    @objc func restartAction() { stop(restart: true) }
    @objc func reconnectAction() { guard !busy && desired else { return }; work.async { do { _ = try LocalSocket.request(backendSocket, "reconnect") } catch { DispatchQueue.main.async { self.fault = error.localizedDescription; self.update() } } } }
    @objc func quitAction() { quitRequested = true; if !busy { stop(quit: true) } }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if quitting && !busy && bridgePID == 0 { return .terminateNow }
        quitAction(); return .terminateLater
    }
    @objc func forceAction() {
        let alert = NSAlert(); alert.messageText = "强制停止 Passport 后台？"; alert.informativeText = "仅终止此应用托管的后台及其子进程。未完成的数据发送可能被中断。"; alert.addButton(withTitle: "强制停止"); alert.addButton(withTitle: "取消")
        if alert.runModal() == .alertFirstButtonReturn { work.async { let result = self.shell("backend-force-stop"); DispatchQueue.main.async { self.fault = result.0 == 0 ? "" : result.1; self.forceItem.isHidden = result.0 == 0; self.bridgePID = result.0 == 0 ? 0 : self.bridgePID; self.state = [:]; self.update() } } }
    }
    func setLogin(_ enabled: Bool) { do { if enabled { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }; fault = "" } catch { fault = error.localizedDescription }; update() }
    @objc func loginAction() { setLogin(SMAppService.mainApp.status != .enabled); if SMAppService.mainApp.status == .requiresApproval { SMAppService.openSystemSettingsLoginItems() } }
    @objc func logAction() { NSWorkspace.shared.open(URL(fileURLWithPath: root + "/reports/bridge.log")) }
    @objc func woke() { if desired && !busy { reconnectAction() } }
    func applicationWillTerminate(_ notification: Notification) { if serverFD >= 0 { close(serverFD) }; unlink(appSocket) }
}
let app = NSApplication.shared
let delegate = Passport(); app.delegate = delegate
app.run()
