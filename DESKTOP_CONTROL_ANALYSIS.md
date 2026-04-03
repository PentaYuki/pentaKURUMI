# 🖥️ PHÂN TÍCH CHỨC NĂNG ĐIỀU KHIỂN DESKTOP - PentaMiv1

## 📋 TỔNG QUAN HỆ THỐNG

Dự án PentaMiv1 là một hệ thống AI assistant đa nền tảng với khả năng điều khiển desktop từ xa thông qua voice commands. Hệ thống hoạt động theo kiến trúc **3-tier**:

```
┌─────────────────────────────────────────────────────────────────┐
│                     PentaCommand (iOS/macOS)                    │
│                         Swift App Client                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP/WebSocket
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PentaAI_Mac (Mac Mini)                       │
│                  FastAPI Server + AI Engine                     │
│              • Ollama LLM Command Interpreter                  │
│              • Action Executor + Web Actions                   │
│              • TTS Engine (Valtec/VoiceVox/Edge)               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP/Tailscale/Cloudflare
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  PentakuruV4 (Windows PC)                       │
│                Flask Server + PS Executor                       │
│              • PowerShell Command Execution                    │
│              • AI Actuator (Demo Recording/Playback)           │
│              • Screen Change Detection                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🏗️ KIẾN TRÚC ĐIỀU KHIỂN DESKTOP

### 1. **Command Flow (Luồng lệnh)**

```
User Voice Input
       │
       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  PentaCommand   │───▶│  PentaAI_Mac    │───▶│  PentakuruV4    │
│  (iOS Client)   │    │  (AI Server)    │    │  (Win Executor) │
└─────────────────┘    └─────────────────┘    └─────────────────┘
       │                       │                       │
       │ WebSocket/HTTP        │ HTTP                  │ PowerShell
       │                       │                       │
       ▼                       ▼                       ▼
   Voice Input            NLP Processing         Desktop Control
   TTS Output             Command Parsing        App Launching
   UI Updates             Action Dispatch        System Automation
```

### 2. **Các Thành Phần Chính**

#### **A. PentaAI_Mac (Mac Mini Server)**

**Vai trò:** Trung tâm xử lý AI và phân tích lệnh

**Thành phần cốt lõi:**

1. **OllamaCommandInterpreter** (`ollama_command.py`)
   - Phân tích ngôn ngữ tự nhiên thành cấu trúc lệnh
   - Hỗ trợ 3-tier fallback:
     - **Tier 1:** Rule-based parsing (không cần AI)
     - **Tier 2:** Local Ollama (llama3.2:1b)
     - **Tier 3:** Cloud API (OpenAI-compatible)
   - Circuit Breaker pattern cho cloud fallback
   - Xử lý filler words từ voice recognition

2. **ActionExecutor** (`core/action_executor.py`)
   - Thực thi các hành động đã được parse
   - Hỗ trợ 7 loại action:
     - `open` → Mở URL/ứng dụng
     - `search` → Tìm kiếm trên platforms
     - `play` → Phát nhạc/video YouTube
     - `run` → Chạy ứng dụng macOS
     - `fetch` → Tải nội dung web (Phase 4)
     - `setup` → Điều khiển hệ thống (Phase 5)
     - `penta` → Quick-link từ PentaKuruV4

3. **WebActions** (`core/web_actions.py`)
   - Thực hiện các hành động web trực tiếp
   - Hỗ trợ 9 search engines: YouTube, Google, Bing, Wikipedia, GitHub, npm, Facebook, Instagram, TikTok
   - Mở URL, tìm kiếm, mở ứng dụng macOS
   - Sử dụng `webbrowser` module (cross-platform)

4. **FastAPI Server** (`ai_server.py`)
   - REST API endpoints cho chat, commands, health
   - WebSocket support cho real-time communication
   - TTS integration (Valtec/VoiceVox/Edge)
   - Hormone system cho emotional AI
   - Proactive engine cho contextual care

#### **B. PentakuruV4 (Windows PC Server)**

**Vai trò:** Thực thi lệnh trên Windows PC

**Thành phần cốt lõi:**

1. **Flask Server** (`pentaKuruV4.py`)
   - HTTP server nhận lệnh từ Mac Mini
   - Authentication qua Bearer token
   - Support Tailscale và Cloudflare tunnel
   - Demo mode với whitelist an toàn

2. **PSExecutor** (`pentaKuruV4.py`)
   - Thực thi PowerShell commands an toàn
   - Hỗ trợ 2 modes:
     - `run(cmd)` - Lệnh đơn
     - `run_script(script)` - Script nhiều dòng
   - Timeout protection (120s)
   - UTF-8 BOM encoding cho tiếng Việt

3. **AI Actuator** (`ai_actuator.py`)
   - Demo recording với intelligent detection
   - Screen change detection (SSIM + pixel-based)
   - Smart waiting cho adaptive execution
   - Double click detection
   - Context-aware playback

#### **C. PentaCommand (iOS/macOS Client)**

**Vai trò:** Giao diện người dùng và voice interaction

**Thành phần cốt lõi:**

1. **NetworkManager** (`NetworkManager.swift`)
   - HTTP/WebSocket communication với AI server
   - Audio streaming (WAV + compressed)
   - Bluetooth audio support
   - Health monitoring với ping loop

2. **Voice Engine**
   - Speech recognition
   - TTS playback
   - Audio session management

3. **UI Components**
   - Floating pentagon widget
   - Command list view
   - Settings view
   - Voice visualization

---

## 🔄 LUỒNG XỬ LÝ CHI TIẾT

### **Scenario 1: Voice Command "Mở YouTube"**

```
1. PentaCommand (iOS)
   └─> Speech Recognition: "mở youtube"
   └─> HTTP POST /api/chat hoặc WebSocket
   └─> Payload: {"text": "mở youtube", "tts": true, "speaker": "NF"}

