# 📧 Gmail Notification - Quick Setup Guide

## 🚀 5-Minute Setup

### Step 1: Get Gmail App Password (2 min)

1. Go to **myaccount.google.com → Security**
2. Enable **2-Step Verification** (if not already done)
3. Go back to **Security → App Passwords**
4. Choose "Mail" + "Windows" → Generate
5. Copy the password (16 characters with spaces)

### Step 2: Update config.json (1 min)

```bash
cd PentaAI_Mac
```

Edit **config.json** and find/add:

```json
{
  "email": "yourname@gmail.com",
  "password": "xxxx xxxx xxxx xxxx",
  "gmail_notification_enabled": false,
  "gmail_notification_whitelist": [
    {"email": "sender1.gmail", "nickname": "sender1"},
    {"email": "boss.company", "nickname": "boss"}
  ],
  "gmail_notification_retry_interval_sec": 900
}
```

⚠️ **Replace**:
- `yourname@gmail.com` → Your actual Gmail
- `xxxx xxxx xxxx xxxx` → App password from Step 1

### Step 3: Restart Server (1 min)

```bash
# Stop old server (if running)
pkill -f "python.*ai_server.py" || true

# Start server
python ai_server.py
```

**Check startup logs** for:
```
✅ Gmail Notification Daemon started
✅ IMAP connected
```

### Step 4: Configure Whitelist via CLI (1 min)

1. Open **http://localhost:8080** in browser
2. Sidebar → **📧 Gmail Notification**
3. Click **"⚙️ Quản lí danh sách"**
4. Add emails you want to monitor:
   - Email: `test.gmail`
   - Nickname: `test` (how it appears in notification)
5. Click **"Lưu thay đổi"**

### Step 5: Enable Feature (Optional, 30 sec)

```bash
# Option A: CLI checkbox
# Sidebar → Gmail Notification → Toggle "Bật thông báo"

# Option B: Voice command
# Say: "Anh muốn bật pentgmail"
```

## ✅ Test It

### Send Test Email

1. From browser, send email to yourself from one of the whitelist senders
2. Wait **15-30 seconds**
3. Listen for: **"Bạn có tin nhắn từ [nickname]"**

### Expected Flow

```
📧 Email arrives
  ↓
🔊 "Bạn có tin nhắn từ test - Project Update"
   "Bạn có muốn đọc nội dung không?"
  ↓
You say: "Được" / "Có" / "Yes"
  ↓
🔊 "Email từ test: Project Update"
  ↓
✅ Email marked as read on Gmail
```

## 🎭 Voice Commands

| Say | Result |
|-----|--------|
| "Bật pentgmail" | Enable notifications |
| "Tắt pentgmail" | Disable notifications |
| "Có tin nhắn nào không?" | Check queue |
| "Được" / "Có" | Read email content |
| "Không" / "Thôi" | Remind me in 15 min |

## 🔍 Troubleshooting

### ❌ "Cannot connect to Gmail"
- Check App Password is correct (16 chars with spaces)
- Check 2-Step Verification is enabled
- Check IMAP is enabled in Gmail Settings

### ❌ "Notification not triggering"
- Check email is in whitelist (case-insensitive)
- Make sure email is UNSEEN (not read yet)
- Check server logs: `grep GmailNotifDaemon outputs.log`

### ❌ "Email not being recognized"
- Must be EXACT email address (no typos)
- Case doesn't matter (test.gmail = TEST.GMAIL)
- Check whitelist in CLI shows email

## 📋 Features

✅ **Queue Management**: Automatic retry after 15 minutes  
✅ **State Machine**: PENDING → ASK → REPLY → DONE/REQUEUE  
✅ **Whitelist Control**: CLI-based management (no code edits)  
✅ **Auto Mark Read**: Marks email as read when user responds "yes"  
✅ **Multi-Language**: VI/EN/JP support  
✅ **TTS Broadcast**: Phát qua speaker để user nghe  
✅ **Voice Interactive**: User responds via voice commands  

## 📚 Full Documentation

See **GMAIL_NOTIFICATION_GUIDE.md** for:
- Complete architecture overview
- API reference
- Advanced configuration
- Performance tuning
- Security notes
- Development roadmap

## 🆘 Getting Help

**Check logs**:
```bash
tail -100 outputs.log | grep Gmail
```

**Test IMAP connection**:
```bash
cd skills
python3 gmail.py --setup
python3 gmail.py --test
```

**Restart daemon**:
```bash
# Kill AI server
pkill -f "python.*ai_server.py"

# Wait 2s
sleep 2

# Restart
python ai_server.py
```

## 🎉 You're Ready!

Daemon is now monitoring your inbox. Send yourself a test email and listen for the notification!

**Pro tip**: Try saying "Có tin nhắn nào không?" to check the queue anytime.
