// SettingsView.swift — v3.2
// - Cho phép nhập URL với cổng tuỳ ý (http/https)
// - Thêm nút kiểm tra kết nối
// - Lưu wake word, URL và token

import SwiftUI

struct SettingsView: View {
    @ObservedObject var voiceEngine: VoiceEngine
    @ObservedObject var commandStore: CommandStore
    @Environment(\.dismiss) var dismiss

    // ── URLs ────────────────────────────────────────────────────
    @State private var windowsAIURL  = UserDefaults.standard.string(forKey: "windows_ai_url")
                                       ?? "http://100.x.x.x:9090"
    @State private var macMiniURL    = UserDefaults.standard.string(forKey: "tailscale_url")
                                       ?? "http://100.x.x.x:9090"
    @State private var authToken     = UserDefaults.standard.string(forKey: "auth_token") ?? ""
    @State private var pentaKuruURL = UserDefaults.standard.string(forKey: "penta_kuru_url") ?? ""
    @State private var pentaKuruToken = UserDefaults.standard.string(forKey: "penta_kuru_token") ?? ""

    // ── Wake word ───────────────────────────────────────────────
    @State private var wakeWordInput = UserDefaults.standard.string(forKey: "wake_word") ?? "Penta"

    // ── Test connection states ──────────────────────────────────
    @State private var testingWindowsAI = false
    @State private var windowsAIStatus: String?
    @State private var testingMacMini = false
    @State private var macMiniStatus: String?
    @State private var showSaved = false
    var body: some View {
        NavigationView {
            ZStack {
                Color(hex: "0A0A0F").ignoresSafeArea()
                ScrollView {
                    VStack(spacing: 20) {
                        settingsHeader

                        // ── Kết nối Windows AI ───────────────────────────
                        settingsSection(title: "WINDOWS AI (TRỰC TIẾP)", icon: "desktopcomputer") {
                            VStack(alignment: .leading, spacing: 6) {
                                Text("URL WINDOWS AI".uppercased())
                                    .font(.custom("Courier New", size: 10))
                                    .foregroundColor(Color(hex: "6C63FF")).tracking(2)
                                
                                HStack {
                                    TextField("http://192.168.1.100:9090", text: $windowsAIURL)
                                        .autocorrectionDisabled()
                                        .autocapitalization(.none)
                                        .font(.custom("Courier New", size: 13))
                                        .foregroundColor(.white)
                                        .padding(12)
                                        .background(
                                            RoundedRectangle(cornerRadius: 8)
                                                .fill(Color.white.opacity(0.04))
                                                .overlay(RoundedRectangle(cornerRadius: 8)
                                                    .stroke(Color.white.opacity(0.1), lineWidth: 1))
                                        )
                                    
                                    Button(action: testWindowsAI) {
                                        if testingWindowsAI {
                                            ProgressView().frame(width: 32, height: 32)
                                        } else {
                                            Image(systemName: "network")
                                                .foregroundColor(Color(hex: "6C63FF"))
                                        }
                                    }
                                    .frame(width: 44)
                                }
                                
                                if let status = windowsAIStatus {
                                    Text(status)
                                        .font(.custom("Courier New", size: 9))
                                        .foregroundColor(status == "✅ OK" ? .green : .red)
                                }
                                
                                Text("Ví dụ: http://192.168.1.100:9090 hoặc https://domain.com:9090")
                                    .font(.custom("Courier New", size: 9))
                                    .foregroundColor(Color.white.opacity(0.3))
                            }
                            
                            settingsField(
                                label: "Auth Token",
                                placeholder: "để trống nếu không dùng",
                                text: $authToken,
                                isSecure: true,
                                hint: "AI_AUTH env trên Windows (để trống = không cần)"
                            )
                        }

                        // ── Mac mini ─────────────────────────────────────
                        settingsSection(title: "MAC MINI (TUYA / BẬT TẮT PC)", icon: "power") {
                            VStack(alignment: .leading, spacing: 6) {
                                Text("URL MAC MINI".uppercased())
                                    .font(.custom("Courier New", size: 10))
                                    .foregroundColor(Color(hex: "6C63FF")).tracking(2)
                                
                                HStack {
                                    TextField("http://192.168.1.200:9090", text: $macMiniURL)
                                        .autocorrectionDisabled()
                                        .autocapitalization(.none)
                                        .font(.custom("Courier New", size: 13))
                                        .foregroundColor(.white)
                                        .padding(12)
                                        .background(
                                            RoundedRectangle(cornerRadius: 8)
                                                .fill(Color.white.opacity(0.04))
                                                .overlay(RoundedRectangle(cornerRadius: 8)
                                                    .stroke(Color.white.opacity(0.1), lineWidth: 1))
                                        )
                                    
                                    Button(action: testMacMini) {
                                        if testingMacMini {
                                            ProgressView().frame(width: 32, height: 32)
                                        } else {
                                            Image(systemName: "network")
                                                .foregroundColor(Color(hex: "6C63FF"))
                                        }
                                    }
                                    .frame(width: 44)
                                }
                                
                                if let status = macMiniStatus {
                                    Text(status)
                                        .font(.custom("Courier New", size: 9))
                                        .foregroundColor(status == "✅ OK" ? .green : .red)
                                }
                                
                                Text("Ví dụ: http://192.168.1.200:9090")
                                    .font(.custom("Courier New", size: 9))
                                    .foregroundColor(Color.white.opacity(0.3))
                            }
                        }
                        // ── Penta Kuru (Windows) ─────────────────────────────────────
                        settingsSection(title: "PENTA KURU (WINDOWS)", icon: "pc") {
                            settingsField(
                                label: "Penta Kuru URL",
                                placeholder: "http://192.168.1.x:7777",
                                text: $pentaKuruURL,
                                hint: "URL của máy Windows chạy pentaKuruV3.py (có thể qua Tailscale)"
                            )
                            settingsField(
                                label: "Penta Kuru Token",
                                placeholder: "để trống nếu không dùng",
                                text: $pentaKuruToken,
                                isSecure: true,
                                hint: "Token xác thực từ server PentaKuru trên Windows"
                            )
                        }

                        // Trong hàm saveSettings(), thêm dòng lưu:

                        // ── Giọng nói (giữ nguyên) ───────────────────────
                        settingsSection(title: "NHẬN DẠNG GIỌNG NÓI", icon: "waveform") {
                            settingsField(
                                label: "Wake Word",
                                placeholder: "Penta",
                                text: $wakeWordInput,
                                hint: "Từ khoá kích hoạt — lưu khi bấm LƯU CÀI ĐẶT"
                            )

                            // Mode picker (giữ nguyên)
                            VStack(alignment: .leading, spacing: 8) {
                                Text("CHẾ ĐỘ LẮNG NGHE")
                                    .font(.custom("Courier New", size: 10))
                                    .foregroundColor(Color(hex: "6C63FF"))
                                    .tracking(2)

                                HStack(spacing: 8) {
                                    ForEach(ListeningMode.allCases, id: \.self) { mode in
                                        Button(action: { voiceEngine.listeningMode = mode }) {
                                            VStack(spacing: 4) {
                                                Image(systemName: mode == .continuous
                                                      ? "waveform.circle" : "bolt.circle")
                                                    .font(.system(size: 20))
                                                Text(mode.rawValue)
                                                    .font(.custom("Courier New", size: 9))
                                                    .tracking(1)
                                            }
                                            .foregroundColor(voiceEngine.listeningMode == mode
                                                             ? Color(hex: "6C63FF")
                                                             : Color.white.opacity(0.3))
                                            .frame(maxWidth: .infinity)
                                            .padding(.vertical, 12)
                                            .background(
                                                RoundedRectangle(cornerRadius: 10)
                                                    .fill(voiceEngine.listeningMode == mode
                                                          ? Color(hex: "6C63FF").opacity(0.15)
                                                          : Color.white.opacity(0.03))
                                                    .overlay(
                                                        RoundedRectangle(cornerRadius: 10).stroke(
                                                            voiceEngine.listeningMode == mode
                                                            ? Color(hex: "6C63FF").opacity(0.4)
                                                            : Color.white.opacity(0.07),
                                                            lineWidth: 1
                                                        )
                                                    )
                                            )
                                        }
                                    }
                                }

                                Text(voiceEngine.listeningMode == .wakeWord
                                     ? "Nói \"\(wakeWordInput)\" trước, rồi nói lệnh"
                                     : "App lắng nghe liên tục, nói lệnh bất kỳ lúc nào")
                                    .font(.custom("Courier New", size: 10))
                                    .foregroundColor(voiceEngine.listeningMode == .wakeWord
                                                     ? Color(hex: "FFB800").opacity(0.7)
                                                     : Color(hex: "00FF88").opacity(0.7))
                            }
                        }

                        // ── Kiến trúc (giữ nguyên) ───────────────────────
                        settingsSection(title: "KIẾN TRÚC HỆ THỐNG", icon: "cpu") {
                            architectureGuide
                        }

                        // ── Lưu ──────────────────────────────────────────
                        Button(action: saveSettings) {
                            HStack {
                                Image(systemName: showSaved ? "checkmark" : "square.and.arrow.down")
                                Text(showSaved ? "ĐÃ LƯU" : "LƯU CÀI ĐẶT")
                            }
                            .font(.custom("Courier New", size: 13))
                            .fontWeight(.bold)
                            .tracking(2)
                            .foregroundColor(.white)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 14)
                            .background(
                                RoundedRectangle(cornerRadius: 12)
                                    .fill(showSaved
                                          ? LinearGradient(colors: [Color(hex: "00FF88"), Color(hex: "00CC66")],
                                                           startPoint: .leading, endPoint: .trailing)
                                          : LinearGradient(colors: [Color(hex: "6C63FF"), Color(hex: "8B5CF6")],
                                                           startPoint: .leading, endPoint: .trailing))
                            )
                        }
                        .padding(.top, 8)
                    }
                    .padding(20)
                }
            }
            .navigationBarHidden(true)
            .overlay(alignment: .topTrailing) {
                Button(action: { dismiss() }) {
                    Image(systemName: "xmark")
                        .font(.system(size: 14, weight: .medium))
                        .foregroundColor(Color.white.opacity(0.5))
                        .frame(width: 32, height: 32)
                        .background(Circle().fill(Color.white.opacity(0.08)))
                }
                .padding(.top, 16).padding(.trailing, 20)
            }
        }
    }

    // MARK: - Save
    func saveSettings() {
        let defaults = UserDefaults.standard
        defaults.set(windowsAIURL, forKey: "windows_ai_url")
        defaults.set(macMiniURL,   forKey: "tailscale_url")
        defaults.set(authToken,    forKey: "auth_token")
        defaults.set(pentaKuruURL, forKey: "penta_kuru_url")
        defaults.set(pentaKuruToken, forKey: "penta_kuru_token")
        let trimmed = wakeWordInput.trimmingCharacters(in: .whitespaces)
        let final   = trimmed.isEmpty ? "Penta" : trimmed
        defaults.set(final, forKey: "wake_word")
        voiceEngine.wakeWord = final

        defaults.synchronize()

        withAnimation { showSaved = true }
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
            withAnimation { showSaved = false }
        }
    }

    // MARK: - Test connection
    private func testWindowsAI() {
        testingWindowsAI = true
        windowsAIStatus = nil
        testConnection(urlString: windowsAIURL, endpoint: "api/health") { success in
            windowsAIStatus = success ? "✅ OK" : "❌ Không kết nối được"
            testingWindowsAI = false
        }
    }

    private func testMacMini() {
        testingMacMini = true
        macMiniStatus = nil
        testConnection(urlString: macMiniURL, endpoint: "api/health") { success in
            macMiniStatus = success ? "✅ OK" : "❌ Không kết nối được"
            testingMacMini = false
        }
    }

    private func testConnection(urlString: String, endpoint: String, completion: @escaping (Bool) -> Void) {
        guard var url = URL(string: urlString) else {
            completion(false)
            return
        }
        url = url.appendingPathComponent(endpoint)
        var request = URLRequest(url: url)
        request.timeoutInterval = 5
        URLSession.shared.dataTask(with: request) { _, response, error in
            let success = error == nil && (response as? HTTPURLResponse)?.statusCode == 200
            DispatchQueue.main.async {
                completion(success)
            }
        }.resume()
    }

    // MARK: - Architecture Guide (giữ nguyên)
    var settingsHeader: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text("CÀI ĐẶT")
                    .font(.custom("Courier New", size: 20)).fontWeight(.bold)
                    .foregroundColor(.white).tracking(4)
                Text("PENTA COMMAND")
                    .font(.custom("Courier New", size: 11))
                    .foregroundColor(Color(hex: "6C63FF")).tracking(3)
            }
            Spacer()
            PentagonShape()
                .fill(Color(hex: "6C63FF").opacity(0.2))
                .overlay(PentagonShape().stroke(Color(hex: "6C63FF").opacity(0.5), lineWidth: 1))
                .frame(width: 40, height: 40)
        }
    }

    var architectureGuide: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(architectureSteps, id: \.0) { step in
                HStack(alignment: .top, spacing: 10) {
                    Text(step.0)
                        .font(.custom("Courier New", size: 14))
                        .foregroundColor(Color(hex: "6C63FF"))
                        .frame(width: 20)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(step.1)
                            .font(.custom("Courier New", size: 11)).fontWeight(.bold)
                            .foregroundColor(.white)
                        Text(step.2)
                            .font(.custom("Courier New", size: 10))
                            .foregroundColor(Color.white.opacity(0.4))
                    }
                }
                if step.0 != "3" {
                    HStack {
                        Spacer().frame(width: 30)
                        Rectangle()
                            .fill(Color(hex: "6C63FF").opacity(0.2))
                            .frame(width: 1, height: 12)
                    }
                }
            }
        }
    }

    let architectureSteps = [
        ("1", "iOS App (Swift)",         "Giọng nói → text → POST /api/chat"),
        ("2", "Windows PC (Tailscale)",  "ai_server.py → PentaAI → TTS → audio"),
        ("3", "Mac mini (chỉ Tuya)",     "Bật/tắt ổ điện → cấp nguồn PC"),
    ]

    // MARK: - Subviews
    func settingsField(
        label: String, placeholder: String,
        text: Binding<String>,
        isSecure: Bool = false, hint: String? = nil
    ) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label.uppercased())
                .font(.custom("Courier New", size: 10))
                .foregroundColor(Color(hex: "6C63FF")).tracking(2)
            Group {
                if isSecure {
                    SecureField(placeholder, text: text)
                } else {
                    TextField(placeholder, text: text)
                        .autocorrectionDisabled()
                        .autocapitalization(.none)
                }
            }
            .font(.custom("Courier New", size: 13))
            .foregroundColor(.white)
            .padding(12)
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .fill(Color.white.opacity(0.04))
                    .overlay(RoundedRectangle(cornerRadius: 8)
                        .stroke(Color.white.opacity(0.1), lineWidth: 1))
            )
            if let hint {
                Text(hint)
                    .font(.custom("Courier New", size: 9))
                    .foregroundColor(Color.white.opacity(0.3)).tracking(0.5)
            }
        }
    }

    @ViewBuilder
    func settingsSection<Content: View>(
        title: String, icon: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) {
                Image(systemName: icon).font(.system(size: 12))
                    .foregroundColor(Color(hex: "6C63FF"))
                Text(title)
                    .font(.custom("Courier New", size: 10)).fontWeight(.bold)
                    .foregroundColor(Color(hex: "6C63FF")).tracking(2)
                Spacer()
            }
            VStack(spacing: 14) { content() }
                .padding(16)
                .background(
                    RoundedRectangle(cornerRadius: 14)
                        .fill(Color.white.opacity(0.03))
                        .overlay(RoundedRectangle(cornerRadius: 14)
                            .stroke(Color.white.opacity(0.07), lineWidth: 1))
                )
        }
    }
}

