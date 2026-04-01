// FloatingPentagonWidget.swift — v3.1
// Fix:
//   • Bấm pentagon chỉ mở panel, KHÔNG tự hiện bàn phím
//   • Bàn phím chỉ xuất hiện khi bấm nút ⌨ bên trong panel
//   • Panel tự trượt lên khi bàn phím mở, không bị che
//   • Mac: pip install websockets "uvicorn[standard]"

import SwiftUI
import UIKit
import Combine

// MARK: - FloatingPentagonWidget

struct FloatingPentagonWidget: View {

    @ObservedObject var voiceEngine: VoiceEngine

    // ── Vị trí ──────────────────────────────────────────────────────────
    @State private var position   : CGPoint = CGPoint(
        x: UIScreen.main.bounds.width - 56,
        y: UIScreen.main.bounds.height * 0.72
    )
    @State private var dragOffset : CGSize = .zero
    @State private var isDragging : Bool   = false

    // ── Panel ────────────────────────────────────────────────────────────
    @State private var showPanel  : Bool   = false

    // ── Widget glow / opacity ────────────────────────────────────────────
    @State private var opacity    : Double  = 0.28
    @State private var pulseScale : CGFloat = 1.0
    @State private var innerGlow  : Double  = 0.0
    @State private var rotAngle   : Double  = 0.0

    // ── AI glow ──────────────────────────────────────────────────────────
    @State private var aiGlowRing : Double  = 0.0
    @State private var aiGlowPulse: CGFloat = 1.0
    @State private var aiNewMsg   : Bool    = false

    // ── ⭐ Streaming text display ─────────────────────────────────────────
    // Thay vì hiện toàn bộ text 1 lần, reveal từng câu để sync với audio
    @State private var displayedText     : String   = ""   // text đang hiển thị (tăng dần)
    @State private var pendingSentences  : [String] = []   // hàng đợi câu chờ reveal
    @State private var sentenceTimer     : Timer?          // timer reveal câu tiếp theo
    @State private var isReceivingText   : Bool     = false // đang nhận text từ AI
    @State private var scrollProxy       : ScrollViewProxy? = nil

    // ── Keyboard ─────────────────────────────────────────────────────────
    @State private var inputText     : String  = ""
    @State private var isSending     : Bool    = false
    @State private var keyboardHeight: CGFloat = 0
    @FocusState private var kbFocused: Bool

    // ── Timers ───────────────────────────────────────────────────────────
    @State private var fadeTimer  : Timer?
    @State private var panelTimer : Timer?
    private let fadeDuration  : TimeInterval = 3.0
    private let panelDuration : TimeInterval = 12.0

    // ── Sizes ────────────────────────────────────────────────────────────
    private let widgetSize : CGFloat = 52
    private let panelWidth : CGFloat = 264

