#if !PENTA_HAS_NETWORK_MANAGER
// NetworkManager.swift — v3.3
// Fix: Tự động chuyển sang Bluetooth khi kết nối (bỏ overrideOutputAudioPort)
//   - Xóa tất cả lệnh overrideOutputAudioPort(.speaker)
//   - Giữ nguyên category .playAndRecord + options cho phép Bluetooth
//   - Hệ thống sẽ tự chọn đầu ra phù hợp (loa ngoài hoặc Bluetooth)

import Foundation
import AVFoundation
import Combine

// MARK: - Models (giữ nguyên)

// MARK: - WAV Header Parser (giữ nguyên)

private struct WAVInfo {
    let sampleRate:    Double
    let channels:      AVAudioChannelCount
    let bitsPerSample: Int
    let pcmDataOffset: Int
}

private func parseWAVHeader(_ data: Data) -> WAVInfo? {
    guard data.count >= 44 else { return nil }
    guard data[0] == 0x52, data[1] == 0x49, data[2] == 0x46, data[3] == 0x46,
          data[8] == 0x57, data[9] == 0x41, data[10] == 0x56, data[11] == 0x45
    else { return nil }

    func u16(_ o: Int) -> UInt16 { UInt16(data[o]) | (UInt16(data[o+1]) << 8) }
    func u32(_ o: Int) -> UInt32 {
        UInt32(data[o]) | (UInt32(data[o+1]) << 8) |
        (UInt32(data[o+2]) << 16) | (UInt32(data[o+3]) << 24)
    }
    let channels      = u16(22)
    let sampleRate    = u32(24)
    let bitsPerSample = u16(34)

    var offset = 12
    while offset + 8 <= data.count {
        let id   = String(bytes: [data[offset], data[offset+1], data[offset+2], data[offset+3]], encoding: .ascii) ?? ""
        let size = Int(u32(offset + 4))
        if id == "data" {
            return WAVInfo(sampleRate: Double(sampleRate),
                           channels: AVAudioChannelCount(channels),
                           bitsPerSample: Int(bitsPerSample),
                           pcmDataOffset: offset + 8)
        }
        offset += 8 + size
    }
    return nil
}

// MARK: - NetworkManager

class Penta​NetworkManager: NSObject, ObservableObject, AVAudioPlayerDelegate {

    // Nested models to avoid global name collisions
    private struct ChatRequest: Encodable {
        let text: String
        let tts: Bool
        let speaker: String
        let speed: Double
    }

    struct ChatResponse: Decodable {
        let text: String
        let audiob64:       String?
        let aiLatencyMs:    Int?
        let totalLatencyMs: Int?
        let ttsError:       String?
        enum CodingKeys: String, CodingKey {
            case text
            case audiob64       = "audio_b64"
            case aiLatencyMs    = "ai_latency_ms"
            case totalLatencyMs = "total_latency_ms"
            case ttsError       = "tts_error"
        }
    }

    @Published var isConnected:         Bool   = false
    @Published var lastResponseText:    String = ""
    @Published var isPlayingAudio:      Bool   = false
    @Published var lastLatencyMs:       Int    = 0
    @Published var currentEmotionState: String = "neutral"   // ❤️ Trạng thái cảm xúc AI hiện tại

    var onAudioWillPlay: (() -> Void)?
    var onAudioDidEnd:   (() -> Void)?

    // WebSocket
    private var wsTask           : URLSessionWebSocketTask?
    private var wsSession        : URLSession?
    private var wsConnected      : Bool = false
    private var wsReconnectCount : Int  = 0
    private var receiveGeneration: Int  = 0

    // AVAudioEngine streaming
    private var audioEngine   = AVAudioEngine()
    private var playerNode    = AVAudioPlayerNode()
    private var engineRunning : Bool = false
    private var currentFormat : AVAudioFormat?
    private let audioQueue    = DispatchQueue(label: "penta.audio", qos: .userInteractive)
    private var pendingBuffers: Int = 0

    private var pingTimer: Timer?
    private var audioPlayer  : AVAudioPlayer?
    private var micBlockUntil: Date = .distantPast
    private var compressedAudioQueue: [Data] = []

    override init() {
        super.init()
        setupAudioSession()
        setupRouteChangeObserver()   // vẫn giữ để debug route thay đổi (không override nữa)
        startPingLoop()
    }

    deinit {
        NotificationCenter.default.removeObserver(self)
    }

    // MARK: - URLs

