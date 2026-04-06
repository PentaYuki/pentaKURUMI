# 📧 PentaAI Gmail Notification System - Hướng dẫn triển khai

## Tính năng

Hệ thống **Gmail Notification** cho phép PentaAI:
- ✅ **Monitor email** từ danh sách whitelist người dùng cấu hình
- ✅ **Phát thông báo TTS** qua speaker: "Bạn có tin nhắn từ [nickname]"
- ✅ **Hỏi tương tác**: "Bạn có muốn đọc nội dung không?"
- ✅ **Queue + Retry**: Nếu user không trả lời, nhắc lại sau 15 phút
- ✅ **Đánh dấu đọc**: Tự động mark as read trên Gmail khi user đồng ý
- ✅ **Multi-lang**: Vietnamese, English, Japanese support

## Kiến trúc

```
┌─────────────────────────────────────────────────────────┐
│  ai_server.py (FastAPI)                                 │
│  ├─ Lifespan: init_daemon(config_fn, broadcast_fn)      │
│  ├─ API /api/gmail_notify_*                             │
│  └─ broadcast_proactive() → WebSocket clients           │
├─ GmailNotificationDaemon (services/)                    │
│  ├─ Background thread: 15s loop                         │
│  ├─ IMAP monitor: Check UNSEEN emails                   │
│  ├─ Queue state machine:                                │
│  │   PENDING → ASK_USER → REPLIED_YES/NO                │
│  │             ↓ timeout (15min) → REQUEUE              │
│  └─ _broadcast_fn() → TTS + WebSocket                   │
├─ CLI (cli.py)                                           │
│  ├─ UI section: "Gmail Notification"                    │
│  ├─ Modal: Config whitelist                             │
│  └─ JS functions: add/remove/save whitelist             │
├─ SkillManager                                           │
│  └─ skills/gmail_notification_intent.py                 │
│     (Check intents: "bật pentgmail", "có tin nhắn", etc)
└─────────────────────────────────────────────────────────┘
```

## Cấu hình

### 1. Thêm Gmail Config vào `config.json`

```json
{
  "gmail_notification_enabled": false,
  "gmail_notification_whitelist": [
    {"email": "test.gmail", "nickname": "test"},
    {"email": "boss.company.com", "nickname": "boss"}
  ],
  "gmail_notification_retry_interval_sec": 900,
  "email": "yourname@gmail.com",
  "password": "xxxx xxxx xxxx xxxx"
}
```

**Lưu ý:**
- `email` & `password`: Gmail + App Password (không phải plain password!)
  - Mở Gmail Settings → Security → App Passwords
  - Tạo app password cho "Mail" on "Windows"  
  - Copy vào email + password keys

### 2. Khởi động Server

```bash
cd PentaAI_Mac
python ai_server.py
```

Server sẽ tự:
- Tải daemon service
- Khởi tạo background thread
- Kết nối IMAP (nếu enabled=true)

### 3. Cấu hình Whitelist qua CLI

**Bước 1**: Truy cập CLI ở `http://localhost:8080`

**Bước 2**: Ở sidebar bên trái, tìm section "📧 Gmail Notification"

**Bước 3**: Nhấn "⚙️ Quản lí danh sách"

**Bước 4**: Thêm email + nickname:
- Email: `test.gmail` 
- Nickname: `test` (hiện thị trong thông báo)

**Bước 5**: Nhấn "Lưu thay đổi"

### 4. Bật Notification

```bash
# Via CLI checkbox
- Ở section Gmail Notification, bật "Bật thông báo"

# Hoặc nói với AI
- "Bật pentgmail"
- "Kích hoạt Gmail notification"
```

## Luồng hoạt động

### Nhận email:

```
1. Daemon: Check IMAP mỗi 15 giây
2. Phát hiện email UNSEEN từ whitelist
3. Thêm vào queue: PENDING state
4. Queue processor: Convert → ASK_USER
5. Broadcast TTS: "Bạn có tin nhắn từ [nickname]"

📢 Output: "Bạn có tin nhắn từ test"
```

### User trả lời Yes:

```
1. User nói: "Được" / "Có" / "Yes"
2. Skill detect & broadcast continue
3. Daemon mark email state → REPLIED_YES
4. Phát nội dung: "Email từ test: [subject]"
5. Tự động mark as read trên Gmail
6. Xóa khỏi queue

✅ Done
```

### User trả lời No / Timeout:

```
1. User nói: "Không" / "Skip" / "No"
   HOẶC user hết timeout (15 phút)

2. Daemon state: REPLIED_NO / REQUEUE

3. Sau 15 phút: Phát thông báo lại
   📢 "Nhắc nhở: Bạn có tin nhắn từ test - [subject]"

4. User có thể trả lời lại hoặc skip tiếp
```