2. PentaAI_Mac (Mac Mini)
   └─> OllamaCommandInterpreter.interpret("mở youtube")
       ├─> Tier 1: Rule-based parsing
       │   └─> Match "mở" + "youtube"
       │   └─> Return: {"action": "open", "target": "https://youtube.com", "query": ""}
       │
       └─> ActionExecutor.execute({"action": "open", "target": "https://youtube.com"})
           └─> WebActions.open_url("https://youtube.com")
               └─> webbrowser.open(url) → Mở Safari/Chrome trên Mac Mini
   └─> TTS Response: "Đã mở YouTube"
   └─> WebSocket/HTTP response về iOS

3. PentaCommand (iOS)
   └─> Display response text
   └─> Play TTS audio
   └─> Update UI
```

### **Scenario 2: PC Command "Chạy Notepad trên PC"**

```
1. PentaCommand (iOS)
   └─> Speech Recognition: "chạy notepad trên pc"
   └─> HTTP POST /api/execute_pc_command

2. PentaAI_Mac (Mac Mini)
   └─> OllamaCommandInterpreter.interpret("chạy notepad trên pc")
       └─> Return: {"action": "run", "target": "Notepad", "query": ""}
   └─> _map_ollama_to_windows_payload()
       └─> Return: {"cmd": "Start-Process \"Notepad\"", "script": ""}
   └─> send_to_windows(cmd="Start-Process \"Notepad\"")
       └─> HTTP POST http://[PC_IP]:7777/run
       └─> Headers: Authorization: Bearer [token]
       └─> Body: {"cmd": "Start-Process \"Notepad\""}

3. PentakuruV4 (Windows PC)
   └─> FlaskServerThread nhận request
   └─> _check_token() xác thực
   └─> PSExecutor.run("Start-Process \"Notepad\"")
       └─> subprocess.run(["powershell.exe", "-Command", "Start-Process \"Notepad\""])
   └─> Return: {"ok": true, "stdout": "", "stderr": "", "exit_code": 0}

4. PentaAI_Mac (Mac Mini)
   └─> Return result to iOS

5. PentaCommand (iOS)
   └─> Display result
   └─> TTS: "Đã mở Notepad"
```

### **Scenario 3: Complex Script "Dọn rác PC"**

```
1. PentaCommand (iOS)
   └─> Speech Recognition: "dọn rác pc"
   └─> HTTP POST /api/execute_pc_command