    private func loadAIServerPool() -> [String] {
        let defaults = UserDefaults.standard
        let stored = defaults.array(forKey: "ai_server_pool") as? [String] ?? []
        let trimmed = stored
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        if !trimmed.isEmpty {
            return Array(NSOrderedSet(array: trimmed)) as? [String] ?? trimmed
        }
        let legacy = defaults.string(forKey: "windows_ai_url") ?? "http://100.x.x.x:9090"
        return [legacy]
    }

    private var windowsAIURL: String {
        let defaults = UserDefaults.standard
        let active = defaults.string(forKey: "active_ai_server_url")?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !active.isEmpty {
            return active
        }
        return loadAIServerPool().first ?? "http://100.x.x.x:9090"
    }
    private var wsURL: String {
        var url = windowsAIURL
            .replacingOccurrences(of: "https://", with: "wss://")
            .replacingOccurrences(of: "http://",  with: "ws://")
            + "/ws/chat"
        // ── WebSocket Security: thêm token vào query param ──────────────────
        if !authToken.isEmpty {
            url += "?token=\(authToken)"
        }
        return url
    }
    private var macMiniURL: String {
        UserDefaults.standard.string(forKey: "tailscale_url") ?? "http://100.x.x.x:8080"
    }
    private var authToken: String {
        UserDefaults.standard.string(forKey: "auth_token") ?? ""
    }
    private var preferredSpeaker: String {
        UserDefaults.standard.string(forKey: "tts_speaker") ?? "NF"
    }
    private func headers() -> [String: String] {
        var h = ["Content-Type": "application/json"]
        if !authToken.isEmpty { h["Authorization"] = "Bearer \(authToken)" }
        return h
    }
    // MARK: - Penta Kuru (Windows) - thêm sau phần URLs

    private var pentaKuruURL: String {
        UserDefaults.standard.string(forKey: "penta_kuru_url") ?? ""
    }

    private var pentaKuruToken: String {
        UserDefaults.standard.string(forKey: "penta_kuru_token") ?? ""
    }

    // MARK: - Penta Kuru Command

    struct PentaKuruCommandResult: Decodable {
        let ok: Bool
        let stdout: String
        let stderr: String
        let exit_code: Int
    }

