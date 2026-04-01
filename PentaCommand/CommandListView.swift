import SwiftUI
struct CommandListView: View {
    @ObservedObject var commandStore: CommandStore
    @Environment(\.dismiss) var dismiss
    @State private var showAddCommand = false
    @State private var editingCommand: VoiceCommand? = nil
    
    let iconColors = ["6C63FF", "FF4444", "00FF88", "FFB800", "FF6B9D", "00BFFF", "FF8C00", "9B59B6"]
    
    var body: some View {
        NavigationView {
            ZStack {
                Color(hex: "0A0A0F").ignoresSafeArea()
                
                VStack(spacing: 0) {
                    // Header
                    listHeader
                    
                    if commandStore.commands.isEmpty {
                        emptyState
                    } else {
                        ScrollView {
                            LazyVStack(spacing: 10) {
                                ForEach(commandStore.commands) { command in
                                    CommandRowView(
                                        command: command,
                                        onToggle: { commandStore.toggleCommand(command) },
                                        onEdit: { editingCommand = command }
                                    )
                                }
                            }
                            .padding(.horizontal, 20)
                            .padding(.vertical, 12)
                        }
                    }
                }
            }
            .navigationBarHidden(true)
            .sheet(isPresented: $showAddCommand) {
                CommandEditorView(commandStore: commandStore, command: nil)
            }
            .sheet(item: $editingCommand) { command in
                CommandEditorView(commandStore: commandStore, command: command)
            }
        }
    }
    
    var listHeader: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("LỆNH GIỌNG NÓI")
                    .font(.custom("Courier New", size: 16))
                    .fontWeight(.bold)
                    .foregroundColor(.white)
                    .tracking(3)
                Text("\(commandStore.commands.filter(\.isEnabled).count) / \(commandStore.commands.count) đang hoạt động")
                    .font(.custom("Courier New", size: 10))
                    .foregroundColor(Color.white.opacity(0.3))
                    .tracking(1)
            }
            
            Spacer()
            
            Button(action: { showAddCommand = true }) {
                Image(systemName: "plus")
                    .font(.system(size: 16, weight: .medium))
                    .foregroundColor(.white)
                    .frame(width: 36, height: 36)
                    .background(
                        RoundedRectangle(cornerRadius: 10)
                            .fill(Color(hex: "6C63FF").opacity(0.3))
                            .overlay(
                                RoundedRectangle(cornerRadius: 10)
                                    .stroke(Color(hex: "6C63FF").opacity(0.5), lineWidth: 1)
                            )
                    )
            }
            
            Button(action: { dismiss() }) {
                Image(systemName: "xmark")
                    .font(.system(size: 14))
                    .foregroundColor(Color.white.opacity(0.4))
                    .frame(width: 36, height: 36)
                    .background(Circle().fill(Color.white.opacity(0.06)))
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 16)
        .background(
            Rectangle()
                .fill(Color(hex: "0A0A0F"))
                .shadow(color: Color.white.opacity(0.04), radius: 10, y: 4)
        )
    }
    
    var emptyState: some View {
        VStack(spacing: 16) {
            Spacer()
            PentagonShape()
                .stroke(Color(hex: "6C63FF").opacity(0.3), lineWidth: 1)
                .frame(width: 60, height: 60)
            
            Text("CHƯA CÓ LỆNH NÀO")
                .font(.custom("Courier New", size: 13))
                .foregroundColor(Color.white.opacity(0.3))
                .tracking(2)
            
            Button(action: { showAddCommand = true }) {
                Text("+ THÊM LỆNH ĐẦU TIÊN")
                    .font(.custom("Courier New", size: 12))
                    .foregroundColor(Color(hex: "6C63FF"))
                    .tracking(1)
            }
            Spacer()
        }
    }
}

struct CommandRowView: View {
    let command: VoiceCommand
    let onToggle: () -> Void
    let onEdit: () -> Void
    
