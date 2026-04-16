// ContentView.swift — v3.0
// Thêm FloatingPentagonWidget nổi lên trên toàn bộ giao diện

import SwiftUI
import AVFoundation
import Speech
import Combine

// MARK: - Purple Palette
private extension Color {
    static let pSleeping   = Color(hex: "1C1635")
    static let pWoken      = Color(hex: "4338CA")
    static let pListening  = Color(hex: "6C63FF")
    static let pCountdown  = Color(hex: "9333EA")
    static let pExecuting  = Color(hex: "C084FC")
    static let pResponding = Color(hex: "00D4AA")
}

struct ContentView: View {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var voiceEngine  = VoiceEngine()
    @StateObject private var commandStore = CommandStore()
    @State private var showSettings = false
    @State private var showCommands = false

    // Animations
    @State private var rotationAngle  : Double  = 0
    @State private var pulseScale     : CGFloat = 1.0
    @State private var glowOpacity    : Double  = 0.0
    @State private var orbitRotation  : Double  = 0
    @State private var wokenBreathe   : CGFloat = 1.0
    @State private var executingPulse : CGFloat = 1.0
    @State private var respondingPulse: CGFloat = 1.0

    var body: some View {
        ZStack {
            // ── Màn hình chính ───────────────────────────────────────────
            mainScreen

            // ── Floating Pentagon Widget — nổi trên tất cả ──────────────
            FloatingPentagonWidget(voiceEngine: voiceEngine)
                .ignoresSafeArea()
                .allowsHitTesting(true)
        }
        .sheet(isPresented: $showSettings) {
            SettingsView(voiceEngine: voiceEngine, commandStore: commandStore)
        }
        .sheet(isPresented: $showCommands) {
            CommandListView(commandStore: commandStore)
        }
    }

    // ─────────────────────────────────────────────────────────
    // MARK: - Main Screen
    // ─────────────────────────────────────────────────────────

    var mainScreen: some View {
        ZStack {
            Color(hex: "0A0A0F").ignoresSafeArea()
            GridBackgroundView().opacity(0.12)

            VStack(spacing: 0) {
                topBar
                Spacer()
                pentagonMicView
                Spacer()
                modeToggle
                bottomPanel
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 16)
        }
        .onAppear {
            voiceEngine.requestPermissions()
            voiceEngine.setCommandStore(commandStore)
            startOrbitAnimation()
        }
        .onChange(of: voiceEngine.voiceState) { newState in
            syncAnimations(to: newState)
        }
        .onChange(of: scenePhase) { phase in
            switch phase {
            case .active:
                voiceEngine.appDidBecomeActive()
            case .background, .inactive:
                voiceEngine.appDidEnterBackground()
            @unknown default:
                break
            }
        }
    }

    // ─────────────────────────────────────────────────────────
    // MARK: - Top Bar
    // ─────────────────────────────────────────────────────────

