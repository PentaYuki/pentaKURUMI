# 🔺 Pentakuru V4: Windows Remote Controller

![Windows](https://img.shields.io/badge/OS-Windows-blue)
![Python](https://img.shields.io/badge/Python-3.10+-yellow)
![Framework](https://img.shields.io/badge/PySide-6-green)

**Pentakuru V4** là công cụ điều khiển Windows mạnh mẽ, đóng vai trò là "cảnh tay nối dài" cho máy chủ AI trong hệ sinh thái **pentaKURUMI**.

---

## 🔗 Liên kết với pentaKURUMI

Công cụ này được thiết kế để kết nối trực tiếp với [pentaKURUMI AI Ecosystem](https://github.com/gooleseswsq1/pentaKURUMI). Khi máy chủ AI (thường chạy trên Mac) muốn thực hiện các lệnh trên Windows, nó sẽ gửi yêu cầu qua giao thức **Tailscale** an toàn tới Pentakuru V4 để:
- **Thực thi PowerShell**: Điều khiển toàn bộ hệ thống từ xa.
- **Tìm kiếm tập tin**: Tìm các file ZIP, PDF, hoặc thư mục nhanh chóng.
- **Radial Launcher**: Giao diện vòng tròn hiện đại giúp truy cập nhanh các ứng dụng trên Windows.

---

## ✨ Tính năng chính

- **Flask Server**: Nhận lệnh HTTP an toàn qua Token.
- **Tailscale Integration**: Truy cập từ xa mà không cần mở port phức tạp.
- **Radial UI**: Giao diện đẹp mắt, tự ẩn hiện linh hoạt.
- **Smart Tracking**: Theo dõi tab trình duyệt (Chrome DevTools).
- **Auto-hide**: Tự động ẩn khi click ra ngoài.

---

## 🚀 Cài đặt & Sử dụng

### 1. Yêu cầu
- Python 3.10+
- PySide6
- Flask
- Tailscale (để điều khiển từ xa)

### 2. Cài đặt dependencies
```bash
pip install PySide6 flask requests pyperclip uiautomation websocket-client
```

### 3. Chạy ứng dụng
```bash
python pentaKuruV4.py
```

### 4. Cấu hình
Lần đầu chạy, ứng dụng sẽ tạo thư mục `data/` chứa các cấu hình quan trọng. Hãy đảm bảo **Auth Token** trong `server.json` khớp với cấu hình phía máy chủ AI (pentaKURUMI).

---

## 🛡️ Bảo mật
Mọi lệnh thực thi đều yêu cầu **Bearer Token** xác thực. Dữ liệu nhạy cảm được tệp `.gitignore` bỏ qua để đảm bảo an toàn khi đẩy lên GitHub.

---
*Developed by gooleseswsq1. A unified future of AI and Remote Interaction.*
