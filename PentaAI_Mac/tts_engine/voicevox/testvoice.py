import os
from voicevox_core import VoicevoxCore

# 1. Khởi tạo Voicevox (Nhớ trỏ đúng đường dẫn thư mục từ điển của bạn)
dict_path = "tts/open_jtalk_dic_utf_8-1.11" # Sửa lại nếu thư mục của bạn nằm chỗ khác
core = VoicevoxCore(acceleration_mode="AUTO", open_jtalk_dict_dir=dict_path)

# 2. Chọn ID giọng đọc (Ví dụ: 2 là Zundamon)
SPEAKER_ID = 2  

print(f"⏳ Đang load giọng ID {SPEAKER_ID}...")
core.load_model(SPEAKER_ID)

# 3. Đọc thử một câu tiếng Nhật
text = "こんにちは、ずんだもんなのだ"
print(f"🗣️ Đang đọc: {text}")
wav_data = core.tts(text, SPEAKER_ID)

# 4. Lưu ra file và phát thử
with open("test.wav", "wb") as f:
    f.write(wav_data)

print("✅ Đã lưu thành file test.wav!")

# Tự động phát âm thanh (Nếu bạn dùng Windows)
import sys
if sys.platform == "win32":
    import winsound
    winsound.PlaySound("test.wav", winsound.SND_FILENAME)
elif sys.platform == "darwin": # Nếu dùng máy Mac
    os.system("afplay test.wav")