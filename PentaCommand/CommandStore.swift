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
            VoiceCommand(
                name: "Bật PC",
                trigger: "bật pc",
                endpoint: "/api/turn-on-pc",
                icon: "pc",
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
            VoiceCommand(
                name: "Bật AI Studio",
                trigger: "mở ai",
                endpoint: "/api/start-ai",
                icon: "cpu",
                color: "00FF88",
                description: "Khởi chạy script AI trên Windows"
            ),
            VoiceCommand(
                name: "Trạng thái hệ thống",
                trigger: "trạng thái",
                endpoint: "/api/status",
                icon: "info.circle",
                color: "FFB800",
                description: "Kiểm tra trạng thái hệ thống"
            ),
            VoiceCommand(
                name: "Bật đèn phòng",
                trigger: "bật đèn",
                endpoint: "/api/light/on",
                icon: "lightbulb",
                color: "FFD700",
                description: "Điều khiển đèn qua Home Assistant"
            ),
            VoiceCommand(
                name: "Tắt đèn phòng",
                trigger: "tắt đèn",
                endpoint: "/api/light/off",
                icon: "lightbulb.slash",
                color: "444466",
                description: "Tắt đèn qua Home Assistant"
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

