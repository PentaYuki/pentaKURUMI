// VoiceEngine.swift — v3.1
// Fix: Audio session luôn override speaker sau setActive
//      Bỏ try? ở những chỗ quan trọng để debug dễ hơn

import Foundation
import AVFoundation
import Speech
import Combine
import UIKit

// MARK: - Enums

enum ListeningMode: String, CaseIterable {
    case continuous = "CONTINUOUS"
    case wakeWord   = "WAKE_WORD"
    var displayName: String {
        switch self {
        case .continuous: return "LIÊN TỤC"
        case .wakeWord:   return "WAKE WORD"
        }
    }
}

enum VoiceState: Equatable {
    case sleeping, woken, listening, countdown, executing, responding
}

enum CommandMode: String, CaseIterable {
    case device = "DEVICE"
    case chat   = "CHAT"
    var icon:  String { self == .chat ? "bubble.left.fill" : "bolt.fill" }
    var label: String { self == .chat ? "CHAT" : "LỆNH" }
}

// MARK: - VoiceEngine

class VoiceEngine: NSObject, ObservableObject {

    // MARK: Published
    @Published var voiceState        : VoiceState    = .sleeping
    @Published var isListening       : Bool          = false
    @Published var isConnected       : Bool          = false
    @Published var lastRecognized    : String        = ""
    @Published var currentTranscript : String        = ""
    @Published var statusMessage     : String        = ""
    @Published var silenceProgress   : Double        = 0
    @Published var listeningMode     : ListeningMode = .wakeWord
    @Published var commandMode       : CommandMode   = .chat
    @Published var aiResponseText    : String        = ""
    @Published var isPlayingAudio    : Bool          = false
    @Published var lastLatencyMs     : Int           = 0

    @Published var wakeWord: String = "Penta" {
        didSet {
            UserDefaults.standard.set(wakeWord, forKey: "wake_word")
            if listeningMode == .wakeWord && voiceState == .sleeping {
                statusMessage = "Nói \"\(wakeWord)\" để kích hoạt"
            }
        }
    }

    // MARK: Private — Audio / Speech
    private var audioEngine        = AVAudioEngine()
    private var recognitionRequest : SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask    : SFSpeechRecognitionTask?
    private var speechRecognizer   : SFSpeechRecognizer?
    private var sessionGeneration  : Int = 0

    // Echo prevention
    private var recognitionPaused : Bool = false
    private let echoTailDelay: TimeInterval = 0.6

    // MARK: Private — Silence detection
    private var silenceTimer   : Timer?
    private var progressTimer  : Timer?
    private var countdownStart : Date?
    private var lastSeenText   : String = ""
    private var pendingText    : String = ""
    private let silenceDuration: TimeInterval = 0.8

    // MARK: Private — Dependencies
    private(set) var networkManager: Penta​NetworkManager
    private var commandStore       : CommandStore?
    private var cancellables       = Set<AnyCancellable>()

    // MARK: Init
    override init() {
        networkManager = Penta​NetworkManager()
        super.init()

        if let saved = UserDefaults.standard.string(forKey: "wake_word"), !saved.isEmpty {
            wakeWord = saved
        }

        // Khởi tạo SFSpeechRecognizer trước — có thể chậm, nên init sớm
        speechRecognizer = SFSpeechRecognizer(locale: Locale(identifier: "vi-VN"))
            ?? SFSpeechRecognizer(locale: Locale(identifier: "en-US"))

        networkManager.$isConnected
            .receive(on: DispatchQueue.main)
            .assign(to: \.isConnected, on: self)
            .store(in: &cancellables)

        networkManager.$isPlayingAudio
            .receive(on: DispatchQueue.main)
            .sink { [weak self] playing in
                guard let self else { return }
                self.isPlayingAudio = playing
                if playing {
                    self.pauseRecognition()
                } else {
                    self.scheduleResumeRecognition()
                }
            }
            .store(in: &cancellables)

        networkManager.onAudioWillPlay = { [weak self] in self?.pauseRecognition() }
        networkManager.onAudioDidEnd   = { [weak self] in self?.scheduleResumeRecognition() }
    }