2. PentaAI_Mac (Mac Mini)
   └─> OllamaCommandInterpreter.interpret("dọn rác pc")
       └─> Ollama LLM generates PowerShell script
       └─> Return: {"action": "ps_script", "target": "Cleanup", 
                    "query": "Remove-Item -Path $env:TEMP\\* -Recurse -Force"}
   └─> _map_ollama_to_windows_payload()
       └─> Return: {"cmd": "", "script": "Remove-Item -Path $env:TEMP\\* -Recurse -Force"}
   └─> send_to_windows(script="Remove-Item -Path $env:TEMP\\* -Recurse -Force")

3. PentakuruV4 (Windows PC)
   └─> PSExecutor.run_script(script)
       └─> Write script to temp .ps1 file
       └─> Execute with PowerShell
       └─> Delete temp file
   └─> Return execution result

4. Response chain back to iOS
```

---

## 🎯 CÁC CHỨC NĂNG ĐIỀU KHIỂN DESKTOP

### **1. Application Control (Điều khiển ứng dụng)**

| Command | Action | Implementation |
|---------|--------|----------------|
| "Mở Safari" | `run` | `webbrowser.open()` hoặc `open -a Safari` |
| "Mở Notepad" | `run` | `Start-Process "Notepad"` (Windows) |
| "Mở Chrome" | `run` | `Start-Process "chrome"` (Windows) |
| "Chạy Calculator" | `run` | `Start-Process "calc"` (Windows) |

### **2. Web Browsing (Duyệt web)**

| Command | Action | Implementation |
|---------|--------|----------------|
| "Mở YouTube" | `open` | `webbrowser.open("https://youtube.com")` |
| "Mở Google" | `open` | `webbrowser.open("https://google.com")` |
| "Truy cập Facebook" | `open` | `webbrowser.open("https://facebook.com")` |

### **3. Search (Tìm kiếm)**

| Command | Action | Platform |
|---------|--------|----------|
| "Tìm mèo trên YouTube" | `search` | YouTube |
| "Tìm kiếm Python tutorial" | `search` | Google (default) |
| "Tìm nhạc lofi trên Spotify" | `search` | Spotify |
| "Tra cứu Wikipedia AI" | `search` | Wikipedia |

### **4. Media Control (Điều khiển media)**

| Command | Action | Implementation |
|---------|--------|----------------|
| "Phát nhạc jazz" | `play` | YouTube search |
| "Bật video cooking" | `play` | YouTube search |
| "Nghe nhạc lofi" | `play` | YouTube search |

### **5. System Control (Điều khiển hệ thống)**

| Command | Action | Implementation |
|---------|--------|----------------|
| "Tắt âm thanh" | `setup` | `Set-AudioDevice -Mute` |
| "Điều chỉnh volume 50%" | `setup` | `Set-AudioDevice -Volume 50` |
| "Khởi động lại PC" | `setup` | `Restart-Computer` |

### **6. Quick Links (PentaKuru Sectors)**

| Command | Action | Implementation |
|---------|--------|----------------|
| "Mở link số 1" | `penta` | Load sector 1 from sectors.json |
| "Chạy sector YouTube" | `penta` | Match sector by name |

### **7. PowerShell Automation**

| Command | Action | Implementation |
|---------|--------|----------------|
| "Dọn rác PC" | `ps_script` | `Remove-Item $env:TEMP\* -Recurse` |
| "Tạo file test" | `ps_script` | `New-Item -Path "C:\test.txt"` |
| "Cài đặt phần mềm" | `install` | `winget install [package]` |

---

## 🛡️ BẢO MẬT VÀ AN TOÀN

### **1. Authentication**

- **Token-based:** Bearer token cho tất cả API calls
- **Tailscale:** Secure tunnel giữa Mac Mini và Windows PC
- **Cloudflare:** Optional tunnel cho remote access

### **2. Execution Safety**

- **Demo Mode:** Whitelist các lệnh an toàn
- **Timeout Protection:** 120s timeout cho PowerShell
- **Input Validation:** Sanitize commands trước khi thực thi
- **Error Handling:** Graceful fallback khi lệnh thất bại

### **3. Circuit Breaker Pattern**

```python
# Ollama cloud fallback
if self._cb_fails >= self._cb_max_fails:
    self._cb_open_until = time.monotonic() + self._cb_reset_sec
    # Block cloud calls for 60s after 3 consecutive failures
