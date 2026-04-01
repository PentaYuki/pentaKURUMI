from voicevox_core import METAS

print("=== DANH SÁCH ID GIỌNG ĐỌC VOICEVOX ===")
for meta in METAS:
    for style in meta.styles:
        print(f"ID: {style.id:<3} | Nhân vật: {meta.name} (Kiểu: {style.name})")