    var topBar: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("PENTA")
                    .font(.custom("Courier New", size: 11)).fontWeight(.bold)
                    .foregroundColor(.pListening).tracking(4)
                Text("COMMAND")
                    .font(.custom("Courier New", size: 11)).fontWeight(.bold)
                    .foregroundColor(Color.white.opacity(0.3)).tracking(4)
            }
            Spacer()

            if voiceEngine.lastLatencyMs > 0 {
                Text("\(voiceEngine.lastLatencyMs)ms")
                    .font(.custom("Courier New", size: 9))
                    .foregroundColor(Color(hex: "00D4AA").opacity(0.7))
                    .padding(.horizontal, 7).padding(.vertical, 4)
                    .background(Capsule().fill(Color(hex: "00D4AA").opacity(0.08))
                        .overlay(Capsule().stroke(Color(hex: "00D4AA").opacity(0.2), lineWidth: 1)))
                    .padding(.trailing, 6)
            }

            connectionStatusBadge

            Button(action: { showSettings = true }) {
                Image(systemName: "slider.horizontal.3")
                    .font(.system(size: 18, weight: .light))
                    .foregroundColor(Color.white.opacity(0.5))
                    .frame(width: 36, height: 36)
                    .background(
                        RoundedRectangle(cornerRadius: 10)
                            .fill(Color.white.opacity(0.04))
                            .overlay(RoundedRectangle(cornerRadius: 10)
                                .stroke(Color.white.opacity(0.08), lineWidth: 1))
                    )
            }
        }
    }

    var connectionStatusBadge: some View {
        HStack(spacing: 5) {
            Circle()
                .fill(voiceEngine.isConnected ? Color(hex: "A78BFA") : Color(hex: "FF4466"))
                .frame(width: 5, height: 5)
                .shadow(color: voiceEngine.isConnected ? .pExecuting : Color(hex: "FF4466"),
                        radius: voiceEngine.isConnected ? 4 : 2)
            Text(voiceEngine.isConnected ? "ONLINE" : "OFFLINE")
                .font(.custom("Courier New", size: 9))
                .foregroundColor(Color.white.opacity(0.35)).tracking(2)
        }
        .padding(.horizontal, 10).padding(.vertical, 6)
        .background(Capsule().fill(Color.white.opacity(0.03))
            .overlay(Capsule().stroke(Color.white.opacity(0.07), lineWidth: 1)))
        .padding(.trailing, 8)
    }

    // ─────────────────────────────────────────────────────────
    // MARK: - Pentagon Mic
    // ─────────────────────────────────────────────────────────

    var pentagonMicView: some View {
        ZStack {
            ForEach(0..<3) { i in
                PentagonShape()
                    .stroke(stateColor.opacity(glowOpacity * Double(3 - i) * 0.18), lineWidth: 1)
                    .frame(width: 260 + CGFloat(i * 28), height: 260 + CGFloat(i * 28))
                    .rotationEffect(.degrees(rotationAngle * 0.3 + Double(i) * 6))
            }
            ZStack {
                Circle().stroke(Color.clear, lineWidth: 0).frame(width: 230, height: 230)
                Triangle()
                    .fill(stateColor.opacity(voiceEngine.voiceState == .sleeping ? 0.12 : 0.55))
                    .frame(width: 7, height: 6).offset(y: -115)
                    .rotationEffect(.degrees(orbitRotation))
                    .shadow(color: stateColor.opacity(0.8), radius: 3)
            }
            PentagonFromTriangles(voiceState: voiceEngine.voiceState, rotation: rotationAngle)
                .frame(width: 220, height: 220)
            PentagonShape()
                .stroke(
                    LinearGradient(gradient: Gradient(colors: [stateColor, stateBorderColor, stateColor]),
                                   startPoint: .topLeading, endPoint: .bottomTrailing),
                    lineWidth: voiceEngine.voiceState == .sleeping ? 0.8 : 1.8
                )
                .frame(width: 220, height: 220)
                .rotationEffect(.degrees(rotationAngle))
                .shadow(color: stateColor.opacity(0.4), radius: voiceEngine.voiceState == .sleeping ? 2 : 10)
            PentagonShape()
                .fill(RadialGradient(gradient: Gradient(colors: [Color(hex: "12101E"), Color(hex: "080810")]),
                                     center: .center, startRadius: 8, endRadius: 110))
                .frame(width: 212, height: 212).rotationEffect(.degrees(rotationAngle))
            micButton
        }
    }

    var micButton: some View {
        Button(action: toggleListening) {
            ZStack {
                if voiceEngine.voiceState != .sleeping && voiceEngine.isListening {
                    ForEach(0..<2) { i in
                        Circle()
                            .stroke(stateColor.opacity(0.22 - Double(i) * 0.07), lineWidth: 1)
                            .frame(width: 82 + CGFloat(i * 22), height: 82 + CGFloat(i * 22))
                            .scaleEffect(pulseScale)
                    }
                }
                if voiceEngine.voiceState == .countdown {
                    Circle()
                        .trim(from: 0, to: voiceEngine.silenceProgress)
                        .stroke(stateColor, style: StrokeStyle(lineWidth: 3, lineCap: .round))
                        .frame(width: 88, height: 88).rotationEffect(.degrees(-90))
                        .animation(.linear(duration: 0.03), value: voiceEngine.silenceProgress)
                }
                Circle().fill(micGradient).frame(width: 72, height: 72)
                    .shadow(color: stateColor.opacity(0.45), radius: voiceEngine.isListening ? 14 : 5)
                    .scaleEffect(voiceEngine.voiceState == .woken      ? wokenBreathe    :
                                 voiceEngine.voiceState == .executing  ? executingPulse  :
                                 voiceEngine.voiceState == .responding ? respondingPulse : 1.0)
                Image(systemName: micIconName)
                    .font(.system(size: 24, weight: .light))
                    .foregroundColor(.white.opacity(voiceEngine.voiceState == .sleeping ? 0.4 : 0.95))
                    .animation(.easeInOut(duration: 0.2), value: voiceEngine.voiceState)
            }
        }
        .buttonStyle(PlainButtonStyle())
    }

    // ─────────────────────────────────────────────────────────
    // MARK: - Mode Toggle
    // ─────────────────────────────────────────────────────────

    var modeToggle: some View {
        HStack(spacing: 8) {
            ForEach(CommandMode.allCases, id: \.self) { mode in
                Button(action: { voiceEngine.commandMode = mode }) {
                    HStack(spacing: 6) {
                        Image(systemName: mode.icon).font(.system(size: 12))
                        Text(mode.label).font(.custom("Courier New", size: 10)).tracking(1)
                    }
                    .foregroundColor(
                        voiceEngine.commandMode == mode
                            ? (mode == .chat ? Color(hex: "00D4AA") : .pListening)
                            : Color.white.opacity(0.3)
                    )
                    .padding(.horizontal, 14).padding(.vertical, 8)
                    .background(
                        Capsule()
                            .fill(voiceEngine.commandMode == mode
                                  ? (mode == .chat ? Color(hex: "00D4AA").opacity(0.12) : Color.pListening.opacity(0.12))
                                  : Color.white.opacity(0.03))
                            .overlay(Capsule().stroke(
                                voiceEngine.commandMode == mode
                                    ? (mode == .chat ? Color(hex: "00D4AA").opacity(0.4) : Color.pListening.opacity(0.4))
                                    : Color.white.opacity(0.07),
                                lineWidth: 1))
                    )
                }
            }
        }
        .padding(.bottom, 8)
    }

    // ─────────────────────────────────────────────────────────
    // MARK: - Bottom Panel
    // ─────────────────────────────────────────────────────────

    var bottomPanel: some View {
        VStack(spacing: 12) {
            if !voiceEngine.currentTranscript.isEmpty {
                Text(voiceEngine.currentTranscript)
                    .font(.custom("Courier New", size: 13))
                    .foregroundColor(.white.opacity(0.75))
                    .multilineTextAlignment(.center).lineLimit(2)
                    .padding(.horizontal, 8)
            }
            Text(voiceEngine.statusMessage)
                .font(.custom("Courier New", size: 11))
                .foregroundColor(stateColor.opacity(0.8)).tracking(1)
                .multilineTextAlignment(.center)
                .animation(.easeInOut(duration: 0.2), value: voiceEngine.statusMessage)
            if voiceEngine.commandMode == .device {
                Button(action: { showCommands = true }) {
                    HStack(spacing: 6) {
                        Image(systemName: "list.bullet").font(.system(size: 12))
                        Text("DANH SÁCH LỆNH").font(.custom("Courier New", size: 10)).tracking(2)
                    }
                    .foregroundColor(Color.white.opacity(0.3))
                    .padding(.horizontal, 14).padding(.vertical, 8)
                    .background(Capsule().fill(Color.white.opacity(0.03))
                        .overlay(Capsule().stroke(Color.white.opacity(0.06), lineWidth: 1)))
                }
            }
        }
        .padding(.bottom, 8)
    }

    // ─────────────────────────────────────────────────────────
    // MARK: - State colors & icons
    // ─────────────────────────────────────────────────────────

    var stateColor: Color {
        switch voiceEngine.voiceState {
        case .sleeping:   return .pSleeping.opacity(0.3)
        case .woken:      return .pWoken
        case .listening:  return .pListening
        case .countdown:  return .pCountdown
        case .executing:  return .pExecuting
        case .responding: return .pResponding
        }
    }

    var stateBorderColor: Color {
        switch voiceEngine.voiceState {
        case .sleeping:   return Color(hex: "2D2B4E")
        case .woken:      return Color(hex: "6D61F0")
        case .listening:  return Color(hex: "9D94FF")
        case .countdown:  return Color(hex: "B847FF")
        case .executing:  return Color(hex: "D8A8FF")
        case .responding: return Color(hex: "00EEC0")
        }
    }

    var micGradient: LinearGradient {
        switch voiceEngine.voiceState {
        case .sleeping:
            return LinearGradient(gradient: Gradient(colors: [Color(hex: "1A1830"), Color(hex: "0D0C1A")]),
                                  startPoint: .topLeading, endPoint: .bottomTrailing)
        case .woken:
            return LinearGradient(gradient: Gradient(colors: [Color(hex: "4338CA"), Color(hex: "3730A3")]),
                                  startPoint: .topLeading, endPoint: .bottomTrailing)
        case .listening:
            return LinearGradient(gradient: Gradient(colors: [Color(hex: "6C63FF"), Color(hex: "4F46E5")]),
                                  startPoint: .topLeading, endPoint: .bottomTrailing)
        case .countdown:
            return LinearGradient(gradient: Gradient(colors: [Color(hex: "9333EA"), Color(hex: "7E22CE")]),
                                  startPoint: .topLeading, endPoint: .bottomTrailing)
        case .executing:
            return LinearGradient(gradient: Gradient(colors: [Color(hex: "A855F7"), Color(hex: "7C3AED")]),
                                  startPoint: .topLeading, endPoint: .bottomTrailing)
        case .responding:
            return LinearGradient(gradient: Gradient(colors: [Color(hex: "00D4AA"), Color(hex: "0097A7")]),
                                  startPoint: .topLeading, endPoint: .bottomTrailing)
        }
    }

    var micIconName: String {
        switch voiceEngine.voiceState {
        case .sleeping:
            return (voiceEngine.isListening && voiceEngine.listeningMode == .wakeWord) ? "moon.fill" : "mic.fill"
        case .woken:      return "ear.fill"
        case .listening:  return "waveform"
        case .countdown:  return "timer"
        case .executing:  return "paperplane.fill"
        case .responding: return voiceEngine.isPlayingAudio ? "speaker.wave.2.fill" : "brain"
        }
    }

    // ─────────────────────────────────────────────────────────
    // MARK: - Animations
    // ─────────────────────────────────────────────────────────

    func syncAnimations(to state: VoiceState) {
        withAnimation(.easeOut(duration: 0.25)) {
            pulseScale = 1.0; wokenBreathe = 1.0; executingPulse = 1.0; respondingPulse = 1.0
        }
        switch state {
        case .sleeping:
            withAnimation(.easeOut(duration: 0.7)) { rotationAngle = 0; glowOpacity = 0 }
        case .woken:
            withAnimation(.linear(duration: 14).repeatForever(autoreverses: false)) { rotationAngle = 360 }
            withAnimation(.easeInOut(duration: 1.1).repeatForever(autoreverses: true)) {
                glowOpacity = 0.75; wokenBreathe = 1.10
            }
        case .listening:
            withAnimation(.linear(duration: 9).repeatForever(autoreverses: false)) { rotationAngle = 360 }
            withAnimation(.easeInOut(duration: 1.3).repeatForever(autoreverses: true)) {
                pulseScale = 1.13; glowOpacity = 0.85
            }
        case .countdown:
            withAnimation(.linear(duration: 6).repeatForever(autoreverses: false)) { rotationAngle = 360 }
            withAnimation(.easeInOut(duration: 0.5).repeatForever(autoreverses: true)) {
                pulseScale = 1.18; glowOpacity = 0.95
            }
        case .executing:
            withAnimation(.linear(duration: 3.5).repeatForever(autoreverses: false)) { rotationAngle = 360 }
            withAnimation(.easeInOut(duration: 0.35).repeatForever(autoreverses: true)) {
                executingPulse = 1.08; glowOpacity = 1.0
            }
        case .responding:
            withAnimation(.linear(duration: 5).repeatForever(autoreverses: false)) { rotationAngle = 360 }
            withAnimation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true)) {
                respondingPulse = 1.06; glowOpacity = 0.7
            }
        }
    }

    func toggleListening() {
        withAnimation(.spring(response: 0.4, dampingFraction: 0.7)) {
            if voiceEngine.isListening {
                voiceEngine.stopListening()
                withAnimation(.easeOut(duration: 0.5)) {
                    rotationAngle = 0; glowOpacity = 0
                    pulseScale = 1.0; wokenBreathe = 1.0; executingPulse = 1.0; respondingPulse = 1.0
                }
            } else {
                voiceEngine.startListening()
            }
        }
    }

    func startOrbitAnimation() {
        withAnimation(.linear(duration: 14).repeatForever(autoreverses: false)) { orbitRotation = 360 }
    }
}

