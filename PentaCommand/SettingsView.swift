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
    @State private var windowsAIURL  = UserDefaults.standard.string(forKey: "active_ai_server_url")
                                       ?? UserDefaults.standard.string(forKey: "windows_ai_url")
                                       ?? "http://100.x.x.x:9090"
    @State private var aiServerPoolText = SettingsView.loadAIServerPoolText()
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
    @State private var showAIServers = true
    @State private var showVoice = true
    @State private var showMacMini = false
    @State private var showPentaKuru = false
    @State private var showArchitecture = false
    var body: some View {
        NavigationView {
            ZStack {
                Color(hex: "0A0A0F").ignoresSafeArea()
                ScrollView {
                    VStack(spacing: 20) {
                        settingsHeader

                        // ── AI Server Pool ───────────────────────────────
                        settingsSection(title: "AI SERVER POOL", icon: "network", isExpanded: $showAIServers) {
                            VStack(alignment: .leading, spacing: 6) {
                                Text("ACTIVE AI SERVER".uppercased())
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
                                
                                Text("App sẽ dùng URL này cho chat, WS và các AI endpoint mặc định.")
                                    .font(.custom("Courier New", size: 9))
                                    .foregroundColor(Color.white.opacity(0.3))
                            }

                            VStack(alignment: .leading, spacing: 6) {
                                Text("DANH SÁCH AI SERVER".uppercased())
                                    .font(.custom("Courier New", size: 10))
                                    .foregroundColor(Color(hex: "6C63FF")).tracking(2)

                                TextEditor(text: $aiServerPoolText)
                                    .font(.custom("Courier New", size: 12))
                                    .foregroundColor(.white)
                                    .scrollContentBackground(.hidden)
                                    .frame(minHeight: 96)
                                    .padding(8)
                                    .background(
                                        RoundedRectangle(cornerRadius: 8)
                                            .fill(Color.white.opacity(0.04))
                                            .overlay(RoundedRectangle(cornerRadius: 8)
                                                .stroke(Color.white.opacity(0.1), lineWidth: 1))
                                    )

                                Text("Mỗi dòng là một AI server. Ví dụ: local, cloud gateway, server agent chuyên dụng.")
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
                        settingsSection(title: "MAC MINI (TUYA / BẬT TẮT PC)", icon: "power", isExpanded: $showMacMini) {
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
                        settingsSection(title: "PENTA KURU (WINDOWS)", icon: "pc", isExpanded: $showPentaKuru) {
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
                        settingsSection(title: "NHẬN DẠNG GIỌNG NÓI", icon: "waveform", isExpanded: $showVoice) {
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
                        settingsSection(title: "KIẾN TRÚC HỆ THỐNG", icon: "cpu", isExpanded: $showArchitecture) {
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
        let aiPool = parseAIServerPool(aiServerPoolText, fallback: windowsAIURL)
        defaults.set(windowsAIURL, forKey: "windows_ai_url")
        defaults.set(windowsAIURL, forKey: "active_ai_server_url")
        defaults.set(aiPool, forKey: "ai_server_pool")
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
                Text("Tối giản để dễ thao tác")
                    .font(.custom("Courier New", size: 10))
                    .foregroundColor(Color.white.opacity(0.35))
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
        ("1", "iOS App (Swift)",         "Giọng nói → text → WS/API gateway"),
        ("2", "AI Server Pool",          "Local / Cloud / Agent server tuỳ active URL"),
        ("3", "Mac mini / Device Layer", "Tuya, PC power, endpoint điều khiển thiết bị"),
    ]

    private static func loadAIServerPoolText() -> String {
        let defaults = UserDefaults.standard
        let stored = defaults.array(forKey: "ai_server_pool") as? [String] ?? []
        if !stored.isEmpty {
            return stored.joined(separator: "\n")
        }
        return defaults.string(forKey: "windows_ai_url") ?? "http://100.x.x.x:9090"
    }

    private func parseAIServerPool(_ raw: String, fallback: String) -> [String] {
        let lines = raw
            .split(whereSeparator: \ .isNewline)
            .map { String($0).trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        if lines.isEmpty {
            return [fallback.trimmingCharacters(in: .whitespacesAndNewlines)]
        }
        return Array(NSOrderedSet(array: lines)) as? [String] ?? lines
    }

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
        isExpanded: Binding<Bool>,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Button {
                withAnimation(.easeInOut(duration: 0.2)) {
                    isExpanded.wrappedValue.toggle()
                }
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: icon).font(.system(size: 12))
                        .foregroundColor(Color(hex: "6C63FF"))
                    Text(title)
                        .font(.custom("Courier New", size: 10)).fontWeight(.bold)
                        .foregroundColor(Color(hex: "6C63FF")).tracking(2)
                    Spacer()
                    Image(systemName: isExpanded.wrappedValue ? "chevron.up" : "chevron.down")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundColor(Color.white.opacity(0.45))
                }
            }
            .buttonStyle(.plain)

            if isExpanded.wrappedValue {
                VStack(spacing: 14) { content() }
                    .padding(16)
                    .background(
                        RoundedRectangle(cornerRadius: 14)
                            .fill(Color.white.opacity(0.03))
                            .overlay(RoundedRectangle(cornerRadius: 14)
                                .stroke(Color.white.opacity(0.07), lineWidth: 1))
                    )
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
    }
}

