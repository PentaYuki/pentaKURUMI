// SplashView.swift — PentaCommand
// Màn hình loading xuất hiện trước ContentView
// Giải quyết vấn đề app bị "treo" do tải tài nguyên

import SwiftUI

struct SplashView: View {
    @Binding var isVisible: Bool

    // Animation states
    @State private var pentagonRotation : Double  = 0
    @State private var pentagonScale    : CGFloat = 0.4
    @State private var pentagonOpacity  : Double  = 0
    @State private var glowOpacity      : Double  = 0
    @State private var textOpacity      : Double  = 0
    @State private var dotsOpacity      : Double  = 0
    @State private var ringScale        : [CGFloat] = [0.5, 0.5, 0.5]
    @State private var ringOpacity      : [Double]  = [0, 0, 0]
    @State private var loadingProgress  : Double  = 0
    @State private var loadingText      : String  = "Khởi động hệ thống"
    @State private var dotCount         : Int     = 0

    private let accentColor  = Color(hex: "6C63FF")
    private let tealColor    = Color(hex: "00D4AA")
    private let darkBG       = Color(hex: "0A0A0F")

    // Loading phases
    private let phases: [(String, Double)] = [
        ("Khởi động hệ thống",   0.0),
        ("Tải nhận dạng giọng",  0.30),
        ("Kết nối mạng",         0.60),
        ("Sẵn sàng",             0.90),
    ]