// MARK: - PentagonFromTriangles

struct PentagonFromTriangles: View {
    let voiceState : VoiceState
    let rotation   : Double
    var baseColor: Color {
        switch voiceState {
        case .sleeping:   return Color(hex: "1C1635")
        case .woken:      return Color(hex: "4338CA")
        case .listening:  return Color(hex: "6C63FF")
        case .countdown:  return Color(hex: "9333EA")
        case .executing:  return Color(hex: "C084FC")
        case .responding: return Color(hex: "00D4AA")
        }
    }
    var sliceOpacity: Double {
        switch voiceState {
        case .sleeping:   return 0.06
        case .woken:      return 0.25
        case .listening:  return 0.32
        case .countdown:  return 0.42
        case .executing:  return 0.50
        case .responding: return 0.38
        }
    }
    var body: some View {
        ZStack {
            ForEach(0..<5) { i in
                TriangleSlice(index: i, totalSlices: 5)
                    .fill(LinearGradient(gradient: Gradient(colors: [baseColor.opacity(sliceOpacity), baseColor.opacity(0.01)]),
                                         startPoint: .top, endPoint: .bottom))
                    .rotationEffect(.degrees(rotation))
            }
            ForEach(0..<5) { i in
                TriangleSlice(index: i, totalSlices: 5)
                    .stroke(baseColor.opacity(0.18), lineWidth: 0.5)
                    .rotationEffect(.degrees(rotation))
            }
        }
        .animation(.easeInOut(duration: 0.4), value: voiceState)
    }
}