    // MARK: - Body

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .topLeading) {

                if showPanel {
                    chatPanel(in: geo)
                        .transition(.asymmetric(
                            insertion: .scale(scale: 0.78, anchor: panelAnchor(geo))
                                .combined(with: .opacity),
                            removal:   .scale(scale: 0.88, anchor: panelAnchor(geo))
                                .combined(with: .opacity)
                        ))
                }

                pentagonWidget
                    .position(widgetCenter)
                    .opacity(opacity)
                    .gesture(dragGesture(in: geo))
                    .onTapGesture { handleTap() }
            }
            .animation(.spring(response: 0.32, dampingFraction: 0.72), value: showPanel)
            .animation(.easeInOut(duration: 0.35), value: opacity)
            .animation(.easeInOut(duration: 0.28), value: keyboardHeight)
            .onAppear { startFadeTimer() }
            // ── Keyboard notifications ────────────────────────────────────
            .onReceive(
                NotificationCenter.default.publisher(for: UIResponder.keyboardWillShowNotification)
            ) { notif in
                if let frame = notif.userInfo?[UIResponder.keyboardFrameEndUserInfoKey] as? CGRect {
                    keyboardHeight = frame.height
                    panelTimer?.invalidate()   // giữ panel mở khi đang nhập
                }
            }
            .onReceive(
                NotificationCenter.default.publisher(for: UIResponder.keyboardWillHideNotification)
            ) { _ in
                keyboardHeight = 0
                if showPanel { startPanelTimer() }
            }
            // ── AI response ───────────────────────────────────────────────
            // Khi nhận text từ AI → reveal từng câu với hiệu ứng streaming
            .onChange(of: voiceEngine.aiResponseText) { _, newText in
                guard !newText.isEmpty else { return }
                triggerAIGlow()
                revealAndShowPanel()
                startSentenceStream(newText)
            }
            // Khi bắt đầu gửi câu hỏi mới → xóa text cũ, hiện "đang xử lý..."
            .onChange(of: voiceEngine.voiceState) { _, state in
                if state == .executing || state == .responding {
                    if voiceEngine.aiResponseText.isEmpty {
                        sentenceTimer?.invalidate()
                        pendingSentences = []
                        displayedText    = ""
                        isReceivingText  = false
                    }
                }
            }
            .onChange(of: voiceEngine.isPlayingAudio) { _, playing in
                playing ? boostPlayingGlow() : dimPlayingGlow()
            }
        }
    }

    // MARK: - Pentagon Widget

    var pentagonWidget: some View {
        ZStack {
            // AI Glow rings
            if aiGlowRing > 0 {
                ForEach(0..<3) { i in
                    PentagonShape()
                        .stroke(
                            aiGlowColor.opacity(aiGlowRing * (0.60 - Double(i) * 0.15)),
                            lineWidth: CGFloat(3 - i)
                        )
                        .frame(
                            width:  widgetSize + 18 + CGFloat(i * 12),
                            height: widgetSize + 18 + CGFloat(i * 12)
                        )
                        .scaleEffect(aiGlowPulse)
                        .rotationEffect(.degrees(rotAngle * 1.2))
                        .blur(radius: CGFloat(i + 1))
                }
            }

            // Outer glow
            PentagonShape()
                .stroke(Color(hex: "6C63FF").opacity(innerGlow * 0.5), lineWidth: 1.5)
                .frame(width: widgetSize + 14, height: widgetSize + 14)
                .rotationEffect(.degrees(rotAngle))
                .scaleEffect(pulseScale)
                .blur(radius: 2)

            // Fill
            PentagonShape()
                .fill(
                    RadialGradient(
                        colors: [widgetFillColor.opacity(0.88), Color(hex: "3A1F8F").opacity(0.95)],
                        center: .center, startRadius: 4, endRadius: widgetSize * 0.6
                    )
                )
                .frame(width: widgetSize, height: widgetSize)
                .rotationEffect(.degrees(rotAngle))
                .shadow(
                    color: widgetFillColor.opacity(innerGlow * 0.85 + aiGlowRing * 0.5),
                    radius: 10 + 6 * aiGlowRing
                )

            // Border
            PentagonShape()
                .stroke(
                    LinearGradient(
                        colors: [Color(hex: "A78BFA").opacity(0.9), Color(hex: "6C63FF").opacity(0.4)],
                        startPoint: .top, endPoint: .bottom
                    ),
                    lineWidth: 1.2
                )
                .frame(width: widgetSize, height: widgetSize)
                .rotationEffect(.degrees(rotAngle))

            // Icon
            centerIcon.scaleEffect(pulseScale * 0.94)

            // Unread dot
            if aiNewMsg && !showPanel {
                Circle()
                    .fill(Color(hex: "00D4AA"))
                    .frame(width: 8, height: 8)
                    .overlay(Circle().stroke(Color(hex: "0A0A0F"), lineWidth: 1.5))
                    .offset(x: widgetSize * 0.3, y: -widgetSize * 0.3)
                    .scaleEffect(aiGlowPulse)
            }
        }
        .frame(width: widgetSize + 30, height: widgetSize + 30)
    }

    @ViewBuilder
    var centerIcon: some View {
        if voiceEngine.isPlayingAudio {
            Image(systemName: "speaker.wave.2.fill")
                .font(.system(size: 16, weight: .light))
                .foregroundColor(Color(hex: "00D4AA"))
                .symbolEffect(.variableColor.iterative)
        } else if voiceEngine.voiceState == .responding {
            Image(systemName: "brain")
                .font(.system(size: 15, weight: .light))
                .foregroundColor(Color(hex: "00D4AA"))
        } else {
            Image(systemName: "p.circle.fill")
                .font(.system(size: 17, weight: .ultraLight))
                .foregroundColor(Color.white.opacity(0.85))
        }
    }

    var widgetFillColor: Color {
        switch voiceEngine.voiceState {
        case .responding: return Color(hex: "00D4AA")
        case .executing:  return Color(hex: "C084FC")
        default:          return Color(hex: "6C63FF")
        }
    }

    var aiGlowColor: Color {
        voiceEngine.isPlayingAudio ? Color(hex: "00D4AA") : Color(hex: "A78BFA")
    }

    // MARK: - Chat Panel

    func chatPanel(in geo: GeometryProxy) -> some View {
        let center = widgetCenter
        let onLeft = center.x > geo.size.width / 2

        let panelX: CGFloat = onLeft
            ? center.x - panelWidth - 14
            : center.x + widgetSize / 2 + 10

        // ⭐ Đẩy panel lên trên bàn phím khi bàn phím xuất hiện
        let maxY   = geo.size.height - keyboardHeight - 220 - 12
        let rawY   = center.y - widgetSize / 2
        let panelY = max(60, min(rawY, maxY))

        return VStack(spacing: 0) {
            panelHeader
            Divider().opacity(0.15)
            responseTextArea
            Divider().opacity(0.15)
            inputRow   // ← bàn phím chỉ mở khi bấm nút ⌨ trong này
        }
        .frame(width: panelWidth)
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(Color(hex: "0D0B1A").opacity(0.97))
                .overlay(
                    RoundedRectangle(cornerRadius: 16)
                        .stroke(
                            LinearGradient(
                                colors: [
                                    Color(hex: "6C63FF").opacity(0.55),
                                    Color(hex: "3A1F8F").opacity(0.22),
                                ],
                                startPoint: .topLeading,
                                endPoint:   .bottomTrailing
                            ),
                            lineWidth: 1
                        )
                )
        )
        .shadow(color: Color(hex: "6C63FF").opacity(0.18), radius: 18, y: 4)
        .overlay(alignment: onLeft ? .trailing : .leading) {
            Triangle()
                .fill(Color(hex: "6C63FF").opacity(0.32))
                .frame(width: 8, height: 8)
                .rotationEffect(.degrees(onLeft ? -90 : 90))
                .offset(x: onLeft ? 4 : -4, y: 0)
        }
        .position(x: panelX + panelWidth / 2, y: panelY + 100)
    }

    // ── Header ────────────────────────────────────────────────────────────

    var panelHeader: some View {
        HStack(spacing: 6) {
            PentagonShape()
                .fill(Color(hex: "6C63FF").opacity(0.8))
                .frame(width: 11, height: 11)

            Text("PENTA AI")
                .font(.system(size: 9, weight: .semibold, design: .monospaced))
                .foregroundColor(Color(hex: "A78BFA"))
                .tracking(1.5)

            // ⭐ Badge chế độ (Chat / Device) có thể bấm để chuyển
            HStack(spacing: 4) {
                Image(systemName: voiceEngine.commandMode == .chat ? "bubble.left.fill" : "bolt.fill")
                    .font(.system(size: 8))
                    .foregroundColor(voiceEngine.commandMode == .chat ? Color(hex: "00D4AA") : Color(hex: "C084FC"))
                Text(voiceEngine.commandMode == .chat ? "CHAT" : "DEVICE")
                    .font(.system(size: 7, weight: .medium, design: .monospaced))
                    .foregroundColor(voiceEngine.commandMode == .chat ? Color(hex: "00D4AA") : Color(hex: "C084FC"))
            }
            .padding(.horizontal, 4)
            .padding(.vertical, 2)
            .background(
                Capsule()
                    .fill(voiceEngine.commandMode == .chat ? Color(hex: "00D4AA").opacity(0.15) : Color(hex: "C084FC").opacity(0.15))
                    .overlay(Capsule().stroke(voiceEngine.commandMode == .chat ? Color(hex: "00D4AA").opacity(0.4) : Color(hex: "C084FC").opacity(0.4), lineWidth: 0.5))
            )
            .onTapGesture {
                withAnimation(.easeInOut(duration: 0.2)) {
                    voiceEngine.commandMode = voiceEngine.commandMode == .chat ? .device : .chat
                }
            }

            Spacer()

            // Phần còn lại giữ nguyên: audio bars, latency, nút đóng...
            if voiceEngine.isPlayingAudio {
                HStack(spacing: 2) {
                    ForEach(0..<3) { i in
                        RoundedRectangle(cornerRadius: 1)
                            .fill(Color(hex: "00D4AA"))
                            .frame(width: 2, height: CGFloat([5, 9, 6][i]))
                            .animation(
                                .easeInOut(duration: 0.4)
                                    .repeatForever(autoreverses: true)
                                    .delay(Double(i) * 0.12),
                                value: voiceEngine.isPlayingAudio
                            )
                    }
                }
                .frame(height: 12)
            }

            if voiceEngine.lastLatencyMs > 0 {
                Text("\(voiceEngine.lastLatencyMs)ms")
                    .font(.system(size: 8, design: .monospaced))
                    .foregroundColor(Color(hex: "6C63FF").opacity(0.6))
            }

            Button {
                kbFocused = false
                withAnimation { showPanel = false }
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 8, weight: .medium))
                    .foregroundColor(Color.white.opacity(0.3))
                    .frame(width: 16, height: 16)
                    .background(Circle().fill(Color.white.opacity(0.06)))
            }
        }
        .padding(.horizontal, 12)
        .padding(.top, 10)
        .padding(.bottom, 6)
    }

    // ── ⭐ Response text — streaming reveal từng câu ──────────────────────

    var responseTextArea: some View {
        ScrollViewReader { proxy in
            ScrollView(.vertical, showsIndicators: false) {
                VStack(alignment: .leading, spacing: 0) {

                    // Text hiển thị dần (từng câu)
                    if displayedText.isEmpty && !isReceivingText {
                        // Trạng thái chờ
                        HStack(spacing: 6) {
                            if voiceEngine.voiceState == .responding ||
                               voiceEngine.voiceState == .executing {
                                // 3 chấm nhấp nháy
                                HStack(spacing: 3) {
                                    ForEach(0..<3) { i in
                                        Circle()
                                            .fill(Color(hex: "6C63FF").opacity(0.6))
                                            .frame(width: 4, height: 4)
                                            .scaleEffect(isReceivingText ? 1.0 : 0.6)
                                            .animation(
                                                .easeInOut(duration: 0.5)
                                                    .repeatForever(autoreverses: true)
                                                    .delay(Double(i) * 0.16),
                                                value: voiceEngine.voiceState
                                            )
                                    }
                                }
                                Text("đang xử lý")
                                    .font(.system(size: 11, design: .monospaced))
                                    .foregroundColor(Color(hex: "6C63FF").opacity(0.5))
                            } else {
                                Text("Đang chờ phản hồi…")
                                    .font(.system(size: 13, design: .monospaced))
                                    .foregroundColor(Color.white.opacity(0.25))
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 10)
                    } else {
                        // Text stream dần
                        Text(displayedText)
                            .font(.system(size: 13, design: .monospaced))
                            .foregroundColor(Color.white.opacity(0.88))
                            .lineSpacing(4)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 12)
                            .padding(.top, 10)
                            .padding(.bottom, isReceivingText ? 4 : 10)
                            // Fade-in mỗi khi text thêm vào
                            .animation(.easeIn(duration: 0.2), value: displayedText)

                        // ⭐ Cursor nhấp nháy khi đang stream
                        if isReceivingText {
                            HStack {
                                BlinkingCursor()
                                Spacer()
                            }
                            .padding(.horizontal, 12)
                            .padding(.bottom, 8)
                        }
                    }

                    // Anchor để scroll xuống cuối
                    Color.clear.frame(height: 1).id("bottom")
                }
            }
            .frame(maxHeight: 120)
            .onChange(of: displayedText) { _, _ in
                // Auto-scroll xuống cuối mỗi khi text thêm vào
                withAnimation(.easeOut(duration: 0.15)) {
                    proxy.scrollTo("bottom", anchor: .bottom)
                }
            }
        }
    }

    // ── ⭐ Input Row ───────────────────────────────────────────────────────
    // Bàn phím KHÔNG tự focus — chỉ focus khi bấm nút ⌨

    var inputRow: some View {
        HStack(spacing: 8) {
            TextField("Nhập tin nhắn…", text: $inputText, axis: .vertical)
                .font(.system(size: 13))
                .foregroundColor(.white)
                .tint(Color(hex: "6C63FF"))
                .lineLimit(1...3)
                .padding(.horizontal, 10)
                .padding(.vertical, 8)
                .background(
                    RoundedRectangle(cornerRadius: 10)
                        .fill(Color.white.opacity(0.05))
                        .overlay(
                            RoundedRectangle(cornerRadius: 10)
                                .stroke(
                                    kbFocused
                                        ? Color(hex: "6C63FF").opacity(0.6)
                                        : Color.white.opacity(0.1),
                                    lineWidth: 1
                                )
                        )
                )
                .focused($kbFocused)   // controlled externally
                .submitLabel(.send)
                .onSubmit { handleSend() }

            // Nút đa năng: ⌨ mở | ⬇ đóng | ↑ gửi
            Button(action: handleKeyboardButton) {
                ZStack {
                    if isSending {
                        ProgressView().scaleEffect(0.7).tint(Color(hex: "6C63FF"))
                    } else if !inputText.isEmpty {
                        Image(systemName: "arrow.up")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundColor(Color(hex: "6C63FF"))
                    } else if kbFocused {
                        Image(systemName: "keyboard.chevron.compact.down")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundColor(Color.white.opacity(0.4))
                    } else {
                        Image(systemName: "keyboard")
                            .font(.system(size: 12, weight: .light))
                            .foregroundColor(Color(hex: "6C63FF").opacity(0.8))
                    }
                }
                .frame(width: 32, height: 32)
                .background(
                    Circle()
                        .fill(buttonBgColor)
                        .overlay(Circle().stroke(buttonBorderColor, lineWidth: 1))
                )
            }
            .disabled(isSending)
            .animation(.easeInOut(duration: 0.15), value: kbFocused)
            .animation(.easeInOut(duration: 0.15), value: inputText.isEmpty)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
    }

    var buttonBgColor: Color {
        if !inputText.isEmpty { return Color(hex: "6C63FF").opacity(0.18) }
        if kbFocused          { return Color.white.opacity(0.05) }
        return Color(hex: "6C63FF").opacity(0.10)
    }
    var buttonBorderColor: Color {
        if !inputText.isEmpty { return Color(hex: "6C63FF").opacity(0.5) }
        if kbFocused          { return Color.white.opacity(0.1) }
        return Color(hex: "6C63FF").opacity(0.35)
    }

    // MARK: - ⭐ Keyboard Button

    func handleKeyboardButton() {
        if !inputText.isEmpty {
            handleSend()
        } else if kbFocused {
            kbFocused = false          // đóng bàn phím
        } else {
            kbFocused = true           // mở bàn phím
            panelTimer?.invalidate()   // không auto-close khi đang nhập
        }
    }

    // MARK: - Send

    func handleSend() {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { kbFocused = false; return }
        inputText = ""
        isSending = true
        kbFocused = false
        voiceEngine.sendTextFromKeyboard(text)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { isSending = false }
        startPanelTimer()
    }

    // MARK: - Drag

    func dragGesture(in geo: GeometryProxy) -> some Gesture {
        DragGesture(minimumDistance: 4)
            .onChanged { val in
                isDragging = true
                kbFocused  = false
                revealWidget()
                let newX = position.x + val.translation.width  - dragOffset.width
                let newY = position.y + val.translation.height - dragOffset.height
                position = CGPoint(
                    x: max(widgetSize / 2, min(geo.size.width  - widgetSize / 2, newX)),
                    y: max(widgetSize / 2, min(geo.size.height - widgetSize / 2, newY))
                )
                dragOffset = val.translation
            }
            .onEnded { _ in
                isDragging = false
                dragOffset = .zero
                withAnimation(.spring(response: 0.4, dampingFraction: 0.75)) {
                    let midX = geo.size.width / 2
                    position.x = position.x < midX
                        ? widgetSize / 2 + 10
                        : geo.size.width - widgetSize / 2 - 10
                }
                startFadeTimer()
            }
    }

    // MARK: - ⭐ Tap — CHỈ mở/đóng panel, không touch bàn phím

    func handleTap() {
        guard !isDragging else { return }
        revealWidget()
        aiNewMsg = false
        withAnimation(.spring(response: 0.3, dampingFraction: 0.68)) {
            if showPanel {
                kbFocused = false
                showPanel = false
            } else {
                showPanel = true
                startPanelTimer()
                // ← KHÔNG gọi kbFocused = true ở đây
            }
        }
    }

    // MARK: - ⭐ Sentence Streaming

    /// Tách text thành câu, đưa vào hàng đợi, reveal từng câu
    func startSentenceStream(_ fullText: String) {
        sentenceTimer?.invalidate()
        displayedText    = ""
        pendingSentences = splitSentences(fullText)
        isReceivingText  = true
        revealNextSentence()
    }

    func revealNextSentence() {
        guard !pendingSentences.isEmpty else {
            // Hết câu → tắt cursor sau 0.8s
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
                withAnimation(.easeOut(duration: 0.3)) { isReceivingText = false }
            }
            return
        }

        let sentence = pendingSentences.removeFirst()

        withAnimation(.easeIn(duration: 0.18)) {
            displayedText = displayedText.isEmpty
                ? sentence
                : displayedText + " " + sentence
        }

        // Delay trước câu kế tiếp — ngắn để cảm giác nhanh, dài hơn nếu câu dài
        let delay: TimeInterval = pendingSentences.isEmpty ? 0 : min(0.35, Double(sentence.count) * 0.008 + 0.18)
        sentenceTimer = Timer.scheduledTimer(withTimeInterval: delay, repeats: false) { _ in
            revealNextSentence()
        }
    }

    /// Tách text thành câu (tiếng Việt + tiếng Anh)
    func splitSentences(_ text: String) -> [String] {
        // Tách theo dấu câu kết thúc
        var sentences: [String] = []
        var current = ""
        for char in text {
            current.append(char)
            if [".", "!", "?", "。", "！", "？"].contains(char) {
                let trimmed = current.trimmingCharacters(in: .whitespaces)
                if !trimmed.isEmpty { sentences.append(trimmed) }
                current = ""
            }
        }
        // Phần còn lại không có dấu câu
        let remainder = current.trimmingCharacters(in: .whitespaces)
        if !remainder.isEmpty { sentences.append(remainder) }

        // Gộp câu quá ngắn (< 8 ký tự) vào câu kế tiếp
        var merged: [String] = []
        var buf = ""
        for s in sentences {
            buf = buf.isEmpty ? s : buf + " " + s
            if buf.count >= 12 { merged.append(buf); buf = "" }
        }
        if !buf.isEmpty {
            if merged.isEmpty { merged.append(buf) }
            else { merged[merged.count - 1] += " " + buf }
        }
        return merged.isEmpty ? [text] : merged
    }

    // MARK: - AI Glow

    func triggerAIGlow() {
        aiNewMsg = true
        withAnimation(.easeOut(duration: 0.25)) { aiGlowRing = 1.0 }
        withAnimation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true)) { aiGlowPulse = 1.12 }
        DispatchQueue.main.asyncAfter(deadline: .now() + 6) {
            guard !showPanel else { return }
            withAnimation(.easeInOut(duration: 1.2)) { aiGlowRing = 0.0; aiGlowPulse = 1.0 }
        }
    }

    func boostPlayingGlow() {
        withAnimation(.easeInOut(duration: 0.3)) { aiGlowRing = 1.0 }
        withAnimation(.easeInOut(duration: 0.5).repeatForever(autoreverses: true)) { aiGlowPulse = 1.15 }
    }

    func dimPlayingGlow() {
        withAnimation(.easeInOut(duration: 1.5)) { aiGlowRing = 0.0; aiGlowPulse = 1.0 }
    }

    // MARK: - Visibility

    func revealWidget() {
        fadeTimer?.invalidate()
        withAnimation(.easeOut(duration: 0.22)) { opacity = 1.0; innerGlow = 1.0 }
        withAnimation(.linear(duration: 8).repeatForever(autoreverses: false)) { rotAngle = 360 }
        withAnimation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true)) { pulseScale = 1.08 }
        startFadeTimer()
    }

    func revealAndShowPanel() {
        revealWidget()
        withAnimation(.spring(response: 0.32, dampingFraction: 0.72)) { showPanel = true }
        startPanelTimer()
    }

    func startFadeTimer() {
        fadeTimer?.invalidate()
        fadeTimer = Timer.scheduledTimer(withTimeInterval: fadeDuration, repeats: false) { _ in
            guard !isDragging && !showPanel else { return }
            withAnimation(.easeInOut(duration: 0.8)) { opacity = 0.22; innerGlow = 0.0; pulseScale = 1.0 }
            withAnimation(.easeOut(duration: 0.5)) { rotAngle = 0 }
        }
    }

    func startPanelTimer() {
        panelTimer?.invalidate()
        panelTimer = Timer.scheduledTimer(withTimeInterval: panelDuration, repeats: false) { _ in
            guard !kbFocused else { return }
            withAnimation(.easeOut(duration: 0.35)) { showPanel = false }
            startFadeTimer()
        }
    }

    var widgetCenter: CGPoint { position }

    func panelAnchor(_ geo: GeometryProxy) -> UnitPoint {
        position.x > geo.size.width / 2 ? .trailing : .leading
    }
}

// MARK: - BlinkingCursor

private struct BlinkingCursor: View {
    @State private var visible = true
    var body: some View {
        Rectangle()
            .fill(Color(hex: "6C63FF").opacity(0.8))
            .frame(width: 2, height: 13)
            .opacity(visible ? 1 : 0)
            .onAppear {
                withAnimation(.easeInOut(duration: 0.5).repeatForever(autoreverses: true)) {
                    visible = false
                }
            }
    }
}
