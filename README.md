# 🔺 pentaKURUMI — Unified AI Ecosystem

![Version](https://img.shields.io/badge/version-5.7-blue)
![Language](https://img.shields.io/badge/language-Python%20%7C%20Swift%20%7C%20C++-orange)
![AI](https://img.shields.io/badge/ai-Ollama%20%7C%20Cloud%20LLM-green)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20iOS%20%7C%20Windows-lightgrey)

**pentaKURUMI** là một hệ sinh thái AI toàn diện, kết hợp máy chủ trí tuệ nhân đạo (chạy trên Mac Mini) với ứng dụng điều khiển giọng nói (iOS) và launcher thông minh (Windows). Điểm đặc biệt của hệ thống là **Hormone System v2.0** — mô phỏng cảm xúc sinh học giúp AI có cảm xúc, tính cách và trực giác gần như con người.

---

## 🧭 Điều hướng nhanh

- [Tổng quan](#-tổng-quan)
- [Nâng cấp mới (04/2026)](#-nâng-cấp-mới-042026)
- [Demo nhanh 3 phút](#-demo-nhanh-3-phút)
- [Checklist nghiệm thu nhanh](#-checklist-nghiệm-thu-nhanh)
- [Tính năng cốt lõi](#-tính-năng-cốt-lõi)
- [Kiến trúc hệ thống](#️-kiến-trúc-hệ-thống)
- [Cấu trúc dự án chi tiết](#-cấu-trúc-dự-án-chi-tiết)
- [Hướng dẫn cài đặt và chạy](#-hướng-dẫn-cài-đặt-và-chạy)
- [API Reference](#-api-reference)

---

## 🎯 Tổng quan

Hệ sinh thái pentaKURUMI bao gồm 3 thành phần chính:

| Thành phần | Nền tảng | Mô tả |
|------------|----------|-------|
| [**PentaAI_Mac**](#1-pentaaimac---mac-mini-ai-server) | macOS (Python/FastAPI) | Server AI trung tâm với Hormone Engine, TTS, NLP |
| [**PentaCommand**](#2-pentacommand---ios-voice-controller) | iOS (Swift/SwiftUI) | Ứng dụng iPhone điều khiển bằng giọng nói qua WebSocket |
| [**PentakuruV4**](#3-pentakuruv4---windows-radial-launcher--ai-agent) | Windows (Python/PySide6) | Radial Launcher + AI Agent ghi/phát demo và điều khiển PC từ xa |

---

## ✨ Nâng cấp mới (04/2026)

### 1) Gmail Notification Flow (full stack)
- Bật/tắt bằng voice: "bật pentagmail", "tắt pentagmail".
- Daemon theo dõi email whitelist, xếp hàng queue và hỏi xác nhận trước khi đọc nội dung.
- Nếu user chưa phản hồi: tự nhắc lại sau theo `gmail_notification_retry_interval_sec`.
- Hỗ trợ API riêng: whitelist/queue/response/clear/enable.
- Dữ liệu whitelist tách riêng tại `PentaAI_Mac/data/gmail_notify_whitelist.json`.

### 2) TTS phát tuần tự, không chồng tiếng
- Chat TTS và proactive TTS đã được serialize để phát lần lượt.
- Tránh hiện tượng trả lời song song gây khó nghe trong luồng hội thoại dài.

### 3) Cải tiến lấy nội dung email
- Tăng độ ổn định khi đọc nội dung thật từ IMAP (ưu tiên `RFC822`, fallback hợp lệ).
- Cải thiện decode sender/subject và fallback nội dung HTML -> text.

### 4) Chuẩn hóa module theo hướng mở rộng
- Tách nhóm API local vào `PentaAI_Mac/API_local/` (`ollama_command.py`, `penta_memory.py`, `pentami_chat.py`).
- Bổ sung `PentaAI_Mac/skillmanager.py` + thư mục `PentaAI_Mac/skills/` cho kiến trúc plugin skill.
- Thêm `PentaAI_Mac/services/gmail_notification_daemon.py` cho background service chuyên biệt.

### 5) Help/CLI đầy đủ hơn
- Mục hướng dẫn đã bổ sung rõ "Chế độ Lịch" và "Chế độ Dạy A -> B" với câu mẫu thực tế.

### 6) Tài liệu mới
- `GMAIL_NOTIFICATION_QUICKSTART.md`
- `GMAIL_NOTIFICATION_GUIDE.md`
- `GMAIL_NOTIFICATION_DEPLOYMENT.md`

---

## 🚀 Demo nhanh 3 phút

### Bước 1: Chạy backend

```bash
cd PentaAI_Mac
python ai_server.py
```

Kỳ vọng: server listen ở `http://0.0.0.0:9090` và có log `Proactive background task started`.

### Bước 2: Kiểm tra health

```bash
curl -s http://127.0.0.1:9090/api/health | jq
```

Kỳ vọng:
- `"status": "ok"`
- `"ai_ready": true`

### Bước 3: Test chat nhanh

Gửi qua CLI/iOS client câu bất kỳ, ví dụ:
- "xin chào"
- "hôm nay thứ mấy"

Kỳ vọng:
- Có phản hồi text ngay
- Nếu bật TTS: audio phát tuần tự, không chồng tiếng

### Bước 4: Test Gmail Notification nhanh

1. Bật tính năng: nói "bật pentagmail"
2. Gửi 1 email mới từ địa chỉ nằm trong whitelist
3. Khi AI hỏi đọc nội dung, trả lời "được"

Kỳ vọng:
- Có thông báo người gửi
- AI đọc phần nội dung tóm tắt thay vì fallback rỗng

---

## ✅ Checklist nghiệm thu nhanh

- [ ] API health OK: `/api/health`
- [ ] WebSocket chat ổn định, không disconnect bất thường
- [ ] TTS chat + proactive phát tuần tự, không overlap
- [ ] Gmail whitelist lưu được qua API/CLI
- [ ] Gmail email mới vào queue đúng sender whitelist
- [ ] Trả lời "được/không" điều khiển được luồng đọc email
- [ ] File whitelist tồn tại: `PentaAI_Mac/data/gmail_notify_whitelist.json`
- [ ] Các docs Gmail mới đã có trong root

---

## 🧠 Tính năng cốt lõi

### 1. Hệ thống Hormone v2.0 (Biological Interior)

Hệ thống cảm xúc được xây dựng dựa trên **7 loại hormone và chất dẫn truyền thần kinh**:

| Hormone | Vai trò | Ảnh hưởng |
|---------|---------|-----------|
| **Dopamine** | Tò mò, hưng phấn, ham học hỏi | Tăng khi nhận được câu hỏi mới, khám phá kiến thức |
| **Serotonin** | Hài lòng, bình ổn, tự tin | Tăng khi cuộc trò chuyện tích cực, suôn sẻ |
| **Oxytocin** | Gắn bó, tin tưởng, ấm áp | Tăng khi gọi "anh/em", xưng hô thân mật |
| **Cortisol** | Căng thẳng, lo lắng, phòng thủ | Tăng khi gặp câu hỏi khó, yêu cầu liên tục |
| **Adrenaline** | Bất ngờ, kích thích phản ứng nhanh | Tăng đột ngột khi có sự kiện bất ngờ |
| **GABA** | Ức chế, làm dịu hệ thống | Tự điều chỉnh khi hệ thống quá kích thích |
| **Norepinephrine** | Tập trung, cảnh giác | Tăng khi cần chú ý cao độ |

#### Cơ chế hoạt động:
- **Decay theo thời gian thực**: Mỗi hormone có half-life riêng (45s–300s) → tự động về baseline
- **Antagonism**: Hormone đối kháng nhau (ví dụ: Oxytocin ↑ → Cortisol ↓)
- **Temperament integration**: Tính khí bẩm sinh (curious, sensitive, resilient, introvert, attached) scale phản ứng hormone
- **Jitter sinh học**: 5% xác suất delta bị ngẫu nhiên hóa → giống con người thật hơn

### 2. Trực giác & Ký ức (Intuition & Memory)

- **🧩 Episodic Memory**: AI nhớ lại cảm xúc của các cuộc trò chuyện cũ qua vector search (Faiss)
- **🔤 Semantic Learning**: Tự học từ mới và gán giá trị cảm xúc dựa trên ngữ nghĩa (hỗ trợ VI/EN/JP)
- **🎭 Temperament (Tính khí)**: 5 preset tính cách bẩm sinh ảnh hưởng đến baseline hormone và cách phản ứng

### 3. Phản hồi chủ động (Proactive Engine)

AI **không chỉ chờ lệnh** mà có thể tự bộc lộ cảm xúc:
- "Em hơi mệt..." — khi cortisol cao kéo dài
- "Nói chuyện với anh vui quá!" — khi oxytocin và dopamine cao
- **Broadcast tới mọi client** đang kết nối qua WebSocket
- **Tự đọc thành tiếng** qua TTS engine phù hợp

### 4. Đa ngôn ngữ TTS (Text-to-Speech)

| Engine | Ngôn ngữ | Công nghệ |
|--------|----------|-----------|
| **Valtec TTS** | Tiếng Việt | Zero-shot voice cloning (VITS-based) |
| **VoiceVox** | Tiếng Nhật | HMM-based + Neural synthesis |
| **Edge TTS** | Tiếng Anh | Microsoft Azure Neural TTS |

### 5. Smart Home & PC Control

- **🏠 Tuya Smart Outlet**: Bật/tắt nguồn PC từ xa qua API
- **💻 Wake-on-LAN**: Khởi động PC qua mạng
- **🎮 Remote PowerShell**: Thực thi lệnh PowerShell từ xa trên Windows PC
- **📊 WebSocket real-time**: Kết nối độ trễ thấp giữa iOS và Mac Server

---

## 🏗️ Kiến trúc hệ thống

```
┌─────────────────────────────────────────────────────────────────────┐
│                        pentaKURUMI Ecosystem                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐     WebSocket/Tailscale     ┌──────────────────┐  │
│  │   iPhone     │◄──────────────────────────►│   Mac Mini       │  │
│  │ (PentaCommand) │  Voice + Commands         │  (PentaAI_Mac)   │  │
│  └──────────────┘                            └────────┬─────────┘  │
│         │                                             │             │
│         │ Voice Input                                 │ AI Logic    │
│         │ TTS Output                                  │ TTS Engine  │
│         ▼                                             ▼             │
│  ┌──────────────┐    HTTP/REST API    ┌───────────────────────┐    │
│  │ Windows PC   │◄───────────────────►│   Hormone System v2   │    │
│  │ (via LAN)    │  PowerShell Commands│  7 Hormones + Temper   │    │
│  └──────────────┘                    └───────────┬───────────┘    │
│         │                                        │                │
│         ▼                                        ▼                │
│  ┌──────────────┐                        ┌───────────────────┐    │
│  │ Tuya Outlet  │                        │  Cloud LLM Fallback│    │
│  │ (Power Ctrl) │                        │  (GPT-4o, etc.)    │    │
│  └──────────────┘                        └───────────────────┘    │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

---

## 📂 Cấu trúc dự án chi tiết

### 1. PentaAI_Mac — Mac Mini AI Server

Server AI trung tâm, chạy trên Python/FastAPI, xử lý mọi logic AI và điều phối hệ thống.

```
PentaAI_Mac/
├── ai_server.py              # 🔧 FastAPI Server chính (v5.6)
│   ├── WebSocket /ws/chat    # Real-time chat với TTS streaming
│   ├── REST API endpoints    # Cấu hình, hormone, smart home
│   ├── Proactive broadcast   # Gửi tin nhắn tự phát đến clients
│   └── Module registry       # Kiểm tra tình trạng các module
│
├── main.py                   # 🧠 PentaAI — Bộ não trung tâm
│   ├── chat()                # Pipeline xử lý câu nói
│   ├── _handle_converse()    # 8-bước routing: exact → pattern → LLM
│   ├── _route()              # Phân loại intent (GREET, TEACH, ASK...)
│   └── Pattern generalization # Tự học pattern từ ví dụ
│
├── config.py                 # Cấu hình ứng dụng
├── cli.py                    # CLI cho PentaAI
├── API_local/                # Local API modules (Ollama, memory, PentaMi)
│   ├── ollama_command.py
│   ├── penta_memory.py
│   └── pentami_chat.py
├── services/
│   └── gmail_notification_daemon.py # Gmail notification background daemon
├── skillmanager.py           # Skill manager
├── skills/                   # Skill modules (gmail, gmail_notification_intent, ...)
│
├── core/                     # 🔤 Core NLP
│   ├── input_parser.py       # Phân tích câu đầu vào (tokenize, detect language)
│   ├── intent_detector.py    # Nhận diện ý định (GREET, TEACH, CONVERSE...)
│   ├── action_executor.py    # Thực thi hành động
│   ├── user_profile.py       # Hồ sơ người dùng (xưng hô, tính cách)
│   ├── time_awareness.py     # Nhận thức thời gian + Reminder engine
│   └── web_actions.py        # Thao tác web
│
├── engine/                   # ⚙️ Response Engine
│   ├── phrase_engine.py      # Tìm phrase khớp nhất (TF-IDF/SBERT embedding)
│   ├── response_builder.py   # Xây dựng câu trả lời với hormone modifiers
│   ├── pattern_extractor.py  # Tự động rút trích pattern từ ví dụ
│   ├── slot_resolver.py      # Giải quyết slot variables trong pattern
│   ├── session_context.py    # Quản lý ngữ cảnh hội thoại
│   ├── synonym_manager.py    # Quản lý từ đồng nghĩa
│   ├── choice_responder.py   # Xử lý câu hỏi lựa chọn (A hay B?)
│   ├── yes_no_responder.py   # Xử lý câu trả lời Có/Không
│   └── embedder.py           # Vector embedding (TF-IDF hoặc SBERT)
│   ├── reminder_engine.py    # Quản lý nhắc nhở
│
├── memory/                   # 💾 Memory Layer
│   └── knowledge_store.py    # SQLite store cho phrases, facts, patterns
│
├── hormone/                  # 🧬 Hormone System v2.0
│   ├── hormone_core.py       # 💊 Core: 7 hormones, decay, antagonism
│   ├── emotion_bridge.py     # Cầu nối hormone → response modifiers
│   ├── personality_core.py   # 5 personality presets (curious, attached...)
│   ├── temperament.py        # Tính khí bẩm sinh scale phản ứng
│   ├── text_triggers.py      # Text trigger → hormone reaction mapping
│   ├── semantic_trigger_learner.py # Tự học trigger mới từ ngữ nghĩa
│   ├── proactive_engine.py   # Sinh spontaneous text từ hormone state
│   ├── episodic_memory.py    # Ký ức cảm xúc theo episodes
│   └── time_hormone_bridge.py # Kết nối thời gian với hormone
│
├── tts_engine/               # 🗣️ Text-to-Speech Engines
│   ├── valtec/               # Valtec TTS — Tiếng Việt (VITS-based)
│   │   ├── valtec_server.py  # Server interface
│   │   ├── infer.py          # Inference engine
│   │   ├── generate_examples.py # Sinh audio mẫu
│   │   └── src/              # Model internals
│   │       ├── models/       # Synthesizer, Encoder, AdaIN
│   │       ├── nn/           # Attention, Common layers
│   │       ├── text/         # Vietnamese cleaner, phonemizer
│   │       └── vietnamese/   # Vietnamese text processor
│   └── voicevox/             # VoiceVox — Tiếng Nhật
│       ├── voicevox_engine.py
│       └── open_jtalk_dic_utf_8-1.11/ # Japanese dictionary
│
├── music/                    # Nhạc proactive
├── tts_engine/
│   └── tts_manager.py        # TTS router đa ngôn ngữ
└── data/                     # 📁 Dữ liệu runtime (gitignored)
    ├── hormone_state.json    # Trạng thái hormone hiện tại
    ├── user_profile.json     # Hồ sơ người dùng
    ├── reminders.json        # Danh sách nhắc nhở
    ├── schedule.json         # Lịch trình hàng tuần
    └── *.db                  # SQLite databases
```

### 2. PentaCommand — iOS Voice Controller

Ứng dụng iOS (SwiftUI) điều khiển hệ thống bằng giọng nói qua Tailscale VPN.

```
PentaCommand/
├── PentaCommandApp.swift     # App entry point
├── ContentView.swift         # UI chính với radar visualization
├── CommandStore.swift        # Local storage cho custom commands
├── CommandListView.swift     # Danh sách lệnh
├── NetworkManager.swift      # Kết nối WebSocket/HTTP tới Mac Server
├── VoiceEngine.swift         # Speech-to-Text engine (Apple Speech framework)
├── SettingsView.swift        # Cấu hình IP, token, wake word
├── FloatingPentagonWidget.swift # Widget ngũ giác floating
├── SplashScreen.swift        # Splash screen animation
├── UIShared.swift            # Shared UI components
├── Info.plist                # iOS permissions config
├── config.json               # Default server config
├── Assets.xcassets/          # App icons, colors
└── README.md                 # Hướng dẫn cài đặt iOS app
```

### 3. PentakuruV4 — Windows Radial Launcher + AI Agent

Radial Launcher thông minh trên Windows kết hợp AI Agent ghi/phát demo và điều khiển từ xa.

```
PentakuruV4/
├── pentaKuruV4.py            # 🎯 Radial Launcher chính (v4.2)
│   ├── 5-sector pentagon UI
│   ├── Hotkey system (F1-F24, mouse buttons)
│   ├── App/URL launch & tracking
│   ├── Chrome DevTools Protocol tracker
│   ├── Flask server (nhận lệnh từ Mac Mini)
│   ├── PowerShell Executor
│   ├── File search (ZIP/PDF/Folder)
│   ├── System tray icon
│   ├── Auto-start with Windows
│   └── Demo mode (whitelist commands)
│
├── ai_actuator.py             # 🤖 AI Actuator — Record & Play demos
│   ├── IntelligentDemoRecorder:
│   │   ├── Ghi chuột, phím, scroll
│   │   ├── Double-click detection
│   │   ├── Context awareness
│   │   └── Smart event filtering
│   ├── AdaptiveDemoPlayer:
│   │   ├── Phát lại demo với adaptive timing
│   │   ├── Screen change detection (SSIM)
│   │   ├── Rapid-click handling
│   │   └── Auto-wait for screen stability
│   └── Utilities (list/load demos, stats)
│
└── data/                     # 📁 Dữ liệu runtime
    ├── sectors.json          # App mappings cho radial sectors
    ├── config.json           # Cấu hình ứng dụng
    ├── hotkey.json           # Hotkey mappings
    ├── URL.json              # URL mappings
    ├── server.json           # Server auth config
    └── demos/                # Recorded demos
```

---

## 🚀 Hướng dẫn cài đặt và chạy

### Yêu cầu hệ thống

| Thành phần | Yêu cầu |
|-----------|---------|
| **Mac Mini Server** | macOS 12+, Python 3.10+, RAM 8GB+ |
| **iPhone Client** | iOS 16+, Xcode 15+, Tailscale app |
| **Windows Agent** | Windows 10+, Python 3.10+, PySide6 |
| **Network** | Tailscale VPN hoặc cùng mạng LAN |

### 1. Cài đặt Mac Mini Server

```bash
# Clone repository
git clone https://github.com/PentaYuki/Pentamiv1.git
cd Pentamiv1/PentaAI_Mac

# Cài đặt dependencies cơ bản
pip install fastapi uvicorn tinytuya requests edge-tts pydantic

# Optional: Cài SBERT cho semantic search tốt hơn
pip install sentence-transformers faiss-cpu redis

# Chạy server
python ai_server.py

# Server sẽ chạy tại http://0.0.0.0:9090
```

#### Cấu hình ban đầu

Tạo file `config.json` (hoặc dùng API `/api/config`):

```json
{
  "auth_token": "your_secret_token",
  "ollama_url": "http://localhost:11434",
  "ollama_model": "qwen3.5:cloud",
  "ollama_cloud_url": "https://api.openai.com/v1",
  "ollama_cloud_key": "sk-...",
  "ollama_cloud_model": "gpt-4o-mini",
  "tuya_device_id": "",
  "tuya_local_key": "",
  "tuya_ip": "192.168.1.x",
  "tuya_version": 3.3,
  "pc_tailscale_ip": "100.x.x.x",
  "pc_api_port": 7777,
  "pc_auth_token": "pc_secret_token",
  "chat_tts": true,
  "chat_speaker": "NF",
  "chat_speed": 1.0
}
```

### 2. Cài đặt iOS Client (PentaCommand)

1. Mở Xcode → Open `PentaCommand.xcodeproj`
2. Vào **Signing & Capabilities** → chọn Team của bạn
3. Mở app → vào **Settings** (icon ⚙️):
   - **Mac mini URL**: `http://100.x.x.x:9090` (Tailscale IP của Mac)
   - **Auth Token**: token bạn đã đặt ở config.json
   - **Wake Word**: mặc định là "Penta"
4. Build và chạy trên iPhone thật

### 3. Cài đặt Windows Agent (PentakuruV4)

```bash
cd PentakuruV4

# Cài đặt dependencies
pip install PySide6 flask pynput pyautogui opencv-python numpy pillow requests

# Optional: SSIM-based screen detection
pip install scikit-image

# Chạy radial launcher
python pentaKuruV4.py
```

---

## 📡 API Reference

### WebSocket

| Endpoint | Mô tả |
|----------|-------|
| `ws://host:9090/ws/chat?token=<auth_token>` | Real-time chat với TTS streaming |

**Request format:**
```json
{
  "text": "Xin chào",
  "mode": "chat",
  "tts": true,
  "speaker": "NF",
  "speed": 1.0,
  "token": "your_secret_token"
}
```

**Response types:**
| Type | Data |
|------|------|
| `response` | `{text, ai_latency_ms, emotional_state, hormone_levels}` |
| `tts_start` | `{total: <số câu>}` |
| `audio_chunk` | `{audio_b64, mime_type}` |
| `audio_end` | `{}` |

### REST API Endpoints

#### 🔐 Authentication
Hầu hết endpoints yêu cầu `Authorization: Bearer <token>`

#### 🏥 Health & Status
| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `GET` | `/` | Trang chủ server |
| `GET` | `/api/health` | Trạng thái hệ thống + hormone levels |
| `GET` | `/api/hormone_status` | Chi tiết trạng thái hormone |
| `POST` | `/api/hormone_reset` | Reset hormone về baseline |

#### ⚙️ Configuration
| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `GET` | `/api/config` | Lấy cấu hình hiện tại |
| `POST` | `/api/config` | Cập nhật cấu hình |
| `GET` | `/api/config_cloud` | Lấy cấu hình Cloud LLM |
| `POST` | `/api/config_cloud` | Cập nhật Cloud LLM config |

#### 🤖 AI & Learning
| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `POST` | `/api/teach` | Dạy AI cụm từ mới |
| `POST` | `/api/ollama_command` | Parse lệnh Ollama |
| `POST` | `/api/execute_pc_command` | Thực thi lệnh trên Windows PC |

#### 🏠 Smart Home
| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `GET` | `/api/status` | Trạng thái ổ điện + PC |
| `POST` | `/api/turn-on-pc` | Bật nguồn PC |
| `POST` | `/api/turn-off-pc` | Tắt nguồn PC |

#### 📅 Schedule
| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `GET` | `/api/schedule` | Lấy lịch trình hàng tuần |
| `POST` | `/api/schedule` | Cập nhật lịch trình |

#### 🔧 System
| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `GET` | `/api/modules` | Trạng thái các module |

---

## 🧬 Hormone System — Chi tiết kỹ thuật

### States mapping
Dựa trên 7 hormone levels, hệ thống ánh xạ thành **15+ trạng thái cảm xúc**:

| Trạng thái | Điều kiện | Mô tả |
|------------|-----------|-------|
| `neutral` | Mặc định | Bình thường |
| `curious_energetic` | D > 0.65, C < 0.28 | Tò mò, năng lượng |
| `content_loving` | O > 0.65, S > 0.55 | Hài lòng, yêu thương |
| `calm_confident` | S > 0.65, C < 0.28 | Bình tĩnh, tự tin |
| `excited_warm` | O > 0.65, D > 0.55 | Hứng thú, ấm áp |
| `mildly_stressed` | C > 0.28, S < 0.60 | Hơi căng thẳng |
| `stressed` | C > 0.50, S < 0.45 | Căng thẳng |
| `anxious` | C > 0.55, A > 0.35 | Lo âu |
| `surprised_alert` | A > 0.30 | Bất ngờ, cảnh giác |
| `sleepy_calm` | G > 0.58, D < 0.55 | Buồn ngủ, bình lặng |
| `low_energy` | D < 0.35, S < 0.42 | Thiếu năng lượng |
| `tired_uneasy` | C > 0.30, G > 0.55 | Mỏi mệt |
| `guarded` | C > 0.30, O < 0.45 | Phòng thủ |

### Response Modifiers
Hormone levels chuyển thành các tham số ảnh hưởng câu trả lời:

| Modifier | Công thức | Range | Ảnh hưởng |
|----------|-----------|-------|-----------|
| `warmth` | O×0.6 + S×0.3 - C×0.2 | 0–1 | Độ ấm áp, thân thiện |
| `verbosity` | D×0.4 + O×0.3 + S×0.2 - C×0.3 | 0.1–1 | Độ dài câu trả lời |
| `positivity` | S×0.4 + D×0.3 + O×0.2 - C×0.4 | 0–1 | Tích cực của tone |
| `proactivity` | D×0.5 + O×0.2 - C×0.2 | 0–1 | Xu hướng tự bộc lộ |
| `intimacy` | O×0.7 + S×0.3 | 0–1 | Mức độ thân mật |
| `distance` | C×0.8 - O×0.2 | 0–1 | Khoảng cách cảm xúc |

### Auto-save & Persistence
- **atexit hook**: Tự động lưu khi process tắt
- **Mỗi 10 interactions**: Auto-save định kỳ
- **File lưu**: `data/hormone_state.json`

---

## 🔒 Bảo mật & Riêng tư

- ✅ **Local-first**: Mọi dữ liệu hormone, profile, ký ức lưu cục bộ trên máy
- ✅ **Token authentication**: Bearer token cho mọi API call
- ✅ **Git-ignore**: Các file nhạy cảm (data/, config.json with secrets) không push lên Git
- ✅ **Tailscale VPN**: Kết nối mã hóa E2E giữa các thiết bị
- ✅ **No cloud dependency** (optional): Cloud LLM chỉ dùng khi được cấu hình

---

## 🔧 Troubleshooting

### Common Issues

| Vấn đề | Nguyên nhân | Giải pháp |
|--------|-------------|-----------|
| Server không khởi động | Missing dependencies | `pip install -r requirements.txt` |
| WebSocket disconnect | Firewall blocking port 9090 | Mở port hoặc dùng Tailscale |
| TTS không phát | Thiếu engine | Cài Valtec hoặc VoiceVox |
| Hormone không persist | File permission | Chmod 755 data/ |
| Ollama không connect | Ollama chưa chạy | `ollama serve` |

### Debug Mode

```bash
# Bật verbose logging
export LOG_LEVEL=DEBUG
python ai_server.py
```

---

## 📈 Performance

| Metric | Giá trị |
|--------|---------|
| AI Response Time | 200–800ms (local), 1–3s (cloud) |
| TTS Latency | 500–1500ms/câu |
| WebSocket Throughput | 100+ msgs/sec |
| Memory Usage | ~500MB (base), ~2GB (with SBERT) |
| Hormone Save | <5ms |

---

## 🗺️ Roadmap

- [ ] **Web Dashboard** — Giao diện web quản lý hệ thống
- [ ] **Multi-user Support** — Hỗ trợ nhiều người dùng
- [ ] **Advanced Memory** — Long-term knowledge graph
- [ ] **Vision Integration** — Nhận diện hình ảnh qua camera
- [ ] **MQTT Support** — Smart home qua MQTT protocol
- [ ] **Docker Deployment** —Deploy dễ dàng qua container

---

## ❤️ Đóng góp

Dự án được phát triển bởi **gooleseswsq1**. Mọi ý kiến đóng góp về hệ thống hormone, cải thiện giọng nói, hoặc tính năng mới đều được chào đón!

### Liên hệ
- GitHub: [PentaYuki/Pentamiv1](https://github.com/PentaYuki/Pentamiv1)
- Issues: [Report bugs & feature requests](https://github.com/PentaYuki/Pentamiv1/issues)

---

<p style="text-align:center; font-style:italic; color:#666;">
Created with love for a More Human AI. 🔺
</p>