// MARK: - Shapes
struct TriangleSlice: Shape {
    let index: Int; let totalSlices: Int
    func path(in rect: CGRect) -> Path {
        let center = CGPoint(x: rect.midX, y: rect.midY)
        let radius = min(rect.width, rect.height) / 2
        let sa = (Double(index)     * 360.0 / Double(totalSlices) - 90) * .pi / 180
        let ea = (Double(index + 1) * 360.0 / Double(totalSlices) - 90) * .pi / 180
        var p = Path()
        p.move(to: center)
        p.addLine(to: CGPoint(x: center.x + radius * CGFloat(cos(sa)), y: center.y + radius * CGFloat(sin(sa))))
        p.addLine(to: CGPoint(x: center.x + radius * CGFloat(cos(ea)), y: center.y + radius * CGFloat(sin(ea))))
        p.closeSubpath(); return p
    }
}
struct GridBackgroundView: View {
    var body: some View {
        Canvas { context, size in
            let spacing: CGFloat = 40
            let color = Color(hex: "6C63FF").opacity(0.25)
            var x: CGFloat = 0
            while x <= size.width {
                var p = Path(); p.move(to: CGPoint(x: x, y: 0)); p.addLine(to: CGPoint(x: x, y: size.height))
                context.stroke(p, with: .color(color), lineWidth: 0.4); x += spacing
            }
            var y: CGFloat = 0
            while y <= size.height {
                var p = Path(); p.move(to: CGPoint(x: 0, y: y)); p.addLine(to: CGPoint(x: size.width, y: y))
                context.stroke(p, with: .color(color), lineWidth: 0.4); y += spacing
            }
        }.ignoresSafeArea()
    }
}

