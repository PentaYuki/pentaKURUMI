# PentaCommand 🔺

iOS app điều khiển hệ thống bằng giọng nói qua Tailscale.

## Kiến trúc

```
iPhone (Swift App)
    │ Tailscale VPN
    ▼
Mac mini 24/7 (penta_server.py :8080)
    │ Home Assistant API
    ▼
Smart Relay (ổ điện thông minh)
    │ Cấp điện
    ▼
Windows PC
    └─ BIOS: Restore on AC Power Loss = ON
    └─ Startup script: start_ai.py
```

## Cài đặt iOS App

1. Mở Xcode → tạo project SwiftUI mới tên **PentaCommand**
2. Copy các file `.swift` vào project
3. Merge nội dung `Info.plist` vào file Info.plist của project
4. **Signing**: chọn Team của bạn trong Xcode > Signing & Capabilities
5. Build và chạy trên iPhone thật (cần device thật vì dùng microphone)

### Quyền cần cấp (iOS Settings)
- Microphone: **Bật**
- Speech Recognition: **Bật**

## Cài đặt Mac mini Server

```bash
# Cài dependencies
pip3 install flask requests

# Cài wakeonlan (tuỳ chọn, để WoL)
brew install wakeonlan

# Cấu hình biến môi trường
export PENTA_TOKEN="penta_your_secret_token"
export HA_URL="http://homeassistant.local:8123"
export HA_TOKEN="your_home_assistant_long_lived_token"
export PC_MAC_ADDRESS="AA:BB:CC:DD:EE:FF"
export PC_TAILSCALE_IP="100.x.x.x"

# Chạy server
python3 penta_server.py

# Để chạy 24/7 dùng launchd hoặc:
# pm2 start penta_server.py --interpreter python3
```

### Tìm Tailscale IP của Mac mini
```bash
tailscale ip -4
# → 100.x.x.x
```

## Cài đặt iOS App Settings

Trong app, vào **Settings** (icon slider):
- **Mac mini URL**: `http://100.x.x.x:8080` (Tailscale IP)
- **Auth Token**: token bạn đặt trong `PENTA_TOKEN`
- **Wake Word**: mặc định là `Penta`

## Chế độ lắng nghe

| Chế độ | Cách dùng |
|--------|-----------|
| **LIÊN TỤC** | Nói lệnh bất cứ lúc nào khi app đang mở |
| **WAKE WORD** | Nói "Penta" trước, rồi nói lệnh |

## Lệnh mặc định

| Trigger | Endpoint | Chức năng |
|---------|----------|-----------|
| "bật pc" | `/api/turn-on-pc` | Cấp điện relay → PC khởi động |
| "tắt pc" | `/api/turn-off-pc` | Ngắt điện relay |
| "mở ai" | `/api/start-ai` | Chạy AI script trên Windows |
| "trạng thái" | `/api/status` | Kiểm tra hệ thống |
| "bật đèn" | `/api/light/on` | Bật đèn qua HA |
| "tắt đèn" | `/api/light/off` | Tắt đèn qua HA |

## BIOS Windows PC

Vào BIOS (thường F2/Del khi khởi động):
- Tìm: **Power Management** → **Restore on AC Power Loss**
- Đặt thành: **Power On** (hoặc Last State)

## Thêm lệnh custom

Trong app → nhấn icon list → dấu **+**:
- **Tên lệnh**: hiển thị trong UI
- **Từ khoá**: trigger giọng nói
- **API Endpoint**: path gửi đến Mac mini (vd: `/api/custom/restart-nginx`)

Server sẽ nhận tại `/api/custom/<endpoint>` — thêm logic tại đó.