    var body: some View {
        HStack(spacing: 14) {
            // Icon
            ZStack {
                RoundedRectangle(cornerRadius: 10)
                    .fill(Color(hex: command.color).opacity(0.15))
                    .overlay(
                        RoundedRectangle(cornerRadius: 10)
                            .stroke(Color(hex: command.color).opacity(0.3), lineWidth: 1)
                    )
                Image(systemName: command.icon)
                    .font(.system(size: 16))
                    .foregroundColor(Color(hex: command.color))
            }
            .frame(width: 44, height: 44)
            .opacity(command.isEnabled ? 1 : 0.4)
            
            // Info
            VStack(alignment: .leading, spacing: 3) {
                Text(command.name)
                    .font(.custom("Courier New", size: 13))
                    .fontWeight(.bold)
                    .foregroundColor(command.isEnabled ? .white : Color.white.opacity(0.3))
                
                HStack(spacing: 4) {
                    Image(systemName: "quote.opening")
                        .font(.system(size: 9))
                    Text(command.trigger)
                        .font(.custom("Courier New", size: 10))
                    Image(systemName: "quote.closing")
                        .font(.system(size: 9))
                }
                .foregroundColor(Color(hex: "6C63FF").opacity(command.isEnabled ? 0.8 : 0.3))
                
                if !command.description.isEmpty {
                    Text(command.description)
                        .font(.custom("Courier New", size: 9))
                        .foregroundColor(Color.white.opacity(0.25))
                        .lineLimit(1)
                }
            }
            
            Spacer()
            
            // Actions
            HStack(spacing: 8) {
                Button(action: onEdit) {
                    Image(systemName: "pencil")
                        .font(.system(size: 12))
                        .foregroundColor(Color.white.opacity(0.3))
                        .frame(width: 28, height: 28)
                        .background(RoundedRectangle(cornerRadius: 6).fill(Color.white.opacity(0.04)))
                }
                
                Toggle("", isOn: Binding(
                    get: { command.isEnabled },
                    set: { _ in onToggle() }
                ))
                .toggleStyle(PentaToggleStyle())
                .labelsHidden()
            }
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color.white.opacity(command.isEnabled ? 0.04 : 0.02))
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(Color.white.opacity(command.isEnabled ? 0.08 : 0.04), lineWidth: 1)
                )
        )
    }
}

struct PentaToggleStyle: ToggleStyle {
    func makeBody(configuration: Configuration) -> some View {
        Button(action: { configuration.isOn.toggle() }) {
            RoundedRectangle(cornerRadius: 12)
                .fill(configuration.isOn ? Color(hex: "6C63FF") : Color.white.opacity(0.1))
                .frame(width: 40, height: 24)
                .overlay(
                    Circle()
                        .fill(.white)
                        .frame(width: 18, height: 18)
                        .offset(x: configuration.isOn ? 8 : -8)
                        .animation(.spring(response: 0.3, dampingFraction: 0.7), value: configuration.isOn)
                )
        }
        .buttonStyle(PlainButtonStyle())
    }
}

// MARK: - Command Editor
struct CommandEditorView: View {
    @ObservedObject var commandStore: CommandStore
    let command: VoiceCommand?
    @Environment(\.dismiss) var dismiss
    
    @State private var name = ""
    @State private var trigger = ""
    @State private var endpoint = ""
    @State private var description = ""
    @State private var selectedColor = "6C63FF"
    @State private var selectedIcon = "mic"
    
    let colors = ["6C63FF", "FF4444", "00FF88", "FFB800", "FF6B9D", "00BFFF", "FF8C00", "9B59B6"]
    let icons = ["mic", "pc", "power", "cpu", "lightbulb", "lightbulb.slash", "wifi", "bolt", "house", "lock", "camera", "speaker.wave.2", "fan", "snowflake", "thermometer", "info.circle"]
    