    var body: some View {
        ZStack {
            // Background
            darkBG.ignoresSafeArea()
            GridBackgroundView().opacity(0.08)

            VStack(spacing: 0) {
                Spacer()

                // ── Animated Pentagon ────────────────────────────────────
                ZStack {
                    // Outer glow rings
                    ForEach(0..<3) { i in
                        PentagonShape()
                            .stroke(accentColor.opacity(ringOpacity[i] * 0.4), lineWidth: 1)
                            .frame(width: 200 + CGFloat(i * 30),
                                   height: 200 + CGFloat(i * 30))
                            .scaleEffect(ringScale[i])
                            .rotationEffect(.degrees(pentagonRotation * 0.5 + Double(i) * 8))
                    }

                    // Inner filled pentagon (glow)
                    PentagonShape()
                        .fill(
                            RadialGradient(
                                colors: [accentColor.opacity(0.18), Color.clear],
                                center: .center,
                                startRadius: 20,
                                endRadius: 100
                            )
                        )
                        .frame(width: 180, height: 180)
                        .opacity(glowOpacity)

                    // Main pentagon border
                    PentagonShape()
                        .stroke(
                            LinearGradient(
                                colors: [accentColor, tealColor, accentColor],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            ),
                            lineWidth: 1.8
                        )
                        .frame(width: 180, height: 180)
                        .rotationEffect(.degrees(pentagonRotation))
                        .shadow(color: accentColor.opacity(0.6), radius: 10)

                    // Dark fill
                    PentagonShape()
                        .fill(
                            RadialGradient(
                                colors: [Color(hex: "12101E"), Color(hex: "070710")],
                                center: .center,
                                startRadius: 5,
                                endRadius: 90
                            )
                        )
                        .frame(width: 172, height: 172)
                        .rotationEffect(.degrees(pentagonRotation))

                    // Center logo
                    VStack(spacing: 4) {
                        Image(systemName: "pentagon.fill")
                            .font(.system(size: 28, weight: .light))
                            .foregroundStyle(
                                LinearGradient(
                                    colors: [accentColor, tealColor],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                        Text("P")
                            .font(.custom("Courier New", size: 22))
                            .fontWeight(.bold)
                            .foregroundColor(.white)
                            .tracking(2)
                    }
                }
                .scaleEffect(pentagonScale)
                .opacity(pentagonOpacity)

                Spacer().frame(height: 52)

                // ── App Title ────────────────────────────────────────────
                VStack(spacing: 6) {
                    Text("PENTA")
                        .font(.custom("Courier New", size: 28))
                        .fontWeight(.bold)
                        .foregroundColor(.white)
                        .tracking(10)
                    Text("COMMAND")
                        .font(.custom("Courier New", size: 12))
                        .foregroundColor(accentColor)
                        .tracking(8)
                }
                .opacity(textOpacity)

                Spacer().frame(height: 60)

                // ── Progress Bar ─────────────────────────────────────────
                VStack(spacing: 14) {
                    ZStack(alignment: .leading) {
                        RoundedRectangle(cornerRadius: 2)
                            .fill(Color.white.opacity(0.06))
                            .frame(width: 200, height: 2)
                        RoundedRectangle(cornerRadius: 2)
                            .fill(
                                LinearGradient(
                                    colors: [accentColor, tealColor],
                                    startPoint: .leading,
                                    endPoint: .trailing
                                )
                            )
                            .frame(width: max(4, 200 * loadingProgress), height: 2)
                            .shadow(color: accentColor.opacity(0.8), radius: 4)
                            .animation(.easeInOut(duration: 0.4), value: loadingProgress)
                    }

                    // Loading text + animated dots
                    HStack(spacing: 2) {
                        Text(loadingText)
                            .font(.custom("Courier New", size: 11))
                            .foregroundColor(Color.white.opacity(0.4))
                            .tracking(1)
                            .animation(.none, value: loadingText)
                        Text(String(repeating: ".", count: dotCount))
                            .font(.custom("Courier New", size: 11))
                            .foregroundColor(accentColor.opacity(0.7))
                            .frame(width: 20, alignment: .leading)
                    }
                }
                .opacity(dotsOpacity)

                Spacer()
            }
            .padding(.horizontal, 32)
        }
        .onAppear { runSplashSequence() }
    }

    // MARK: - Animation Sequence

    private func runSplashSequence() {
        // Step 1: Pentagon scale in (0.0s)
        withAnimation(.spring(response: 0.7, dampingFraction: 0.6)) {
            pentagonScale   = 1.0
            pentagonOpacity = 1.0
        }

        // Step 2: Glow + rings expand (0.3s)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            withAnimation(.easeOut(duration: 0.6)) { glowOpacity = 0.8 }
            for i in 0..<3 {
                withAnimation(
                    .easeOut(duration: 0.7).delay(Double(i) * 0.12)
                ) {
                    ringScale[i]   = 1.0
                    ringOpacity[i] = 1.0
                }
            }
        }

        // Step 3: Pentagon spin start (0.4s)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
            withAnimation(.linear(duration: 12).repeatForever(autoreverses: false)) {
                pentagonRotation = 360
            }
        }

        // Step 4: Text fade in (0.6s)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
            withAnimation(.easeIn(duration: 0.5)) {
                textOpacity = 1.0
                dotsOpacity = 1.0
            }
        }

        // Step 5: Progress phases + dots animation
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
            startDotAnimation()
            animatePhases()
        }
    }

    private func startDotAnimation() {
        Timer.scheduledTimer(withTimeInterval: 0.4, repeats: true) { timer in
            guard isVisible else { timer.invalidate(); return }
            dotCount = (dotCount % 3) + 1
        }
    }

    private func animatePhases() {
        let totalDuration: Double = 1.8   // tổng thời gian loading (giây)
        let phaseCount = phases.count

        for (idx, phase) in phases.enumerated() {
            let delay = totalDuration * phase.1

            DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
                guard isVisible else { return }
                withAnimation(.easeInOut(duration: 0.3)) {
                    loadingText    = phase.0
                    loadingProgress = phase.1 + (1.0 / Double(phaseCount))
                }
            }
        }

        // Finish loading
        DispatchQueue.main.asyncAfter(deadline: .now() + totalDuration) {
            guard isVisible else { return }
            withAnimation(.easeInOut(duration: 0.3)) {
                loadingProgress = 1.0
                loadingText     = "Hoàn tất"
            }

            // Fade out splash → show ContentView
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                withAnimation(.easeInOut(duration: 0.6)) {
                    isVisible = false
                }
            }
        }
    }
}

// MARK: - Preview
#Preview {
    SplashView(isVisible: .constant(true))
        .preferredColorScheme(.dark)
}
