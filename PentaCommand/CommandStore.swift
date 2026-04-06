import Foundation
import SwiftUI
import Combine

struct VoiceCommand: Identifiable, Codable {
    var id = UUID()
    var name: String
    var trigger: String          // Từ khoá kích hoạt
    var endpoint: String         // API endpoint trên Mac mini
    var icon: String             // SF Symbol name
    var color: String            // Hex color
    var isEnabled: Bool = true
    var description: String = ""
}

class CommandStore: ObservableObject {
    @Published var commands: [VoiceCommand] = []
    
    private let saveKey = "penta_commands"
    
    init() {
        loadCommands()
        if commands.isEmpty {
            loadDefaults()
        }
    }
    
    private func loadDefaults() {
        commands = [
            // ── PC Control ─────────────────────────────────────────────────
            VoiceCommand(
                name: "Bật PC",
                trigger: "bật pc",
                endpoint: "/api/turn-on-pc",
                icon: "desktopcomputer",
                color: "6C63FF",
                description: "Cấp điện và khởi động Windows PC"
            ),
            VoiceCommand(
                name: "Tắt PC",
                trigger: "tắt pc",
                endpoint: "/api/turn-off-pc",
                icon: "power",
                color: "FF4444",
                description: "Ngắt điện Windows PC"
            ),

            // ── PentaMi Mode ───────────────────────────────────────────────
            VoiceCommand(
                name: "Bật PentaMi",
                trigger: "bật chế độ pentami",
                endpoint: "/api/pentami/on",
                icon: "heart.fill",
                color: "FF69B4",
                description: "Bật chế độ trò chuyện thân mật PentaMi (Bonsai-8B)"
            ),
            VoiceCommand(
                name: "Tắt PentaMi",
                trigger: "tắt chế độ pentami",
                endpoint: "/api/pentami/off",
                icon: "heart.slash",
                color: "AA4488",
                description: "Tắt chế độ PentaMi, quay về chat thường"
            ),
            VoiceCommand(
                name: "Xoá ngữ cảnh",
                trigger: "xoá ngữ cảnh",
                endpoint: "/api/pentami/clear",
                icon: "xmark.circle",
                color: "888888",
                description: "Xoá lịch sử hội thoại PentaMi và bắt đầu lại"
            ),
            VoiceCommand(
                name: "Trạng thái PentaMi",
                trigger: "trạng thái pentami",
                endpoint: "/api/pentami/status",
                icon: "info.bubble",
                color: "00BFFF",
                description: "Xem trạng thái chế độ PentaMi và số lượt hội thoại"
            ),

            // ── System ─────────────────────────────────────────────────────
            VoiceCommand(
                name: "Hormone",
                trigger: "trạng thái cảm xúc",
                endpoint: "/api/hormone_status",
                icon: "waveform.path.ecg",
                color: "FFB800",
                description: "Xem trạng thái hormone và cảm xúc của AI"
            ),
            VoiceCommand(
                name: "Nhắc nhở",
                trigger: "danh sách nhắc nhở",
                endpoint: "/api/reminders/status",
                icon: "bell.fill",
                color: "FF8C00",
                description: "Xem danh sách nhắc nhở đang chờ"
            ),
        ]
        saveCommands()
    }
    
    func addCommand(_ command: VoiceCommand) {
        commands.append(command)
        saveCommands()
    }
    
    func updateCommand(_ command: VoiceCommand) {
        if let idx = commands.firstIndex(where: { $0.id == command.id }) {
            commands[idx] = command
            saveCommands()
        }
    }
    
    func deleteCommand(at offsets: IndexSet) {
        commands.remove(atOffsets: offsets)
        saveCommands()
    }
    
    func toggleCommand(_ command: VoiceCommand) {
        if let idx = commands.firstIndex(where: { $0.id == command.id }) {
            commands[idx].isEnabled.toggle()
            saveCommands()
        }
    }
    
    private func saveCommands() {
        if let data = try? JSONEncoder().encode(commands) {
            UserDefaults.standard.set(data, forKey: saveKey)
        }
    }
    
    private func loadCommands() {
        if let data = UserDefaults.standard.data(forKey: saveKey),
           let decoded = try? JSONDecoder().decode([VoiceCommand].self, from: data) {
            commands = decoded
        }
    }
}