## API Endpoints

### `GET /api/gmail_notify_whitelist`
Lấy danh sách whitelist hiện tại.

```bash
curl -H "Authorization: Bearer TOKEN" http://localhost:9090/api/gmail_notify_whitelist
```

Response:
```json
{
  "status": "ok",
  "whitelist": [
    {"email": "test.gmail", "nickname": "test"}
  ]
}
```

### `POST /api/gmail_notify_whitelist`
Thêm hoặc xóa entry.

```bash
# Add
curl -X POST \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "add", "email": "boss.company", "nickname": "boss"}' \
  http://localhost:9090/api/gmail_notify_whitelist

# Remove
curl -X POST \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "remove", "email": "test.gmail"}' \
  http://localhost:9090/api/gmail_notify_whitelist
```

### `GET /api/gmail_notify_queue`
Lấy queue email chờ xử lý.

```bash
curl -H "Authorization: Bearer TOKEN" http://localhost:9090/api/gmail_notify_queue
```

Response:
```json
{
  "status": "ok",
  "count": 2,
  "queue": [
    {
      "uid": "12345",
      "email_from": "test.gmail",
      "nickname": "test",
      "subject": "Project Update",
      "state": "ask_user",
      "asked_at": "2026-04-06T14:30:00"
    }
  ]
}
```

### `POST /api/gmail_notify_response`
User gửi trả lời (yes/no).

```bash
curl -X POST \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"uid": "12345", "response": "yes"}' \
  http://localhost:9090/api/gmail_notify_response
```

### `POST /api/gmail_notify_enable`
Bật/tắt Gmail notification.

```bash
# Enable
curl -X POST \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}' \
  http://localhost:9090/api/gmail_notify_enable
```

## Câu lệnh Voice

Nói với PentaAI để điều khiển:

| Lệnh | Tác dụng |
|------|---------|
| "Bật pentgmail" | Enable Gmail notification |
| "Tắt pentgmail" | Disable Gmail notification |
| "Có tin nhắn nào không?" | Check queue |
| "Được" / "Có" / "Yes" | Read email content |
| "Không" / "Skip" / "No" | Remind me later (15 min) |

## Troubleshooting

### ❌ Daemon không kết nối IMAP

**Nguyên nhân**: Email/password sai, 2FA không bật, IMAP chưa enable

**Giải pháp**:
1. Gmail Settings → Forwarding/POP/IMAP → Enable IMAP
2. Account → Security → 2-Step Verification (must enable)
3. App Passwords (not regular password!)
4. Test via CLI button: `python3 skills/gmail.py --test`

### ❌ Notification không phát

**Nguyên nhân**: Daemon không chạy hoặc WebSocket offline

**Giải pháp**:
1. Kiểm tra server logs: `grep "GmailNotifDaemon" ~/.../outputs.log`
2. Ensure CLI/phone app là kết nối (check WebSocket status)
3. Restart server

### ❌ Email không detect được

**Nguyên nhân**: Sender không trong whitelist hoặc email là read

**Giải pháp**:
1. Kiểm tra whitelist email (case-insensitive)
2. Mark email as UNSEEN trong Gmail
3. Daemon chỉ monitor UNSEEN emails

### ❌ Queue theo dõi không cập nhật

**Nguyên nhân**: Daemon thread crashed

**Giải pháp**:
1. Check logs: `grep "GmailNotifDaemon" error.log`
2. Restart server: `kill $(lsof -t -i :9090) && python ai_server.py`

## Performance Tuning

```json
{
  "gmail_notification_retry_interval_sec": 900,  // 15 min retry
  // Tăng để giảm tần suất nhắc nhở
  // Giảm để nhắc nhở nhanh hơn
}
```

**Default**: 900 giây = 15 phút

## Security Notes

- ✅ Email + password mã hóa cấp browser (HTTPS)
- ✅ IMAP connection: SSL/TLS (port 993)
- ✅ API token required (verify_token)
- ⚠️ Mật khẩu lưu plain text trong config.json (git-ignored)
- ⚠️ Đừng commit config.json lên GitHub

## Logs

Xem logs daemon:

```bash
grep "GmailNotifDaemon" PentaAI_Mac/outputs.log
grep "GmailNotifDaemon" -A5 outputs.log  # Full context
```

Kích hoạt DEBUG:
```python
# ai_server.py
logging.getLogger("GmailNotifDaemon").setLevel(logging.DEBUG)
```

## Future Enhancements

- [ ] Hỗ trợ multiple Gmail accounts
- [ ] Filter/Priority email levels
- [ ] Calendar integration (meeting notifications)
- [ ] Custom TTS voice for different senders
- [ ] Email content auto-summarize
- [ ] Mobile push notifications
- [ ] Webhook support for external services