    func sendPentaKuruCommand(
        text: String,
        completion: @escaping (PentaKuruCommandResult) -> Void
    ) {
        guard let url = URL(string: "\(pentaKuruURL)/run") else {
            completion(PentaKuruCommandResult(ok: false, stdout: "", stderr: "URL không hợp lệ", exit_code: -1))
            return
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        // Sử dụng token riêng nếu có, nếu không thì dùng token chung
        let tokenToUse = pentaKuruToken.isEmpty ? authToken : pentaKuruToken
        if !tokenToUse.isEmpty {
            req.setValue("Bearer \(tokenToUse)", forHTTPHeaderField: "Authorization")
        }
        let body: [String: Any] = ["cmd": text]
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        req.timeoutInterval = 12

        URLSession.shared.dataTask(with: req) { data, _, error in
            let fallback = PentaKuruCommandResult(ok: false, stdout: "", stderr: error?.localizedDescription ?? "Lỗi kết nối", exit_code: -1)
            guard let data, error == nil else {
                DispatchQueue.main.async { completion(fallback) }
                return
            }
            do {
                let decoded = try JSONDecoder().decode(PentaKuruCommandResult.self, from: data)
                DispatchQueue.main.async { completion(decoded) }
            } catch {
                DispatchQueue.main.async { completion(fallback) }
            }
        }.resume()
    }
    // MARK: - Penta Kuru Command via AI (phân tích bằng Ollama rồi thực thi)
    func sendPentaKuruCommandViaAI(
        text: String,
        completion: @escaping (PentaKuruCommandResult) -> Void
    ) {
        guard let url = URL(string: "\(windowsAIURL)/api/execute_pc_command") else {
            completion(PentaKuruCommandResult(ok: false, stdout: "", stderr: "URL Mac mini không hợp lệ", exit_code: -1))
            return
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        // Dùng token chính (authToken) để xác thực với Mac mini
        if !authToken.isEmpty {
            req.setValue("Bearer \(authToken)", forHTTPHeaderField: "Authorization")
        }
        let body: [String: Any] = ["text": text]
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        req.timeoutInterval = 12
        
        URLSession.shared.dataTask(with: req) { data, _, error in
            let fallback = PentaKuruCommandResult(ok: false, stdout: "", stderr: error?.localizedDescription ?? "Lỗi kết nối", exit_code: -1)
            guard let data, error == nil else {
                DispatchQueue.main.async { completion(fallback) }
                return
            }
            // Kết quả trả về từ Mac mini có cấu trúc giống PentaKuruCommandResult
            do {
                let decoded = try JSONDecoder().decode(PentaKuruCommandResult.self, from: data)
                DispatchQueue.main.async { completion(decoded) }
            } catch {
                // Nếu decode lỗi, thử parse dict để lấy thông tin lỗi
                if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let errorMsg = json["error"] as? String {
                    DispatchQueue.main.async {
                        completion(PentaKuruCommandResult(ok: false, stdout: "", stderr: errorMsg, exit_code: -1))
                    }
                } else {
                    DispatchQueue.main.async { completion(fallback) }
                }
            }
        }.resume()
    }
    // MARK: - Audio Session (v3.3)

    private func setupAudioSession() {
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(
                .playAndRecord,
                mode: .default,
                options: [.defaultToSpeaker, .allowBluetooth, .allowBluetoothA2DP]
            )
            try session.setActive(true)
            // KHÔNG overrideOutputAudioPort(.speaker) -> hệ thống tự chọn route
            print("🔊 Audio session: category .playAndRecord with Bluetooth options")
        } catch {
            print("⚠️  AudioSession setup error: \(error)")
        }
    }

    // MARK: - Route Change Observer (chỉ log, không override)

    private func setupRouteChangeObserver() {
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleAudioRouteChange(_:)),
            name: AVAudioSession.routeChangeNotification,
            object: nil
        )
    }

    @objc private func handleAudioRouteChange(_ notification: Notification) {
        guard let info   = notification.userInfo,
              let rawVal = info[AVAudioSessionRouteChangeReasonKey] as? UInt,
              let reason = AVAudioSession.RouteChangeReason(rawValue: rawVal)
        else { return }

        // Log route change để debug, nhưng không override
        print("🔊 Route changed: \(reason)")
        // Có thể kiểm tra đầu ra hiện tại nếu muốn
        let currentRoute = AVAudioSession.sharedInstance().currentRoute
        let outputs = currentRoute.outputs.map { $0.portType }
        print("   Current outputs: \(outputs)")
    }

    // MARK: - WebSocket (giữ nguyên)

    private func connectWebSocket() {
        guard let url = URL(string: wsURL) else {
            print("⚠️  WS URL không hợp lệ: \(wsURL)"); return
        }
        wsSession = URLSession(configuration: .default, delegate: nil, delegateQueue: nil)
        var request = URLRequest(url: url)
        if !authToken.isEmpty {
            request.setValue("Bearer \(authToken)", forHTTPHeaderField: "Authorization")
        }
        wsTask = wsSession?.webSocketTask(with: request)
        wsTask?.resume()
        wsConnected      = true
        wsReconnectCount = 0
        print("🔌 WebSocket connected: \(wsURL)")
    }

    private func disconnectWebSocket() {
        wsTask?.cancel(with: .normalClosure, reason: nil)
        wsTask      = nil
        wsConnected = false
        print("🔌 WebSocket disconnected")
    }

    private func ensureConnected() {
        let state = wsTask?.state
        if state == .running { return }
        wsReconnectCount += 1
        if wsReconnectCount > 5 {
            print("⚠️  WS reconnect quá nhiều lần — đợi 5s")
            DispatchQueue.main.asyncAfter(deadline: .now() + 5) {
                self.wsReconnectCount = 0
                self.connectWebSocket()
            }
            return
        }
        connectWebSocket()
    }

    func sendChatWS(
        text:    String,
        mode:    String = "chat",
        onText:  @escaping (String, Int) -> Void,
        onError: @escaping (String)      -> Void
    ) {
        guard !isPlayingAudio else {
            onError("Đang phát audio — bỏ qua"); return
        }

        ensureConnected()

        let payload: [String: Any] = [
            "text":    text,
            "mode":    mode,
            "tts":     true,
            "token":   authToken,
            "speaker": preferredSpeaker,
            "speed":   1.0
        ]
        guard let jsonData   = try? JSONSerialization.data(withJSONObject: payload),
              let jsonString = String(data: jsonData, encoding: .utf8)
        else { print("⚠️  WS payload encode thất bại"); return }

        wsTask?.send(.string(jsonString)) { err in
            if let err { print("⚠️  WS send error: \(err)") }
            else       { print("📤 WS sent: \(jsonString.prefix(80))") }
        }

        receiveGeneration += 1
        let gen = receiveGeneration
        receiveLoop(generation: gen, onText: onText, onError: onError)
    }

    private func receiveLoop(
        generation: Int,
        onText:     @escaping (String, Int) -> Void,
        onError:    @escaping (String)      -> Void
    ) {
        guard generation == receiveGeneration else { return }

        wsTask?.receive { [weak self] result in
            guard let self, generation == self.receiveGeneration else { return }

            switch result {
            case .failure(let err):
                self.wsConnected = false
                DispatchQueue.main.async { onError(err.localizedDescription) }

            case .success(let message):
                switch message {

                case .string(let json):
                    guard let data = json.data(using: .utf8),
                          let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                    else {
                        self.receiveLoop(generation: generation, onText: onText, onError: onError)
                        return
                    }

                    let type = obj["type"] as? String ?? ""

                    switch type {
                    case "response", "text":
                        let txt = obj["text"] as? String ?? ""
                        let ms  = obj["ai_latency_ms"] as? Int ?? 0
                        DispatchQueue.main.async {
                            self.lastResponseText = txt
                            self.lastLatencyMs    = ms
                            onText(txt, ms)
                        }
                        self.receiveLoop(generation: generation, onText: onText, onError: onError)

                    case "tts_start":
                        DispatchQueue.main.async {
                            self.onAudioWillPlay?()
                        }
                        self.receiveLoop(generation: generation, onText: onText, onError: onError)

                    case "audio_chunk":
                        if let b64 = obj["audio_b64"] as? String,
                           let audioData = Data(base64Encoded: b64) {
                            let mimeType = (obj["mime_type"] as? String ?? "audio/wav").lowercased()
                            if mimeType.contains("mpeg") || mimeType.contains("mp3") {
                                self.enqueueCompressedAudio(audioData)
                            } else {
                                self.scheduleWAVChunk(audioData)
                            }
                        }
                        self.receiveLoop(generation: generation, onText: onText, onError: onError)

                    case "audio_end":
                        let totalMs = obj["total_latency_ms"] as? Int ?? 0
                        DispatchQueue.main.async {
                            if totalMs > 0 { self.lastLatencyMs = totalMs }
                        }
                        self.finishAudioStream()
                        self.receiveLoop(generation: generation, onText: onText, onError: onError)

                    case "error":
                        let msg = obj["msg"] as? String ?? "server error"
                        DispatchQueue.main.async { onError(msg) }
                        self.receiveLoop(generation: generation, onText: onText, onError: onError)

                    case "ping":
                        self.receiveLoop(generation: generation, onText: onText, onError: onError)

                    default:
                        self.receiveLoop(generation: generation, onText: onText, onError: onError)
                    }

                case .data(let wavData):
                    self.scheduleWAVChunk(wavData)
                    self.receiveLoop(generation: generation, onText: onText, onError: onError)

                @unknown default:
                    self.receiveLoop(generation: generation, onText: onText, onError: onError)
                }
            }
        }
    }

    // MARK: - AVAudioEngine Streaming (không override speaker)

    private func prepareAudioEngine(format: AVAudioFormat) {
        dispatchPrecondition(condition: .onQueue(audioQueue))

        if audioEngine.isRunning {
            playerNode.stop()
            audioEngine.stop()
        }
        audioEngine.detach(playerNode)

        // Chỉ đảm bảo session active, không override output
        let session = AVAudioSession.sharedInstance()
        try? session.setActive(true)

        audioEngine.attach(playerNode)
        audioEngine.connect(playerNode, to: audioEngine.mainMixerNode, format: format)

        playerNode.volume                        = 1.0
        audioEngine.mainMixerNode.outputVolume   = 1.0

        do {
            try audioEngine.start()
            playerNode.play()
            pendingBuffers = 0
            print("🎵 AVAudioEngine @ \(Int(format.sampleRate))Hz ch\(format.channelCount)")
        } catch {
            print("⚠️  AudioEngine start: \(error)")
            DispatchQueue.main.async { [weak self] in
                self?.engineRunning  = false
                self?.isPlayingAudio = false
                self?.onAudioDidEnd?()
            }
            return
        }

        DispatchQueue.main.async { [weak self] in
            self?.engineRunning  = true
            self?.isPlayingAudio = true
        }
    }

    func scheduleWAVChunk(_ wavData: Data) {
        audioQueue.async { [weak self] in
            self?.scheduleWAVChunk_internal(wavData)
        }
    }

    private func scheduleWAVChunk_internal(_ wavData: Data) {
        dispatchPrecondition(condition: .onQueue(audioQueue))

        guard let info = parseWAVHeader(wavData) else {
            print("⚠️  Invalid WAV header (\(wavData.count)B)"); return
        }
        guard wavData.count > info.pcmDataOffset,
              info.sampleRate > 0, info.channels > 0
        else { print("⚠️  WAV data rỗng"); return }

        let pcmData = wavData.subdata(in: info.pcmDataOffset..<wavData.count)

        guard let format = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate:   info.sampleRate,
            channels:     info.channels,
            interleaved:  false
        ) else { print("⚠️  AVAudioFormat nil"); return }

        let needRebuild = !audioEngine.isRunning
            || currentFormat?.sampleRate   != format.sampleRate
            || currentFormat?.channelCount != format.channelCount

        if needRebuild {
            currentFormat = format
            prepareAudioEngine(format: format)
            guard audioEngine.isRunning else { return }
        }

        let bytesPerSample = info.bitsPerSample == 16 ? 2 : 4
        let frameCount = AVAudioFrameCount(
            pcmData.count / (bytesPerSample * Int(info.channels))
        )
        guard frameCount > 0 else { return }
        guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount) else {
            print("⚠️  PCMBuffer alloc thất bại"); return
        }
        buffer.frameLength = frameCount

        if info.bitsPerSample == 16 {
            pcmData.withUnsafeBytes { rawPtr in
                let src = rawPtr.bindMemory(to: Int16.self)
                for ch in 0..<Int(info.channels) {
                    guard let dst = buffer.floatChannelData?[ch] else { continue }
                    for f in 0..<Int(frameCount) {
                        let idx = f * Int(info.channels) + ch
                        dst[f] = idx < src.count ? Float(src[idx]) / 32768.0 : 0
                    }
                }
            }
        } else {
            pcmData.withUnsafeBytes { rawPtr in
                let src = rawPtr.bindMemory(to: Float.self)
                for ch in 0..<Int(info.channels) {
                    guard let dst = buffer.floatChannelData?[ch] else { continue }
                    for f in 0..<Int(frameCount) {
                        let idx = f * Int(info.channels) + ch
                        dst[f] = idx < src.count ? src[idx] : 0
                    }
                }
            }
        }

        pendingBuffers += 1

        // Không override speaker ở đây nữa
        playerNode.volume                      = 1.0
        audioEngine.mainMixerNode.outputVolume = 1.0

        playerNode.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
            self?.audioQueue.async {
                guard let self else { return }
                self.pendingBuffers -= 1
                print("✅ Buffer played, pending=\(self.pendingBuffers)")
                if self.pendingBuffers <= 0 && !self.engineRunning {
                    self.teardownAudioEngine_internal()
                }
            }
        }
    }

    func finishAudioStream() {
        audioQueue.async { [weak self] in
            guard let self else { return }
            if self.pendingBuffers <= 0 {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
                    self.audioQueue.async { self.teardownAudioEngine_internal() }
                }
            } else {
                DispatchQueue.main.async { self.engineRunning = false }
                print("🏁 audio_end, đợi \(self.pendingBuffers) buffer(s)")
            }
        }
    }

    private func teardownAudioEngine_internal() {
        dispatchPrecondition(condition: .onQueue(audioQueue))
        guard audioEngine.isRunning || pendingBuffers == 0 else { return }

        playerNode.stop()
        audioEngine.stop()
        audioEngine.detach(playerNode)
        pendingBuffers = 0
        currentFormat  = nil
        print("🎵 AVAudioEngine torn down")

        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.engineRunning  = false
            self.isPlayingAudio = false
            self.restoreRecordSession()
            self.micBlockUntil = Date().addingTimeInterval(0.6)
            self.onAudioDidEnd?()
        }
    }

    func stopAudio() {
        audioQueue.async { [weak self] in self?.teardownAudioEngine_internal() }
        DispatchQueue.main.async {
            self.audioPlayer?.stop()
            self.audioPlayer = nil
            self.compressedAudioQueue.removeAll()
            self.isPlayingAudio = false
        }
    }

    // MARK: - Compressed Audio Queue

    private func enqueueCompressedAudio(_ data: Data) {
        DispatchQueue.main.async {
            self.compressedAudioQueue.append(data)
            if self.audioPlayer == nil || self.audioPlayer?.isPlaying == false {
                self.playNextCompressedAudio()
            }
        }
    }

    private func playNextCompressedAudio() {
        guard !compressedAudioQueue.isEmpty else {
            audioPlayer = nil
            isPlayingAudio = false
            restoreRecordSession()
            micBlockUntil = Date().addingTimeInterval(0.8)
            onAudioDidEnd?()
            return
        }

        let data = compressedAudioQueue.removeFirst()
        do {
            let session = AVAudioSession.sharedInstance()
            try? session.setActive(true)
            let player = try AVAudioPlayer(data: data)
            player.delegate = self
            player.volume = 1.0
            player.prepareToPlay()
            audioPlayer = player
            let ok = player.play()
            isPlayingAudio = ok
            if !ok {
                playNextCompressedAudio()
            }
        } catch {
            print("⚠️ Compressed audio play error: \(error)")
            playNextCompressedAudio()
        }
    }

    // MARK: - HTTP sendChat (giữ nguyên)

    func sendChat(
        text:       String,
        tts:        Bool = true,
        onResponse: @escaping (ChatResponse) -> Void,
        onError:    @escaping (String)       -> Void
    ) {
        let now = Date()
        if now < micBlockUntil || isPlayingAudio {
            onError("Đang phát TTS — bỏ qua input"); return
        }
        guard let url = URL(string: "\(windowsAIURL)/api/chat") else {
            onError("URL không hợp lệ"); return
        }
        var req = URLRequest(url: url)
        req.httpMethod  = "POST"
        req.httpBody    = try? JSONEncoder().encode(ChatRequest(
            text: text, tts: tts, speaker: preferredSpeaker, speed: 1.0))
        headers().forEach { req.setValue($1, forHTTPHeaderField: $0) }
        req.timeoutInterval = 35

        URLSession.shared.dataTask(with: req) { [weak self] data, _, error in
            guard let self else { return }
            if let error = error {
                DispatchQueue.main.async { onError(error.localizedDescription) }; return
            }
            guard let data else {
                DispatchQueue.main.async { onError("Không nhận được dữ liệu") }; return
            }
            do {
                let decoded = try JSONDecoder().decode(ChatResponse.self, from: data)
                DispatchQueue.main.async {
                    self.lastResponseText = decoded.text
                    self.lastLatencyMs    = decoded.totalLatencyMs ?? decoded.aiLatencyMs ?? 0
                    onResponse(decoded)
                    if let b64 = decoded.audiob64, !b64.isEmpty {
                        self.micBlockUntil = Date().addingTimeInterval(2.0)
                        self.onAudioWillPlay?()
                        self.playAudioBase64(b64)
                    }
                }
            } catch {
                let msg = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["error"] as? String
                DispatchQueue.main.async { onError(msg ?? "Parse error: \(error)") }
            }
        }.resume()
    }

    // MARK: - HTTP Device Command

    func sendCommand(endpoint: String, completion: @escaping (Bool) -> Void) {
        guard let url = URL(string: "\(macMiniURL)\(endpoint)") else {
            completion(false); return
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        headers().forEach { req.setValue($1, forHTTPHeaderField: $0) }
        req.timeoutInterval = 10
        URLSession.shared.dataTask(with: req) { _, response, error in
            let ok = error == nil && (response as? HTTPURLResponse)?.statusCode == 200
            DispatchQueue.main.async { completion(ok) }
        }.resume()
    }

    // MARK: - Ollama Device Command

    /// Response struct cho /api/ollama_command — Decodable, type-safe.
    struct OllamaCommandResult: Decodable {
        let action:     String?
        let target:     String?
        let parameters: String?
        let error:      String?
        let raw:        String?
    }

    /// Gọi server để phân tích câu lệnh tự nhiên qua Ollama (chế độ DEVICE).
    /// Hoàn toàn tách biệt với sendChat/sendChatWS — không ảnh hưởng đến chat.
    func ollamaCommand(
        text:              String,
        availableCommands: [String] = [],
        completion:        @escaping (OllamaCommandResult) -> Void
    ) {
        guard let url = URL(string: "\(windowsAIURL)/api/ollama_command") else {
            completion(OllamaCommandResult(action: nil, target: nil, parameters: nil,
                                           error: "URL lỗi", raw: nil))
            return
        }
        var body: [String: Any] = ["text": text]
        if !availableCommands.isEmpty {
            body["available_commands"] = availableCommands
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.httpBody   = try? JSONSerialization.data(withJSONObject: body)
        headers().forEach { req.setValue($1, forHTTPHeaderField: $0) }
        req.timeoutInterval = 12

        URLSession.shared.dataTask(with: req) { data, _, error in
            let fallback = OllamaCommandResult(
                action: nil, target: nil, parameters: nil,
                error:  error?.localizedDescription ?? "Lỗi kết nối", raw: nil
            )
            guard let data, error == nil else {
                DispatchQueue.main.async { completion(fallback) }
                return
            }
            let decoded = (try? JSONDecoder().decode(OllamaCommandResult.self, from: data)) ?? fallback
            DispatchQueue.main.async { completion(decoded) }
        }.resume()
    }
    // MARK: - Device Command (gửi đến Mac mini)
    func sendDeviceCommand(
        text:              String,
        availableCommands: [String] = [],
        completion:        @escaping (OllamaCommandResult) -> Void
    ) {
        guard let url = URL(string: "\(macMiniURL)/api/ollama_command") else {
            completion(OllamaCommandResult(action: nil, target: nil, parameters: nil,
                                           error: "URL Mac mini không hợp lệ", raw: nil))
            return
        }
        var body: [String: Any] = ["text": text]
        if !availableCommands.isEmpty {
            body["available_commands"] = availableCommands
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.httpBody   = try? JSONSerialization.data(withJSONObject: body)
        headers().forEach { req.setValue($1, forHTTPHeaderField: $0) }
        req.timeoutInterval = 12

        URLSession.shared.dataTask(with: req) { data, _, error in
            let fallback = OllamaCommandResult(
                action: nil, target: nil, parameters: nil,
                error:  error?.localizedDescription ?? "Lỗi kết nối", raw: nil
            )
            guard let data, error == nil else {
                DispatchQueue.main.async { completion(fallback) }
                return
            }
            let decoded = (try? JSONDecoder().decode(OllamaCommandResult.self, from: data)) ?? fallback
            DispatchQueue.main.async { completion(decoded) }
        }.resume()
    }    // MARK: - Teach

    func teach(fact: String, completion: @escaping (Bool, String) -> Void) {
        guard let url = URL(string: "\(windowsAIURL)/api/teach") else {
            completion(false, "URL lỗi"); return
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.httpBody   = try? JSONSerialization.data(withJSONObject: ["fact": fact])
        headers().forEach { req.setValue($1, forHTTPHeaderField: $0) }
        req.timeoutInterval = 15
        URLSession.shared.dataTask(with: req) { data, _, error in
            guard error == nil, let data else {
                DispatchQueue.main.async {
                    completion(false, error?.localizedDescription ?? "Lỗi")
                }; return
            }
            let resp    = (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
            let message = resp["response"] as? String ?? "Đã dạy"
            DispatchQueue.main.async { completion(true, message) }
        }.resume()
    }

    // MARK: - Legacy Audio Player (HTTP fallback) – không override

    private func playAudioBase64(_ b64: String) {
        let cleaned = b64.components(separatedBy: ",").last ?? b64
        guard let data = Data(base64Encoded: cleaned) else { return }
        do {
            let session = AVAudioSession.sharedInstance()
            try? session.setActive(true)
            // KHÔNG overrideOutputAudioPort

            audioPlayer         = try AVAudioPlayer(data: data)
            audioPlayer?.delegate = self
            audioPlayer?.volume   = 1.0
            audioPlayer?.prepareToPlay()
            let ok = audioPlayer?.play() ?? false
            DispatchQueue.main.async { self.isPlayingAudio = ok }
        } catch {
            print("⚠️ Audio play error: \(error)")
        }
    }

    // MARK: - Restore Record Session (không override)

    private func restoreRecordSession() {
        do {
            let session = AVAudioSession.sharedInstance()
            try? session.setActive(false)
            try session.setCategory(.playAndRecord,
                                    mode: .measurement,
                                    options: [.defaultToSpeaker, .duckOthers, .allowBluetooth])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
            // KHÔNG overrideOutputAudioPort
        } catch {
            print("⚠️ Restore record session error: \(error)")
        }
    }

    // MARK: - Ping (giữ nguyên)

    func ping(completion: @escaping (Bool) -> Void) {
        guard let url = URL(string: "\(windowsAIURL)/api/health") else {
            completion(false); return
        }
        var req = URLRequest(url: url)
        headers().forEach { req.setValue($1, forHTTPHeaderField: $0) }
        req.timeoutInterval = 5
        URLSession.shared.dataTask(with: req) { data, response, error in
            var ok = error == nil && (response as? HTTPURLResponse)?.statusCode == 200
            if ok, let data,
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                ok = json["ai_ready"] as? Bool ?? false
            }
            completion(ok)
        }.resume()
    }

    private func startPingLoop() {
        pingTimer = Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { [weak self] _ in
            self?.ping { ok in DispatchQueue.main.async { self?.isConnected = ok } }
        }
        ping { [weak self] ok in DispatchQueue.main.async { self?.isConnected = ok } }
    }

    // MARK: - AVAudioPlayerDelegate

    func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        DispatchQueue.main.async {
            if !self.compressedAudioQueue.isEmpty {
                self.playNextCompressedAudio()
                return
            }
            self.audioPlayer = nil
            self.isPlayingAudio = false
            self.restoreRecordSession()
            self.micBlockUntil = Date().addingTimeInterval(0.8)
            self.onAudioDidEnd?()
        }
    }
    func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
        DispatchQueue.main.async {
            print("⚠️ Audio decode error: \(error?.localizedDescription ?? "unknown")")
            if !self.compressedAudioQueue.isEmpty {
                self.playNextCompressedAudio()
                return
            }
            self.audioPlayer = nil
            self.isPlayingAudio = false
            self.restoreRecordSession()
            self.micBlockUntil = Date().addingTimeInterval(0.8)
            self.onAudioDidEnd?()
        }
    }
}
#endif // !PENTA_HAS_NETWORK_MANAGER

// MARK: - Hormone Status Models

/// Trạng thái hormone nhận từ /api/hormone_status
struct HormoneLevels: Decodable {
    let dopamine:       Double?
    let serotonin:      Double?
    let oxytocin:       Double?
    let cortisol:       Double?
    let adrenaline:     Double?
    let GABA:           Double?  // swiftlint:disable:this identifier_name
    let norepinephrine: Double?
}

struct HormoneTemperament: Decodable {
    let name:                String?
    let dopamineSensitivity:  Double?
    let cortisolReactivity:   Double?
    let oxytocinaBaslineAdj:  Double?
    let gabaInhibition:       Double?
    enum CodingKeys: String, CodingKey {
        case name
        case dopamineSensitivity  = "dopamine_sensitivity"
        case cortisolReactivity   = "cortisol_reactivity"
        case oxytocinaBaslineAdj  = "oxytocin_baseline_adj"
        case gabaInhibition       = "gaba_inhibition"
    }
}

struct HormoneStatusData: Decodable {
    let hormoneState:    String?
    let hormoneLevels:   HormoneLevels?
    let dominantTrait:   String?
    let interactions:    Int?
    let description:     String?
    let temperament:     HormoneTemperament?
    let semanticLearned: Int?
    enum CodingKeys: String, CodingKey {
        case hormoneState    = "hormone_state"
        case hormoneLevels   = "hormone_levels"
        case dominantTrait   = "dominant_trait"
        case interactions
        case description
        case temperament
        case semanticLearned = "semantic_learned"
    }
}

struct HormoneStatusResponse: Decodable {
    let status: String
    let data:   HormoneStatusData?
}

// MARK: - fetchHormoneStatus Extension
extension Penta​NetworkManager {
    /// Lấy trạng thái hormone từ server và cập nhật currentEmotionState.
    func fetchHormoneStatus(completion: ((HormoneStatusData?) -> Void)? = nil) {
        guard let url = URL(string: "\(windowsAIURL)/api/hormone_status") else {
            completion?(nil); return
        }
        var req = URLRequest(url: url)
        req.timeoutInterval = 5
        // Không cần auth token cho endpoint này
        URLSession.shared.dataTask(with: req) { [weak self] data, _, error in
            guard let data, error == nil else {
                DispatchQueue.main.async { completion?(nil) }
                return
            }
            let decoded = try? JSONDecoder().decode(HormoneStatusResponse.self, from: data)
            let statusData = decoded?.data
            DispatchQueue.main.async {
                if let state = statusData?.hormoneState {
                    self?.currentEmotionState = state
                }
                completion?(statusData)
            }
        }.resume()
    }

    /// Emoji đại diện cho emotion state hiện tại (dùng trong UI).
    var emotionEmoji: String {
        switch currentEmotionState {
        case "excited_warm", "content_loving": return "😊"
        case "curious_energetic":              return "🧐"
        case "calm_confident":                 return "😌"
        case "anxious", "stressed":            return "😰"
        case "tired_uneasy", "sleepy_calm":    return "😴"
        case "mildly_stressed":                return "😟"
        case "low_energy":                     return "😑"
        case "surprised_alert":                return "😲"
        case "guarded":                        return "🤔"
        default:                               return "🤖"
        }
    }
}