    func setCommandStore(_ store: CommandStore) { commandStore = store }

    // MARK: - Permissions

    func requestPermissions() {
        SFSpeechRecognizer.requestAuthorization { [weak self] status in
            DispatchQueue.main.async {
                if status != .authorized {
                    self?.statusMessage = "Cần quyền nhận diện giọng nói"
                }
            }
        }
        AVAudioApplication.requestRecordPermission { [weak self] granted in
            if !granted {
                DispatchQueue.main.async { self?.statusMessage = "Cần quyền microphone" }
            }
        }
    }

    // MARK: - Echo Fix: Pause / Resume Recognition

    private func pauseRecognition() {
        guard isListening, !recognitionPaused else { return }
        recognitionPaused = true
        sessionGeneration += 1
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionRequest?.endAudio()
        recognitionTask?.cancel()
        recognitionRequest = nil
        recognitionTask    = nil
        DispatchQueue.main.async {
            self.clearTranscriptState()
            self.cancelTimers()
        }
    }

    private func scheduleResumeRecognition() {
        guard recognitionPaused else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + echoTailDelay) {
            guard self.recognitionPaused, self.isListening else { return }
            self.recognitionPaused = false
            do {
                try self.setupAudioSession()   // ⭐ FIX: dùng helper để đảm bảo speaker override
            } catch {
                print("⚠️ Resume audio session error: \(error)")
            }
            try? self.beginRecognitionSession()
            self.transitionTo(self.listeningMode == .wakeWord ? .sleeping : .listening)
        }
    }

    // MARK: - Start / Stop Listening

    func startListening() {
        guard !isListening else { return }
        do {
            try setupAudioSession()
            try beginRecognitionSession()
            DispatchQueue.main.async {
                self.isListening = true
                self.transitionTo(self.listeningMode == .continuous ? .listening : .sleeping)
            }
        } catch {
            DispatchQueue.main.async {
                self.statusMessage = "Lỗi audio: \(error.localizedDescription)"
            }
        }
    }

    func stopListening() {
        cancelTimers()
        sessionGeneration += 1
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionRequest?.endAudio()
        recognitionTask?.cancel()
        recognitionRequest = nil
        recognitionTask    = nil
        recognitionPaused  = false
        DispatchQueue.main.async {
            self.isListening = false
            self.voiceState  = .sleeping
            self.clearTranscriptState()
            self.statusMessage = ""
        }
    }

    func switchMode(to mode: ListeningMode) {
        listeningMode = mode
        guard isListening else { return }
        cancelTimers(); clearTranscriptState()
        transitionTo(mode == .continuous ? .listening : .sleeping)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
            try? self.beginRecognitionSession()
        }
    }

    // MARK: - Send to AI — WebSocket (primary)

    func sendTextToAI(_ text: String) {
        transitionTo(.responding)
        aiResponseText = ""
        let wsMode = (commandMode == .chat) ? "chat" : "cmd"

        networkManager.sendChatWS(
            text:    text,
            mode:    wsMode,
            onText:  { [weak self] responseText, latencyMs in
                guard let self else { return }
                let shouldHaptic = self.aiResponseText.isEmpty && !responseText.isEmpty
                self.aiResponseText = responseText
                if latencyMs > 0 {
                    self.lastLatencyMs = latencyMs
                }
                self.statusMessage  = "✓ \(responseText.prefix(40))…"
                if shouldHaptic {
                    self.haptic(.medium)
                }
            },
            onError: { [weak self] err in
                guard let self else { return }
                self.statusMessage = "✗ \(err)"
                self.hapticResult(false)
                DispatchQueue.main.asyncAfter(deadline: .now() + 2) { self.returnToIdle() }
            }
        )

        networkManager.$isPlayingAudio
            .filter { !$0 }
            .first()
            .delay(for: .seconds(echoTailDelay + 0.1), scheduler: DispatchQueue.main)
            .sink { [weak self] _ in
                guard let self, self.voiceState == .responding else { return }
                self.returnToIdle()
            }
            .store(in: &cancellables)
    }

    // MARK: - Keyboard Input

    func sendTextFromKeyboard(_ text: String) {
        guard !isPlayingAudio else { return }
        // Thin client: app chỉ chọn mode (chat/cmd), backend chịu trách nhiệm xử lý.
        sendTextToAI(text)
    }

    // MARK: - App Lifecycle

    func appDidEnterBackground() {
        networkManager.appDidEnterBackground()
        cancelTimers()
        if isListening {
            recognitionPaused = true
            sessionGeneration += 1
            audioEngine.inputNode.removeTap(onBus: 0)
            recognitionRequest?.endAudio()
            recognitionTask?.cancel()
            recognitionRequest = nil
            recognitionTask = nil
        }
    }

    func appDidBecomeActive() {
        networkManager.appDidBecomeActive()
        guard isListening else { return }
        recognitionPaused = false
        do {
            try setupAudioSession()
            try beginRecognitionSession()
        } catch {
            statusMessage = "Không khôi phục được microphone: \(error.localizedDescription)"
        }
    }

    // MARK: - ⭐ Audio Session (FIX v3.1)

    /// Setup audio session với speaker override bắt buộc.
    /// Dùng helper này ở mọi nơi thay vì inline để đảm bảo nhất quán.
    private func setupAudioSession() throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(
            .playAndRecord,
            mode: .measurement,
            options: [.defaultToSpeaker, .duckOthers, .allowBluetooth]
        )
        try session.setActive(true, options: .notifyOthersOnDeactivation)
        // ⭐ FIX: Bắt buộc ra loa ngoài sau khi set active
        try session.overrideOutputAudioPort(.speaker)
    }

    // MARK: - Recognition Session

    private func beginRecognitionSession() throws {
        sessionGeneration += 1
        let myGen = sessionGeneration

        recognitionTask?.cancel(); recognitionTask = nil
        audioEngine.inputNode.removeTap(onBus: 0)

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults  = true
        request.requiresOnDeviceRecognition = false
        recognitionRequest = request

        let inputNode = audioEngine.inputNode
        let format    = inputNode.outputFormat(forBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buf, _ in
            guard self?.recognitionPaused == false else { return }
            request.append(buf)
        }

        if !audioEngine.isRunning { audioEngine.prepare(); try audioEngine.start() }

        recognitionTask = speechRecognizer?.recognitionTask(with: request) { [weak self] result, error in
            guard let self, myGen == self.sessionGeneration else { return }
            guard !self.recognitionPaused else { return }

            if let result {
                let text = result.bestTranscription.formattedString
                DispatchQueue.main.async { self.onNewTranscript(text, isFinal: result.isFinal) }
            }
            if (error != nil || result?.isFinal == true) && self.isListening && !self.recognitionPaused {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
                    guard myGen == self.sessionGeneration, !self.recognitionPaused else { return }
                    try? self.beginRecognitionSession()
                }
            }
        }
    }

    // MARK: - Transcript Processing

    private func onNewTranscript(_ text: String, isFinal: Bool) {
        guard isListening, !text.isEmpty,
              voiceState != .responding,
              !recognitionPaused,
              !isPlayingAudio
        else { return }
        listeningMode == .wakeWord ? handleWakeWordFlow(text) : handleContinuousFlow(text)
    }

    private func handleWakeWordFlow(_ text: String) {
        switch voiceState {
        case .sleeping:
            if containsWakeWord(text) { doWakeUp() }
        case .woken:
            let cmd = stripWakeWord(from: text)
            guard !cmd.isEmpty else { return }
            currentTranscript = cmd
            if cmd != lastSeenText { lastSeenText = cmd; scheduleCountdown(for: cmd) }
        case .countdown:
            let cmd = stripWakeWord(from: text)
            guard !cmd.isEmpty, cmd != lastSeenText else { return }
            lastSeenText = cmd; currentTranscript = cmd; pendingText = cmd
            resetCountdown(for: cmd)
        default: break
        }
    }

    private func handleContinuousFlow(_ text: String) {
        guard voiceState == .listening || voiceState == .countdown,
              text != lastSeenText else { return }
        lastSeenText = text; currentTranscript = text; lastRecognized = text
        voiceState == .listening ? scheduleCountdown(for: text) : resetCountdown(for: text)
    }

    private func doWakeUp() {
        clearTranscriptState(); transitionTo(.woken); haptic(.light)
    }

    private func returnToIdle() {
        cancelTimers(); clearTranscriptState()
        transitionTo(listeningMode == .wakeWord ? .sleeping : .listening)
        guard isListening, !recognitionPaused else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
            guard self.isListening, !self.recognitionPaused else { return }
            try? self.beginRecognitionSession()
        }
    }

    private func clearTranscriptState() {
        currentTranscript = ""; lastSeenText = ""; pendingText = ""; silenceProgress = 0
    }

    // MARK: - Silence Countdown

    private func scheduleCountdown(for text: String) {
        pendingText = text; cancelTimers(); transitionTo(.countdown)
        silenceProgress = 0; countdownStart = Date()
        startProgressAnimation(); fireCountdownTimer()
    }

    private func resetCountdown(for text: String) {
        pendingText = text
        silenceTimer?.invalidate(); progressTimer?.invalidate()
        silenceProgress = 0; countdownStart = Date()
        startProgressAnimation(); fireCountdownTimer()
    }

    private func fireCountdownTimer() {
        silenceTimer = Timer.scheduledTimer(withTimeInterval: silenceDuration, repeats: false) { [weak self] _ in
            DispatchQueue.main.async { self?.commitPendingCommand() }
        }
    }

    private func startProgressAnimation() {
        progressTimer = Timer.scheduledTimer(withTimeInterval: 0.03, repeats: true) { [weak self] _ in
            guard let self, let start = self.countdownStart else { return }
            DispatchQueue.main.async {
                self.silenceProgress = min(Date().timeIntervalSince(start) / self.silenceDuration, 1.0)
            }
        }
    }

    private func commitPendingCommand() {
        guard !recognitionPaused, !isPlayingAudio else {
            clearTranscriptState(); return
        }
        cancelTimers(); silenceProgress = 1.0
        let text = pendingText.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { returnToIdle(); return }
        lastRecognized = text; transitionTo(.executing)
        // Thin client: voice path cũng đi thẳng WS + mode.
        sendTextToAI(text)
    }

    private func matchAndSendCommand(_ text: String) {
        guard let store = commandStore else {
            statusMessage = "⚠️ Chưa có danh sách lệnh"
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { self.returnToIdle() }
            return
        }
        let lower = text.lowercased()
        print("[DEBUG] matchAndSendCommand: \(text)")

        // Bước 1: Khớp chính xác với trigger đã đăng ký (ví dụ: bật/tắt PC qua Mac mini)
        if let matched = store.commands.first(where: {
            $0.isEnabled && lower.contains($0.trigger.lowercased())
        }) {
            statusMessage = "⚡ \(matched.name)"; haptic(.medium)
            networkManager.sendCommand(endpoint: matched.endpoint) { [weak self] success in
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.statusMessage = success ? "✓ \(matched.name)" : "✗ Lỗi: \(matched.name)"
                    self.hapticResult(success)
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { self.returnToIdle() }
                }
            }
            return
        }
        // Bước 2: Kiểm tra URL PentaKuru
        let pentaKuruURL = UserDefaults.standard.string(forKey: "penta_kuru_url") ?? ""
        print("[DEBUG] PentaKuru URL: \(pentaKuruURL)")
        if !pentaKuruURL.isEmpty {
            statusMessage = "🤖 Đang phân tích lệnh qua AI..."
            haptic(.light)
            networkManager.sendPentaKuruCommandViaAI(text: text) { [weak self] result in
                guard let self else { return }
                DispatchQueue.main.async {
                    if result.ok {
                        self.statusMessage = "✓ Lệnh đã thực thi"
                        self.aiResponseText = result.stdout.isEmpty ? "Thành công" : result.stdout
                        self.hapticResult(true)
                    } else {
                        self.statusMessage = "✗ Lỗi: \(result.stderr)"
                        self.aiResponseText = "Lỗi: \(result.stderr)"
                        self.hapticResult(false)
                    }
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { self.returnToIdle() }
                }
            }
            return
        }
        // Bước 3: Không có PentaKuru và không có trigger khớp
        statusMessage = "⚠️ Chưa học lệnh này, dạy cho em nhé"
        aiResponseText = "Không có lệnh phù hợp. Hãy thêm lệnh trong Settings hoặc cấu hình PentaKuru."
        hapticResult(false)
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) { self.returnToIdle() }
    }
    /// nếu không tìm được thì hiển thị gợi ý để người dùng biết cần thêm lệnh.
    private func executeOllamaCommand(
        _ result:      Penta​NetworkManager.OllamaCommandResult,
        originalText:  String,
        store:         CommandStore
    ) {
        let action = (result.action ?? "").lowercased()
        let target = (result.target ?? "").lowercased()
        let combined = "\(action) \(target)"

        // Re-map: tìm lệnh trong store có trigger khớp với action/target
        let remapped = store.commands.first(where: { cmd in
            guard cmd.isEnabled else { return false }
            let t = cmd.trigger.lowercased()
            return combined.contains(t) || t.contains(action) || target.contains(t)
        })

        if let matched = remapped {
            // Tìm được lệnh tương ứng → thực thi
            statusMessage = "⚡ \(matched.name) (AI)"; haptic(.medium)
            networkManager.sendCommand(endpoint: matched.endpoint) { [weak self] success in
                guard let self else { return }
                self.statusMessage = success ? "✓ \(matched.name)" : "✗ Lỗi: \(matched.name)"
                self.hapticResult(success)
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { self.returnToIdle() }
            }
        } else {
            // Ollama hiểu được nhưng không có lệnh tương ứng trong store
            let displayAction = result.action ?? "?"
            let displayTarget = result.target ?? "?"
            statusMessage = "💡 \"\(displayAction) \(displayTarget)\" — chưa được cài đặt"
            UINotificationFeedbackGenerator().notificationOccurred(.warning)
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) { self.returnToIdle() }
        }
    }

    // MARK: - State Machine

    private func transitionTo(_ state: VoiceState) {
        voiceState = state
        switch state {
        case .sleeping:   statusMessage = "Nói \"\(wakeWord)\" để kích hoạt"
        case .woken:      statusMessage = "Đang nghe lệnh..."
        case .listening:  statusMessage = "Lắng nghe liên tục..."
        case .countdown:  break
        case .executing:  statusMessage = "Đang gửi..."
        case .responding: statusMessage = "🤖 AI đang xử lý..."
        }
    }

    private func containsWakeWord(_ text: String) -> Bool {
        text.lowercased().contains(wakeWord.lowercased())
    }

    private func stripWakeWord(from text: String) -> String {
        let lower = text.lowercased(), wake = wakeWord.lowercased()
        guard let range = lower.range(of: wake) else {
            return text.trimmingCharacters(in: .whitespaces)
        }
        var result = text; result.removeSubrange(range)
        return result.trimmingCharacters(in: .whitespaces)
    }

    private func cancelTimers() {
        silenceTimer?.invalidate();  silenceTimer  = nil
        progressTimer?.invalidate(); progressTimer = nil
        countdownStart = nil
    }

    private func haptic(_ style: UIImpactFeedbackGenerator.FeedbackStyle) {
        UIImpactFeedbackGenerator(style: style).impactOccurred()
    }
    private func hapticResult(_ success: Bool) {
        UINotificationFeedbackGenerator().notificationOccurred(success ? .success : .error)
    }
}