```

### **4. Network Security**

- **HTTPS/WSS:** Encrypted communication
- **Token Rotation:** Configurable auth tokens
- **IP Whitelist:** Tailscale/IP-based access control

---

## 📊 PERFORMANCE OPTIMIZATION

### **1. Tiered Command Parsing**

```
Tier 1: Rule-based (0-5ms)
  └─> Direct keyword matching
  └─> No AI overhead
  └─> 80% of common commands

Tier 2: Local Ollama (100-500ms)
  └─> llama3.2:1b model
  └─> Low latency
  └─> 15% of complex commands

Tier 3: Cloud API (500-2000ms)
  └─> GPT-4o-mini or similar
  └─> High accuracy
  └─> 5% of complex commands
```

### **2. Audio Streaming**

- **WAV Streaming:** Real-time audio chunks
- **Compressed Audio:** MP3 queue for efficiency
- **Bluetooth Support:** Automatic device switching

### **3. Screen Change Detection**

```python
# Multi-strategy detection
strategies = [
    _pixel_change_detection,      # Fast, 50% weight
    _structural_similarity_detection,  # Accurate, 30% weight
    _contour_based_detection      # Robust, 20% weight
]
```

---

## 🔧 CONFIGURATION

### **Key Configuration Files**

1. **config.json** (PentaAI_Mac)
   ```json
   {
     "auth_token": "12345abcde",
     "ollama_url": "http://localhost:11434",
     "ollama_model": "qwen3.5:cloud",
     "ollama_command_cloud_policy": "complex_only",
     "pc_tailscale_ip": "100.x.x.x",
     "pc_api_port": 7777
   }
   ```

2. **server.json** (PentakuruV4)
   ```json
   {
     "port": 7777,
     "auth_token": "...",
     "use_tailscale": true,
     "use_cloudflare": false,
     "execution_mode": "full"
   }
   ```

3. **sectors.json** (Quick Links)
   ```json
   {
     "1": {"name": "YouTube", "url": "https://youtube.com"},
     "2": {"name": "Notepad", "exe_path": "notepad.exe"}
   }
   ```

---

## 🚀 DEPLOYMENT ARCHITECTURE

### **Network Topology**

```
┌─────────────────────────────────────────────────────────┐
│                    Internet                              │
└─────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │   Cloudflare      │
                    │   Tunnel (opt)    │
                    └─────────┬─────────┘
                              │
┌─────────────────────────────┼─────────────────────────────┐
│                    Tailscale Network                      │
│  ┌───────────────┐    ┌───────────────┐    ┌───────────┐ │
│  │  iPhone/iPad  │    │   Mac Mini    │    │ Windows PC│ │
│  │ PentaCommand  │◄──►│ PentaAI_Mac   │◄──►│PentakuruV4│ │
│  │  100.x.x.1    │    │  100.x.x.2    │    │ 100.x.x.3 │ │
│  └───────────────┘    └───────────────┘    └───────────┘ │
└─────────────────────────────────────────────────────────┘
```

### **Service Ports**

| Service | Port | Protocol |
|---------|------|----------|
| PentaAI_Mac | 9090 | HTTP/WebSocket |
| PentakuruV4 | 7777 | HTTP |
| Ollama | 11434 | HTTP |
| Tailscale | 41641 | UDP |

---

## 📈 FUTURE ENHANCEMENTS

### **Phase 4: Web Content Fetching**
- Extract content from web pages
- Summarize articles
- Parse structured data

### **Phase 5: Advanced System Control**
- File management automation
- Process monitoring
- System diagnostics
- Multi-monitor support

### **Phase 6: AI-Powered Automation**
- Learn user patterns
- Suggest automations
- Context-aware actions
- Predictive commands

---

## 🎯 CONCLUSION

Hệ thống điều khiển desktop PentaMiv1 cung cấp một giải pháp toàn diện cho voice-controlled desktop automation với:

✅ **3-tier architecture** đảm bảo scalability và reliability  
✅ **Multi-platform support** (macOS + Windows)  
✅ **Intelligent command parsing** với AI fallback  
✅ **Secure communication** qua Tailscale/Cloudflare  
✅ **Real-time audio streaming** với TTS integration  
✅ **Demo recording/playback** cho automation  
✅ **Extensible design** cho future enhancements  

Hệ thống sẵn sàng cho production deployment và có thể mở rộng cho nhiều use cases khác nhau.