    var body: some View {
        ZStack {
            Color(hex: "0A0A0F").ignoresSafeArea()
            
            ScrollView {
                VStack(spacing: 20) {
                    // Header
                    HStack {
                        Text(command == nil ? "THÊM LỆNH" : "SỬA LỆNH")
                            .font(.custom("Courier New", size: 18))
                            .fontWeight(.bold)
                            .foregroundColor(.white)
                            .tracking(3)
                        Spacer()
                        Button(action: { dismiss() }) {
                            Image(systemName: "xmark")
                                .foregroundColor(Color.white.opacity(0.4))
                                .frame(width: 32, height: 32)
                                .background(Circle().fill(Color.white.opacity(0.06)))
                        }
                    }
                    
                    // Fields
                    editorField(label: "TÊN LỆNH", placeholder: "Bật PC", text: $name)
                    editorField(label: "TỪ KHOÁ KÍCH HOẠT", placeholder: "bật pc", text: $trigger,
                               hint: "Nói từ này để kích hoạt lệnh")
                    editorField(label: "API ENDPOINT", placeholder: "/api/turn-on-pc", text: $endpoint,
                               hint: "URL gửi đến Mac mini server")
                    editorField(label: "MÔ TẢ (tuỳ chọn)", placeholder: "Bật Windows PC qua relay", text: $description)
                    
                    // Color picker
                    VStack(alignment: .leading, spacing: 10) {
                        Text("MÀU SẮC")
                            .font(.custom("Courier New", size: 10))
                            .foregroundColor(Color(hex: "6C63FF"))
                            .tracking(2)
                        
                        HStack(spacing: 10) {
                            ForEach(colors, id: \.self) { color in
                                Button(action: { selectedColor = color }) {
                                    Circle()
                                        .fill(Color(hex: color))
                                        .frame(width: 30, height: 30)
                                        .overlay(
                                            Circle().stroke(Color.white, lineWidth: selectedColor == color ? 2 : 0)
                                        )
                                        .shadow(color: selectedColor == color ? Color(hex: color) : Color.clear, radius: 6)
                                }
                            }
                        }
                    }
                    
                    // Icon picker
                    VStack(alignment: .leading, spacing: 10) {
                        Text("BIỂU TƯỢNG")
                            .font(.custom("Courier New", size: 10))
                            .foregroundColor(Color(hex: "6C63FF"))
                            .tracking(2)
                        
                        LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 8), spacing: 10) {
                            ForEach(icons, id: \.self) { icon in
                                Button(action: { selectedIcon = icon }) {
                                    Image(systemName: icon)
                                        .font(.system(size: 16))
                                        .foregroundColor(selectedIcon == icon ? Color(hex: selectedColor) : Color.white.opacity(0.4))
                                        .frame(width: 36, height: 36)
                                        .background(
                                            RoundedRectangle(cornerRadius: 8)
                                                .fill(selectedIcon == icon ? Color(hex: selectedColor).opacity(0.15) : Color.white.opacity(0.04))
                                                .overlay(
                                                    RoundedRectangle(cornerRadius: 8)
                                                        .stroke(selectedIcon == icon ? Color(hex: selectedColor).opacity(0.4) : Color.clear, lineWidth: 1)
                                                )
                                        )
                                }
                            }
                        }
                    }
                    
                    // Save button
                    Button(action: saveCommand) {
                        Text(command == nil ? "TẠO LỆNH" : "CẬP NHẬT")
                            .font(.custom("Courier New", size: 13))
                            .fontWeight(.bold)
                            .tracking(3)
                            .foregroundColor(.white)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 14)
                            .background(
                                RoundedRectangle(cornerRadius: 12)
                                    .fill(
                                        name.isEmpty || trigger.isEmpty || endpoint.isEmpty
                                        ? LinearGradient(colors: [Color.gray.opacity(0.3), Color.gray.opacity(0.2)], startPoint: .leading, endPoint: .trailing)
                                        : LinearGradient(colors: [Color(hex: "6C63FF"), Color(hex: "8B5CF6")], startPoint: .leading, endPoint: .trailing)
                                    )
                            )
                    }
                    .disabled(name.isEmpty || trigger.isEmpty || endpoint.isEmpty)
                }
                .padding(20)
            }
        }
        .onAppear {
            if let command {
                name = command.name
                trigger = command.trigger
                endpoint = command.endpoint
                description = command.description
                selectedColor = command.color
                selectedIcon = command.icon
            }
        }
    }
    
    func editorField(label: String, placeholder: String, text: Binding<String>, hint: String? = nil) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label)
                .font(.custom("Courier New", size: 10))
                .foregroundColor(Color(hex: "6C63FF"))
                .tracking(2)
            
            TextField(placeholder, text: text)
                .font(.custom("Courier New", size: 13))
                .foregroundColor(.white)
                .autocorrectionDisabled()
                .autocapitalization(.none)
                .padding(12)
                .background(
                    RoundedRectangle(cornerRadius: 8)
                        .fill(Color.white.opacity(0.04))
                        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.1), lineWidth: 1))
                )
            
            if let hint {
                Text(hint)
                    .font(.custom("Courier New", size: 9))
                    .foregroundColor(Color.white.opacity(0.3))
            }
        }
    }
    
    func saveCommand() {
        var newCommand = VoiceCommand(
            name: name,
            trigger: trigger,
            endpoint: endpoint,
            icon: selectedIcon,
            color: selectedColor,
            isEnabled: true,
            description: description
        )
        
        if let existing = command {
            newCommand.id = existing.id
            commandStore.updateCommand(newCommand)
        } else {
            commandStore.addCommand(newCommand)
        }
        dismiss()
    }
}
