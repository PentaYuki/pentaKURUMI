# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                        pentaKuruV4.py                                      ║
# ║   PentaKuRu Radial Launcher  ·  Remote PowerShell via Tailscale            ║
# ║   v4.2 — Flask server · PSExecutor · TailscaleManager                      ║
# ║         File Search (ZIP/PDF/Folder) · MB4/MB5/MB6 · Tray icon            ║
# ║         Auto-hide on outside click  · Remote server via Tailscale/LAN      ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

import sys
import os
import json
import time
import math
import winreg
import ctypes
import ctypes.wintypes
import threading
import subprocess
import webbrowser
import socket
import secrets
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Set, List, Callable, Tuple

os.environ["QT_LOGGING_RULES"] = "*.debug=false"

from PySide6.QtWidgets import (
    QWidget, QApplication, QFrame, QVBoxLayout, QHBoxLayout,
    QLineEdit, QLabel, QPushButton, QCheckBox, QListWidget, QListWidgetItem,
    QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QMessageBox,
    QSystemTrayIcon, QMenu, QScrollArea,
)
from PySide6.QtCore import (
    Qt, QTimer, QPoint, QPointF, QRectF, QObject, Signal, Property,
    QThread, QPropertyAnimation, QParallelAnimationGroup, QEasingCurve,
    QAbstractNativeEventFilter, Slot,
)
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QFontMetrics, QPolygonF,
    QPixmap, QIcon, QKeyEvent, QCursor, QPainterPath, QAction,
)

# ── Optional deps ────────────────────────────────────────────────────────────
try:
    import uiautomation as auto  # type: ignore
except ImportError:
    auto = None

try:
    import requests as _req        # noqa – used in CDP tracker
    import websocket as _ws        # noqa
    _CDP_AVAILABLE = True
except ImportError:
    _CDP_AVAILABLE = False

try:
    import pyperclip  # type: ignore
except ImportError:
    pyperclip = None

try:
    from flask import Flask as _Flask, request as _flask_req, jsonify as _jsonify
    _FLASK_OK = True
except ImportError:
    _Flask = _flask_req = _jsonify = None  # type: ignore
    _FLASK_OK = False
    print("[Server] Flask chưa cài. Chạy: pip install flask")


# ══════════════════════════════════════════════════════════════════════════════
#  SYSTEM UTILS
# ══════════════════════════════════════════════════════════════════════════════

class SystemUtils:
    KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
    APP_NAME = "BabySight"

    @staticmethod
    def set_startup_with_windows(enable: bool) -> bool:
        exe_path = sys.executable if getattr(sys, "frozen", False) else os.path.abspath(sys.argv[0])
        exe_path = f'"{exe_path}"'
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, SystemUtils.KEY_PATH, 0, winreg.KEY_ALL_ACCESS)
            if enable:
                winreg.SetValueEx(key, SystemUtils.APP_NAME, 0, winreg.REG_SZ, exe_path)
            else:
                try:
                    winreg.DeleteValue(key, SystemUtils.APP_NAME)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
            return True
        except Exception as e:
            print(f"[Registry] {e}")
            return False

    @staticmethod
    def is_startup_enabled() -> bool:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, SystemUtils.KEY_PATH, 0, winreg.KEY_READ)
            winreg.QueryValueEx(key, SystemUtils.APP_NAME)
            winreg.CloseKey(key)
            return True
        except Exception:
            return False

    @staticmethod
    def get_lan_ip() -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"


# ══════════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

class Constants:
    WIDTH,  HEIGHT      = 800, 800
    NUM_SIDES           = 5
    SECTORS_PER_PAGE    = NUM_SIDES
    FADE_SPEED          = 1.0 / (0.4 * 60)
    RADIUS              = 108
    CENTER_RADIUS       = 30
    UI_POSITION_Y       = 360
    UI_SPACING          = 35
    DROP_ZONE_WIDTH     = 350
    DROP_ZONE_HEIGHT    = 180
    DROP_ZONE_Y         = 520
    URL_UI_WIDTH        = 350
    URL_UI_HEIGHT       = 220
    URL_UI_Y            = 520
    SETTING_UI_WIDTH    = 450
    SETTING_UI_HEIGHT   = 380
    COLOR_IDLE          = (0,  0,  0,  180)
    COLOR_HOVER         = (60, 60, 60, 240)
    COLOR_OUTLINE       = (255, 255, 255, 100)

    # VK codes
    VK_SHIFT    = 0x10;  VK_CONTROL  = 0x11;  VK_MENU   = 0x12
    VK_LWIN     = 0x5B;  VK_SLASH    = 0xBF;  VK_PERIOD = 0xBE
    VK_RETURN   = 0x0D;  VK_ESCAPE   = 0x1B;  VK_SPACE  = 0x20
    VK_BACK     = 0x08;  VK_TAB      = 0x09;  VK_DELETE = 0x2E
    VK_PAUSE    = 0x13;  VK_INSERT   = 0x2D;  VK_HOME   = 0x24
    VK_END      = 0x23;  VK_PAGEUP   = 0x21;  VK_PAGEDOWN = 0x22
    VK_UP       = 0x26;  VK_DOWN     = 0x28;  VK_LEFT   = 0x25; VK_RIGHT = 0x27
    VK_NUMLOCK  = 0x90;  VK_SCROLLLOCK = 0x91; VK_PRINTSCREEN = 0x2C
    # F-keys
    VK_F1  = 0x70;  VK_F2  = 0x71;  VK_F3  = 0x72;  VK_F4  = 0x73
    VK_F5  = 0x74;  VK_F6  = 0x75;  VK_F7  = 0x76;  VK_F8  = 0x77
    VK_F9  = 0x78;  VK_F10 = 0x79;  VK_F11 = 0x7A;  VK_F12 = 0x7B
    VK_F13 = 0x7C;  VK_F14 = 0x7D;  VK_F15 = 0x7E;  VK_F16 = 0x7F
    VK_F17 = 0x80;  VK_F18 = 0x81;  VK_F19 = 0x82;  VK_F20 = 0x83
    VK_F21 = 0x84;  VK_F22 = 0x85;  VK_F23 = 0x86;  VK_F24 = 0x87
    # Mouse
    VK_MB_LEFT    = 0x01;  VK_MB_RIGHT   = 0x02;  VK_MB_MIDDLE  = 0x04
    VK_MB_BACK    = 0x05;  VK_MB_FORWARD = 0x06
    # Hotkey IDs
    ID_LAUNCHER = 1;  ID_SEARCH = 2
    SEARCH_DEFAULT_MODS = 0x0001   # MOD_ALT
    SEARCH_DEFAULT_KEY  = VK_SPACE
    TEXT_VISIBLE_DURATION = 1.8
    TEXT_FADE_SPEED       = 0.1


# ══════════════════════════════════════════════════════════════════════════════
#  DATA MODELS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SectorData:
    exe_path:        str  = ""
    icon_path:       str  = ""
    url:             str  = ""
    name:            str  = ""
    use_incognito:   bool = False
    enable_tracking: bool = False

    def has_data(self) -> bool:
        return bool(self.exe_path or self.url)

    def is_folder(self) -> bool:
        return os.path.isdir(self.exe_path) if self.exe_path else False


class AppState:
    def __init__(self):
        self.visible                  = False
        self.editing_index: Optional[int] = None
        self.hovered_sector_index: Optional[int] = None
        self.is_url_mode              = False
        self.input_active             = False
        self.input_text               = ""
        self.is_setting_mode          = False
        self.key_combination_detected = False
        self.detected_modifiers: Set[int] = set()
        self.detected_key: Optional[int]  = None
        self.is_restarting            = False
        self.current_page             = 0
        self.total_pages              = 1
        self.show_page_indicator      = False
        self.page_indicator_time      = 0
        self.center_fade              = 0.0
        self.last_toggle_time         = 0
        self.keys_held: Dict[int, float] = {}
        self.bound_windows: Dict[int, int] = {}
        self.text_opacity             = 1.0
        self.last_text_active_time    = 0
        self.auto_hide_labels         = True
        self.is_center_hovered        = False

    def can_toggle(self) -> bool:
        t = time.time()
        if t - self.last_toggle_time > 0.3:
            self.last_toggle_time = t
            return True
        return False

    def update_center_fade(self, hovered: bool):
        if hovered:
            self.center_fade = min(1.0, self.center_fade + Constants.FADE_SPEED)
        else:
            self.center_fade = max(0.0, self.center_fade - Constants.FADE_SPEED)

    def get_global_sector_index(self, local: int) -> int:
        return self.current_page * Constants.SECTORS_PER_PAGE + local

    def next_page(self) -> bool:
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._mark_page()
            return True
        return False

    def prev_page(self) -> bool:
        if self.current_page > 0:
            self.current_page -= 1
            self._mark_page()
            return True
        return False

    def add_new_page(self) -> bool:
        self.total_pages += 1
        self.current_page = self.total_pages - 1
        self._mark_page()
        return True

    def remove_current_page(self) -> bool:
        if self.total_pages > 1:
            self.total_pages -= 1
            self.current_page = min(self.current_page, self.total_pages - 1)
            self._mark_page()
            return True
        return False

    def _mark_page(self):
        self.show_page_indicator  = True
        self.page_indicator_time  = time.time()


# ══════════════════════════════════════════════════════════════════════════════
#  DATA MANAGER  (Singleton — BUG FIX #2)
# ══════════════════════════════════════════════════════════════════════════════

class DataManager(QObject):
    """
    Singleton DataManager.
    BUG FIX #2: HotkeyManager cũ tạo instance riêng → dữ liệu không đồng bộ.
    Giờ tất cả dùng DataManager.instance() để lấy cùng 1 object.
    """
    data_changed = Signal()

    _instance: Optional["DataManager"] = None

    @classmethod
    def instance(cls) -> "DataManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _get_app_root() -> str:
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    def __init__(self):
        super().__init__()
        if DataManager._instance is not None:
            raise RuntimeError("Use DataManager.instance()")
        self._lock = threading.Lock()
        self.base_path  = self._get_app_root()
        self.memory_dir = os.path.join(self.base_path, "data")
        try:
            os.makedirs(self.memory_dir, exist_ok=True)
        except PermissionError:
            appdata = os.getenv("APPDATA", ".")
            self.memory_dir = os.path.join(appdata, "BabySight", "data")
            os.makedirs(self.memory_dir, exist_ok=True)
        print(f"[DataManager] data dir: {self.memory_dir}")
        self.sector_data: Dict[int, SectorData] = {}
        self.hotkey_data: dict = {}
        self.app_config: dict  = {"first_run": True, "text_auto_hide": True}
        self.urls_data:  dict  = {}
        self.server_config: dict = {}
        self.startup_config_path = os.path.join(self.memory_dir, "startup_config.json")
        self._load_all()

    # ── I/O ──────────────────────────────────────────────────────────────────

    def _load_all(self):
        self._load_sectors()
        self._load_config()
        self._load_hotkeys_file()
        self._load_urls()
        self._load_server_config()
        # Sau khi load xong config (có ai_server_url), push sectors lần đầu
        self._push_sectors_on_startup()

    def _push_sectors_on_startup(self):
        """Push toàn bộ sectors hiện có lên AI server sau khi khởi động xong."""
        with self._lock:
            if not self.sector_data:
                return
            snapshot = {
                str(idx): {
                    "exe_path":        s.exe_path,
                    "icon_path":       s.icon_path,
                    "url":             s.url,
                    "name":            s.name,
                    "use_incognito":   s.use_incognito,
                    "enable_tracking": s.enable_tracking,
                }
                for idx, s in self.sector_data.items()
            }
        self._push_sectors_to_ai(snapshot)

    def _load_sectors(self):
        p = os.path.join(self.memory_dir, "sectors.json")
        if not os.path.exists(p):
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for k, v in raw.items():
                tracking = v.get("enable_tracking", v.get("tracking", False))
                self.sector_data[int(k)] = SectorData(
                    exe_path=v.get("exe_path", ""),
                    icon_path=v.get("icon_path", ""),
                    url=v.get("url", ""),
                    name=v.get("name", ""),
                    use_incognito=v.get("use_incognito", False),
                    enable_tracking=tracking,
                )
        except Exception as e:
            print(f"[DataManager] load sectors: {e}")

    def _load_config(self):
        p = os.path.join(self.memory_dir, "config.json")
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    self.app_config = json.load(f)
            except Exception:
                pass
        self.app_config.setdefault("text_auto_hide", True)
        self.app_config.setdefault("auto_hide_page_info", True)

    def _load_hotkeys_file(self):
        p = os.path.join(self.memory_dir, "hotkey.json")
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    self.hotkey_data = json.load(f)
            except Exception as e:
                print(f"[DataManager] load hotkeys: {e}")

    def _load_urls(self):
        p = os.path.join(self.memory_dir, "URL.json")
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    self.urls_data = json.load(f)
            except Exception:
                pass

    def save_all_data(self):
        p = os.path.join(self.memory_dir, "sectors.json")
        with self._lock:
            snapshot = {
                str(idx): {
                    "exe_path":      s.exe_path,
                    "icon_path":     s.icon_path,
                    "url":           s.url,
                    "name":          s.name,
                    "use_incognito": s.use_incognito,
                    "enable_tracking": s.enable_tracking,
                }
                for idx, s in self.sector_data.items()
            }
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2, ensure_ascii=False)
            self.data_changed.emit()
            # Push sectors lên AI server sau khi lưu thành công
            self._push_sectors_to_ai(snapshot)
        except Exception as e:
            print(f"[DataManager] save sectors: {e}")

    def _push_sectors_to_ai(self, snapshot: dict):
        """
        Gửi toàn bộ sectors lên AI server qua HTTP (POST /api/kuru/sectors).
        Chạy trong background thread để không block UI.
        Bỏ qua nếu ai_server_url chưa được cấu hình.
        """
        ai_url   = self.server_config.get("ai_server_url", "").strip()
        ai_token = self.server_config.get("ai_server_token", "").strip()
        if not ai_url or not ai_token:
            return  # chưa cấu hình → bỏ qua

        def _do_push():
            try:
                import urllib.request
                import urllib.error
                body = json.dumps({"sectors": snapshot}, ensure_ascii=False).encode("utf-8")
                endpoint = ai_url.rstrip("/") + "/api/kuru/sectors"
                req = urllib.request.Request(
                    endpoint,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {ai_token}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as r:
                    resp = json.loads(r.read().decode())
                    print(f"[KuruPush] AI server nhận {resp.get('received', '?')} sectors ✓")
            except Exception as e:
                print(f"[KuruPush] Không thể gửi sectors lên AI server: {e}")

        threading.Thread(target=_do_push, daemon=True, name="KuruSectorPush").start()

    def save_config(self):
        p = os.path.join(self.memory_dir, "config.json")
        try:
            with open(p, "w") as f:
                json.dump(self.app_config, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            print(f"[DataManager] save config: {e}")

    def save_hotkey_data(self):
        p = os.path.join(self.memory_dir, "hotkey.json")
        try:
            with open(p, "w") as f:
                json.dump(self.hotkey_data, f, indent=2)
        except Exception as e:
            print(f"[DataManager] save hotkeys: {e}")

    def _load_server_config(self):
        """
        Load server config theo thứ tự ưu tiên:
          1. data/server.json  (user đã lưu trước đó)
          2. bundle_config.py  (đã bundle sẵn trong EXE khi build)
          3. defaults tự sinh
        """
        p = os.path.join(self.memory_dir, "server.json")
        first_run = not os.path.exists(p)

        # ── 1. Load từ file đã lưu ────────────────────────────────────────────
        if not first_run:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    self.server_config = json.load(f)
            except Exception:
                first_run = True  # file lỗi → coi như lần đầu

        # ── 2. Lần đầu chạy: đọc bundle_config.py ────────────────────────────
        if first_run:
            bc = self._load_bundle_config()
            self.server_config["tailscale_ip"] = bc.get("tailscale_ip", "")
            self.server_config["auth_token"]   = bc.get("auth_token", "") or secrets.token_hex(16)
            self.server_config["port"]         = bc.get("port", 7777)
            self.server_config["enabled"]      = bc.get("auto_start_server", True)
            # full: mở toàn bộ thực thi PowerShell qua /run
            # demo_safe: bật whitelist demo để chặn lệnh nguy hiểm
            self.server_config["execution_mode"] = "full"
            self.server_config["use_tailscale"] = False
            self.server_config["allow_lan"] = True
            self.server_config["prefer_tailscale"] = False
            self.server_config["controller_mode"] = "default_server_only"
            self.server_config["default_controller"] = "penta_ai"
            self.server_config["allow_teamviewer_control"] = True
            self.save_server_config()
            print(f"[ServerConfig] Lần đầu khởi động — đã load bundle_config.")

        # ── 3. Đảm bảo đủ các key ────────────────────────────────────────────
        self.server_config.setdefault("tailscale_ip", "")
        self.server_config.setdefault("auth_token",   secrets.token_hex(16))
        self.server_config.setdefault("port",         7777)
        self.server_config.setdefault("enabled",      True)
        self.server_config.setdefault("execution_mode", "full")
        self.server_config.setdefault("use_tailscale", False)      # First-time: use LAN
        self.server_config.setdefault("allow_lan", True)           # First-time default: LAN enabled
        self.server_config.setdefault("prefer_tailscale", False)
        self.server_config.setdefault("controller_mode", "default_server_only")
        self.server_config.setdefault("default_controller", "penta_ai")
        self.server_config.setdefault("allow_teamviewer_control", True)
        # Địa chỉ AI server (Mac/PC chạy PentaAI) để PentaKuRu push sectors
        self.server_config.setdefault("ai_server_url",   "")  # vd: http://100.x.x.x:9090
        self.server_config.setdefault("ai_server_token", "")  # Bearer token của AI server

        # Remove legacy Cloudflare keys from older configs.
        for legacy_key in (
            "use_cloudflare",
            "cloudflare_tunnel_name",
            "cloudflare_tunnel_id",
            "cloudflare_token",
            "cloudflare_route_hostname",
            "cloudflare_route_path",
            "cloudflare_service_url",
        ):
            self.server_config.pop(legacy_key, None)

    @staticmethod
    def _load_bundle_config() -> dict:
        """
        Đọc bundle_config.py từ:
          - _MEIPASS (PyInstaller bundle)
          - Cạnh file .py/.exe
        Trả về dict rỗng nếu không tìm thấy.
        """
        search_dirs = []
        mei = getattr(sys, "_MEIPASS", None)
        if mei:
            search_dirs.append(mei)
        base = (os.path.dirname(sys.executable)
                if getattr(sys, "frozen", False)
                else os.path.dirname(os.path.abspath(__file__)))
        search_dirs.append(base)

        for d in search_dirs:
            cfg_path = os.path.join(d, "bundle_config.py")
            if not os.path.exists(cfg_path):
                continue
            try:
                ns: dict = {}
                with open(cfg_path, "r", encoding="utf-8") as f:
                    exec(compile(f.read(), cfg_path, "exec"), ns)
                return {
                    "tailscale_ip":      ns.get("TAILSCALE_IP", ""),
                    "auth_token":        ns.get("AUTH_TOKEN", ""),
                    "port":              ns.get("PORT", 7777),
                    "auto_start_server": ns.get("AUTO_START_SERVER", True),
                }
            except Exception as e:
                print(f"[bundle_config] Lỗi đọc: {e}")
        return {}

    def save_server_config(self):
        p = os.path.join(self.memory_dir, "server.json")
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self.server_config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[DataManager] save server: {e}")

    # ── Sector CRUD ───────────────────────────────────────────────────────────

    def get_sector_data(self, global_idx: int) -> SectorData:
        with self._lock:
            return self.sector_data.get(global_idx, SectorData())

    def update_sector_data(self, global_idx: int, sector: SectorData):
        with self._lock:
            self.sector_data[global_idx] = sector
        self.save_all_data()

    def delete_sector_data(self, global_idx: int):
        # BUG FIX #10: acquire lock before delete
        with self._lock:
            self.sector_data.pop(global_idx, None)
        self.save_all_data()

    def get_max_page_needed(self) -> int:
        with self._lock:
            if not self.sector_data:
                return 1
            return (max(self.sector_data.keys()) // Constants.SECTORS_PER_PAGE) + 1

    # ── Hotkey helpers ────────────────────────────────────────────────────────

    def load_search_hotkey(self) -> Dict:
        sd = self.hotkey_data.get("search_hotkey", {})
        if isinstance(sd, list) and len(sd) >= 2:
            return {"mods": sd[0], "key": sd[1]}
        if isinstance(sd, dict) and sd.get("mods") is not None:
            return sd
        return {"mods": Constants.SEARCH_DEFAULT_MODS, "key": Constants.SEARCH_DEFAULT_KEY}

    def save_search_hotkey(self, mods: int, key: int):
        self.hotkey_data["search_hotkey"] = {"mods": mods, "key": key}
        self.save_hotkey_data()

    def reset_search_hotkey(self):
        self.save_search_hotkey(Constants.SEARCH_DEFAULT_MODS, Constants.SEARCH_DEFAULT_KEY)

    def load_startup_config(self) -> Optional[bool]:
        try:
            if os.path.exists(self.startup_config_path):
                with open(self.startup_config_path, "r") as f:
                    return json.load(f).get("start_with_windows")
        except Exception:
            pass
        return None

    def save_startup_config(self, enabled: bool):
        try:
            with open(self.startup_config_path, "w") as f:
                json.dump({"start_with_windows": enabled}, f)
        except Exception as e:
            print(f"[DataManager] save startup: {e}")

    def get_default_web_url(self) -> str:
        try:
            return self.urls_data.get("1", {}).get("url", "")
        except Exception:
            return ""


# ══════════════════════════════════════════════════════════════════════════════
#  CHROME DEV TOOLS TRACKER
# ══════════════════════════════════════════════════════════════════════════════

class ChromeDevToolsTracker:
    """CDP tracker — uses optional websocket + requests libs."""

    def __init__(self, data_manager: DataManager, app_state: AppState):
        self.data_manager  = data_manager
        self.app_state     = app_state
        self.running       = True
        self.debug_port    = 9222
        self._ws_lock      = threading.Lock()
        self.ws_connections: Dict[int, object]  = {}
        self.tab_ids:        Dict[int, str]     = {}
        self._msg_id        = 100
        self._msg_lock      = threading.Lock()
        if _CDP_AVAILABLE:
            self._ensure_chrome()

    def _next_id(self) -> int:
        with self._msg_lock:
            self._msg_id += 1
            return self._msg_id

    def _ensure_chrome(self):
        try:
            import requests
            r = requests.get(f"http://localhost:{self.debug_port}/json", timeout=1)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        chrome = self._find_chrome()
        if not chrome:
            return False
        args = [chrome, f"--remote-debugging-port={self.debug_port}",
                "--remote-allow-origins=*", "--headless=new", "--disable-gpu",
                "--no-first-run", "--no-default-browser-check", "--mute-audio"]
        si = None
        if os.name == "nt":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         startupinfo=si, close_fds=True)
        time.sleep(2)
        return True

    def _find_chrome(self) -> Optional[str]:
        for p in [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        ]:
            if os.path.exists(p):
                return p
        return None

    def _get_tabs(self) -> List[dict]:
        if not _CDP_AVAILABLE:
            return []
        try:
            import requests
            r = requests.get(f"http://localhost:{self.debug_port}/json", timeout=3)
            return r.json() if r.status_code == 200 else []
        except Exception:
            return []

    def connect_to_tab(self, tab_url: str, sector_idx: int) -> bool:
        if not _CDP_AVAILABLE:
            return False
        import websocket
        for tab in self._get_tabs():
            if tab_url in tab.get("url", "") or tab_url in tab.get("title", ""):
                ws_url = tab.get("webSocketDebuggerUrl")
                if not ws_url:
                    continue
                try:
                    ws = websocket.WebSocket()
                    ws.connect(ws_url, timeout=5)
                    ws.send(json.dumps({"id": self._next_id(), "method": "Page.enable"}))
                    with self._ws_lock:
                        self.ws_connections[sector_idx] = ws
                        self.tab_ids[sector_idx] = tab.get("id")
                    return True
                except Exception as e:
                    print(f"[CDP] connect error: {e}")
        return False

    def get_tab_url(self, sector_idx: int) -> Optional[str]:
        with self._ws_lock:
            ws = self.ws_connections.get(sector_idx)
        if not ws:
            return None
        try:
            ws.send(json.dumps({"id": self._next_id(), "method": "Page.getNavigationHistory"}))
            ws.settimeout(1)
            data = json.loads(ws.recv())
            entries = data.get("result", {}).get("entries", [])
            if entries:
                ci = data["result"].get("currentIndex", len(entries) - 1)
                return entries[ci].get("url")
        except Exception:
            with self._ws_lock:
                try:
                    ws.close()
                except Exception:
                    pass
                self.ws_connections.pop(sector_idx, None)
        return None

    def track_sector(self, sector_idx: int, initial_url: str):
        with self._ws_lock:
            if sector_idx in self.ws_connections:
                return
        self.connect_to_tab(initial_url, sector_idx)

    def stop_tracking_sector(self, sector_idx: int):
        with self._ws_lock:
            ws = self.ws_connections.pop(sector_idx, None)
            self.tab_ids.pop(sector_idx, None)
        if ws:
            try:
                ws.close()
            except Exception:
                pass

    def cleanup(self):
        for idx in list(self.ws_connections.keys()):
            self.stop_tracking_sector(idx)
        self.running = False


# ══════════════════════════════════════════════════════════════════════════════
#  PS EXECUTOR  — chạy PowerShell an toàn với timeout
# ══════════════════════════════════════════════════════════════════════════════

class PSExecutor:
    """
    Thực thi PowerShell — hỗ trợ 2 mode:
      • run(cmd)     — lệnh đơn hoặc inline script ngắn
      • run_script(script) — script nhiều dòng (viết ra .ps1 tạm, chạy rồi xóa)
    """

    TIMEOUT  = 120  # giây — tăng lên để tạo Word / xử lý folder không bị timeout
    _si_cache = None

    @staticmethod
    def _si():
        if PSExecutor._si_cache is None:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            PSExecutor._si_cache = si
        return PSExecutor._si_cache

    @staticmethod
    def _build_result(proc_result) -> Dict:
        return {
            "ok":        proc_result.returncode == 0,
            "stdout":    proc_result.stdout.strip(),
            "stderr":    proc_result.stderr.strip(),
            "exit_code": proc_result.returncode,
        }

    @staticmethod
    def run(cmd: str) -> Dict:
        """Chạy lệnh PS đơn hoặc inline ngắn."""
        try:
            r = subprocess.run(
                ["powershell.exe", "-NonInteractive", "-NoProfile",
                 "-ExecutionPolicy", "Bypass", "-Command", cmd],
                capture_output=True, text=True,
                timeout=PSExecutor.TIMEOUT,
                startupinfo=PSExecutor._si(),
                encoding="utf-8", errors="replace",
            )
            return PSExecutor._build_result(r)
        except subprocess.TimeoutExpired:
            return {"ok": False, "stdout": "", "stderr": f"Timeout {PSExecutor.TIMEOUT}s", "exit_code": -1}
        except FileNotFoundError:
            return {"ok": False, "stdout": "", "stderr": "powershell.exe not found", "exit_code": -2}
        except Exception as e:
            return {"ok": False, "stdout": "", "stderr": str(e), "exit_code": -3}

    @staticmethod
    def run_script(script: str) -> Dict:
        """
        Chạy script PS nhiều dòng:
          1. Ghi ra file .ps1 tạm trong %TEMP%
          2. Chạy file đó
          3. Xóa file sau khi xong
        Dùng cho: tạo Word, restructure folder, script phức tạp...
        """
        import tempfile
        tmp_path = None
        try:
            # Ghi script ra file tạm, encoding UTF-8 BOM để PS đọc đúng tiếng Việt
            fd, tmp_path = tempfile.mkstemp(suffix=".ps1", prefix="pentakuru_")
            with os.fdopen(fd, "w", encoding="utf-8-sig") as f:
                f.write(script)

            r = subprocess.run(
                ["powershell.exe", "-NonInteractive", "-NoProfile",
                 "-ExecutionPolicy", "Bypass", "-File", tmp_path],
                capture_output=True, text=True,
                timeout=PSExecutor.TIMEOUT,
                startupinfo=PSExecutor._si(),
                encoding="utf-8", errors="replace",
            )
            return PSExecutor._build_result(r)
        except subprocess.TimeoutExpired:
            return {"ok": False, "stdout": "", "stderr": f"Timeout {PSExecutor.TIMEOUT}s", "exit_code": -1}
        except FileNotFoundError:
            return {"ok": False, "stdout": "", "stderr": "powershell.exe not found", "exit_code": -2}
        except Exception as e:
            return {"ok": False, "stdout": "", "stderr": str(e), "exit_code": -3}
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass


# ══════════════════════════════════════════════════════════════════════════════
#  FLASK SERVER THREAD  — HTTP server nhận lệnh từ remote client
# ══════════════════════════════════════════════════════════════════════════════

class FlaskServerThread(QThread):
    """
    Chạy Flask trong background thread.
    Endpoint: POST /run
      Header : Authorization: Bearer <auth_token>
      Body   : {"cmd": "...", "type": "ps"}   (type mặc định "ps")
    Response: {"ok": bool, "stdout": "...", "stderr": "...", "exit_code": int}
    """

    status_changed = Signal(str)   # "running" | "stopped" | "error:<msg>"

    def __init__(self, data_manager: "DataManager", parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self._server  = None
        self._running = False

    # ── internal token check ─────────────────────────────────────────────────

    def _check_token(self, req) -> bool:
        auth = req.headers.get("Authorization", "")
        expected = "Bearer " + self.data_manager.server_config.get("auth_token", "")
        return secrets.compare_digest(auth.strip(), expected.strip())

    # ── Demo mode helpers ────────────────────────────────────────────────────

    def _load_exec_policy(self) -> dict:
        """
        Ưu tiên policy từ server_config để có thể đổi runtime.
        Fallback về bundle_config để tương thích bản cũ.
        """
        bc = DataManager._load_bundle_config()
        mode = str(self.data_manager.server_config.get("execution_mode", "")).strip().lower()
        if mode not in {"full", "demo_safe"}:
            mode = "demo_safe" if bc.get("demo_mode", False) else "full"
        return {
            "execution_mode": mode,
            "demo_mode":      mode == "demo_safe",
            "demo_show_log":  bc.get("demo_show_log",  False),
            "demo_watermark": bc.get("demo_watermark", ""),
        }

    # Whitelist lệnh an toàn cho demo — interviewer thấy được làm gì
    _DEMO_WHITELIST = [
        # Xem thông tin máy
        ("Get-ComputerInfo",         "Thông tin máy tính"),
        ("Get-Date",                  "Xem ngày giờ hiện tại"),
        ("Get-Volume",                "Xem ổ đĩa"),
        ("Get-Process",               "Xem tiến trình đang chạy"),
        ("Get-WifiNetworkReport",     "Báo cáo WiFi"),
        # Mở ứng dụng phổ biến
        ("notepad.exe",               "Mở Notepad"),
        ("calc.exe",                  "Mở Calculator"),
        ("mspaint.exe",               "Mở Paint"),
        ("explorer.exe",              "Mở File Explorer"),
        # Thao tác file an toàn (chỉ trong Public)
        ("New-Item.*Public",          "Tạo file/folder trong Public"),
        ("Get-ChildItem.*Public",     "Xem thư mục Public"),
        ("Remove-Item.*Public",       "Xoá file trong Public"),
        # Thông báo
        ("msg.*\\*",                  "Gửi thông báo popup"),
        # Volume
        ("Set-AudioDevice",           "Điều chỉnh âm thanh"),
    ]

    @staticmethod
    def _is_whitelisted(cmd: str) -> tuple:
        """Trả về (ok, mô tả lệnh). ok=False nếu không trong whitelist."""
        import re
        for pattern, desc in FlaskServerThread._DEMO_WHITELIST:
            if re.search(pattern, cmd, re.IGNORECASE):
                return True, desc
        return False, ""

    # ── Flask app factory ────────────────────────────────────────────────────

    def _make_app(self):
        if not _FLASK_OK:
            return None
        app = _Flask("PentaKuRu")
        app.logger.disabled = True
        import logging
        logging.getLogger("werkzeug").setLevel(logging.ERROR)

        chk  = self._check_token
        dcfg = self._load_exec_policy()
        is_demo     = dcfg.get("demo_mode", False)
        show_log    = dcfg.get("demo_show_log", False)
        watermark   = dcfg.get("demo_watermark", "")
        exec_mode   = dcfg.get("execution_mode", "full")
        use_tailscale = bool(self.data_manager.server_config.get("use_tailscale", True))
        allow_lan = bool(self.data_manager.server_config.get("allow_lan", False))
        prefer_tailscale = bool(self.data_manager.server_config.get("prefer_tailscale", True))
        controller_mode = str(self.data_manager.server_config.get("controller_mode", "default_server_only"))
        default_controller = str(self.data_manager.server_config.get("default_controller", "penta_ai"))
        allow_teamviewer = bool(self.data_manager.server_config.get("allow_teamviewer_control", True))
        lan_ip = SystemUtils.get_lan_ip()
        port = self.data_manager.server_config.get("port", 7777)

        # Log buffer cho demo window
        _log: list = []

        def _demo_log(action: str, detail: str, ok: bool = True):
            import datetime
            ts    = datetime.datetime.now().strftime("%H:%M:%S")
            color = "✅" if ok else "❌"
            entry = f"[{ts}] {color} {action}: {detail}"
            _log.append(entry)
            print(entry)
            # Hiện popup notification nhỏ trên máy interviewer
            if show_log:
                try:
                    PSExecutor.run(
                        f'Add-Type -AssemblyName System.Windows.Forms; '
                        f'[System.Windows.Forms.MessageBox]::Show("{entry}", '
                        f'"PentaKuRu Demo Log", '
                        f'"OK", "Information") | Out-Null'
                    )
                except Exception:
                    pass

        # ── /ping ─────────────────────────────────────────────────────────────
        @app.route("/ping", methods=["GET"])
        def ping():
            return _jsonify({
                "pong": True, "app": "PentaKuRu",
                "demo_mode": is_demo,
                "execution_mode": exec_mode,
                "use_tailscale": use_tailscale,
                "allow_lan": allow_lan,
                "prefer_tailscale": prefer_tailscale,
                "controller_mode": controller_mode,
                "default_controller": default_controller,
                "lan_url": f"http://{lan_ip}:{port}" if allow_lan else "",
                "teamviewer_control": allow_teamviewer,
                "watermark": watermark,
            })

        # ── /capabilities ─────────────────────────────────────────────────────
        @app.route("/capabilities", methods=["GET"])
        def capabilities():
            return _jsonify({
                "ok": True,
                "execution_mode": exec_mode,
                "supports": ["cmd", "script", "powershell", "install", "document", "gui_apps"] + (["teamviewer"] if allow_teamviewer else []),
                "network": {
                    "use_tailscale": use_tailscale,
                    "allow_lan": allow_lan,
                    "prefer_tailscale": prefer_tailscale,
                    "lan_url": f"http://{lan_ip}:{port}" if allow_lan else "",
                    "tailscale_ip": self.data_manager.server_config.get("tailscale_ip", ""),
                },
                "controller_mode": controller_mode,
                "default_controller": default_controller,
                "notes": "execution_mode=full cho phep thuc thi toan dien qua /run; teamviewer co the duoc dieu khien nhu mot ung dung neu duoc cai dat"
            })

        # ── /execution_mode ───────────────────────────────────────────────────
        @app.route("/execution_mode", methods=["POST"])
        def execution_mode():
            if not chk(_flask_req):
                return _jsonify({"ok": False, "error": "Unauthorized"}), 401
            data = _flask_req.get_json(force=True, silent=True) or {}
            mode = str(data.get("mode", "")).strip().lower()
            if mode not in {"full", "demo_safe"}:
                return _jsonify({"ok": False, "error": "mode phai la 'full' hoac 'demo_safe'"}), 400
            self.data_manager.server_config["execution_mode"] = mode
            self.data_manager.save_server_config()
            return _jsonify({"ok": True, "execution_mode": mode, "restart_required": True})

        # ── /run ──────────────────────────────────────────────────────────────
        @app.route("/run", methods=["POST"])
        def run_cmd():
            if not chk(_flask_req):
                return _jsonify({"ok": False, "error": "Unauthorized"}), 401
            data   = _flask_req.get_json(force=True, silent=True) or {}
            cmd    = data.get("cmd",    "").strip()
            script = data.get("script", "").strip()

            # ── Demo mode: kiểm tra whitelist ─────────────────────────────────
            if is_demo:
                check_text = cmd or (script[:200] if script else "")
                allowed, desc = self._is_whitelisted(check_text)
                if not allowed:
                    _demo_log("BLOCKED", check_text[:60], ok=False)
                    return _jsonify({
                        "ok":    False,
                        "error": "Demo mode: lệnh này không có trong whitelist an toàn.",
                        "hint":  "Chỉ các lệnh xem thông tin và mở app cơ bản được phép.",
                    }), 403

            # ── Thực thi ──────────────────────────────────────────────────────
            if script:
                print(f"[PS:script] {len(script)} chars")
                result = PSExecutor.run_script(script)
                _demo_log("Script", f"{len(script)} chars → ok={result['ok']}")
            elif cmd:
                print(f"[PS:cmd] {cmd[:80]!r}")
                result = PSExecutor.run(cmd)
                _demo_log("Cmd", f"{cmd[:50]} → ok={result['ok']}")
            else:
                return _jsonify({"ok": False, "error": "Cần 'cmd' hoặc 'script'"}), 400

            return _jsonify(result)

        # ── /ls ───────────────────────────────────────────────────────────────
        @app.route("/ls", methods=["POST"])
        def ls():
            if not chk(_flask_req): return _jsonify({"ok": False, "error": "Unauthorized"}), 401
            data = _flask_req.get_json(force=True, silent=True) or {}
            path = data.get("path", r"C:\Users\Public\Documents")
            result = PSExecutor.run(
                f"Get-ChildItem -Path '{path}' | "
                f"Select-Object Name, PSIsContainer, Length, LastWriteTime | "
                f"ConvertTo-Json -Depth 2"
            )
            _demo_log("ls", path)
            return _jsonify(result)

        # ── /mkdir ────────────────────────────────────────────────────────────
        @app.route("/mkdir", methods=["POST"])
        def mkdir():
            if not chk(_flask_req): return _jsonify({"ok": False, "error": "Unauthorized"}), 401
            data = _flask_req.get_json(force=True, silent=True) or {}
            path = data.get("path", "")
            if not path: return _jsonify({"ok": False, "error": "Cần 'path'"}), 400
            result = PSExecutor.run(
                f"New-Item -ItemType Directory -Force -Path '{path}' | "
                f"Select-Object -ExpandProperty FullName"
            )
            _demo_log("mkdir", path)
            return _jsonify(result)

        # ── /demo_log — interviewer có thể xem lịch sử lệnh ──────────────────
        @app.route("/demo_log", methods=["GET"])
        def demo_log():
            """Không cần auth — interviewer mở browser thấy log."""
            html = f"""<html><head>
<meta http-equiv="refresh" content="3">
<style>
  body{{background:#0d0d14;color:#e0e0f0;font-family:monospace;padding:20px;}}
  h2{{color:#c0a0ff;}} .ok{{color:#4dffb4;}} .err{{color:#ff8888;}}
  .wm{{color:#606090;font-size:11px;margin-bottom:16px;}}
</style></head><body>
<h2>PentaKuRu — Demo Live Log</h2>
<div class="wm">{watermark}</div>
<div class="wm">Trang này tự reload mỗi 3 giây. Mọi lệnh từ Mac mini đều hiện ở đây.</div>
<hr style="border-color:#333;margin:12px 0">
{'<br>'.join(
    f'<span class="{"ok" if "✅" in e else "err"}">{e}</span>'
    for e in reversed(_log[-30:])
) or '<span style="color:#555">Chưa có lệnh nào...</span>'}
</body></html>"""
            from flask import Response
            return Response(html, mimetype="text/html")

        # ── /uninstall — interviewer tự gỡ sau khi phỏng vấn ─────────────────
        @app.route("/uninstall", methods=["POST"])
        def uninstall():
            if not chk(_flask_req): return _jsonify({"ok": False, "error": "Unauthorized"}), 401
            # Tạo script tự xoá trong %TEMP% rồi chạy sau khi app tắt
            import tempfile, os as _os
            exe = sys.executable if getattr(sys, "frozen", False) else "python"
            app_dir = _os.path.dirname(sys.executable if getattr(sys,"frozen",False)
                                       else _os.path.abspath(__file__))
            script = f"""
@echo off
timeout /t 3 /nobreak > nul
rd /s /q "{app_dir}" 2>nul
powershell -Command "Remove-MpPreference -ExclusionPath '{app_dir}' -ErrorAction SilentlyContinue" > nul 2>&1
del "%~f0"
"""
            fd, tmp = tempfile.mkstemp(suffix=".bat", prefix="penta_uninstall_")
            with _os.fdopen(fd, "w") as f:
                f.write(script)
            subprocess.Popen(["cmd", "/c", tmp],
                             creationflags=subprocess.CREATE_NO_WINDOW)
            QTimer.singleShot(1000, QApplication.instance().quit)
            return _jsonify({"ok": True, "msg": "App sẽ tự xoá trong 3 giây."})

        return app

    # ── QThread.run ──────────────────────────────────────────────────────────

    def run(self):
        if not _FLASK_OK:
            self.status_changed.emit("error:Flask not installed")
            return
        app = self._make_app()
        port = self.data_manager.server_config.get("port", 7777)
        bind_host = "0.0.0.0" if (self.data_manager.server_config.get("use_tailscale", True) or self.data_manager.server_config.get("allow_lan", False)) else "127.0.0.1"
        self._running = True
        self.status_changed.emit("running")
        print(f"[FlaskServer] Starting on {bind_host}:{port}")
        try:
            from werkzeug.serving import make_server
            self._server = make_server(bind_host, port, app)
            self._server.serve_forever()
        except OSError as e:
            self.status_changed.emit(f"error:{e}")
            print(f"[FlaskServer] {e}")
        finally:
            self._running = False
            self.status_changed.emit("stopped")

    def stop_server(self):
        if self._server:
            self._server.shutdown()
        self._running = False


# ══════════════════════════════════════════════════════════════════════════════
#  TAILSCALE MANAGER  — quản lý kết nối Tailscale
# ══════════════════════════════════════════════════════════════════════════════

class TailscaleManager(QObject):
    """
    Tích hợp Tailscale cho remote access.
    • Tìm tailscale.exe (bundle, cạnh exe, hoặc PATH)
    • Lấy Tailscale IP của máy (100.x.x.x)
    • Không cần token tunnel — Tailscale tự xác thực qua mạng VPN của nó
    • Flask server bind 0.0.0.0 nên có thể truy cập qua Tailscale IP

    Cách dùng:
      - Cài Tailscale trên Windows: https://tailscale.com/download/windows
      - Đăng nhập Tailscale một lần: tailscale.exe up
      - Các thiết bị khác trong mạng Tailscale truy cập: http://<IP>:7777/run
    """

    status_changed = Signal(str)   # "running:<ip>" | "stopped" | "no_exe" | "not_connected"

    def __init__(self, data_manager: "DataManager", parent=None):
        super().__init__(parent)
        self.data_manager  = data_manager
        self._running      = False
        self._tailscale_ip = ""
        self._poll_timer: Optional[QTimer] = None

    # ── Locate tailscale.exe ─────────────────────────────────────────────────

    @staticmethod
    def find_exe() -> Optional[str]:
        """
        Tìm theo thứ tự:
        1. _MEIPASS (PyInstaller bundle)
        2. Cạnh file .exe / .py
        3. PATH hệ thống
        4. Vị trí cài đặt mặc định của Tailscale trên Windows
        """
        mei = getattr(sys, "_MEIPASS", None)
        if mei:
            p = os.path.join(mei, "tailscale.exe")
            if os.path.exists(p):
                return p

        base = (os.path.dirname(sys.executable)
                if getattr(sys, "frozen", False)
                else os.path.dirname(os.path.abspath(__file__)))
        p = os.path.join(base, "tailscale.exe")
        if os.path.exists(p):
            return p

        # Vị trí mặc định Tailscale cài trên Windows
        for default in [
            r"C:\Program Files\Tailscale\tailscale.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\Tailscale\tailscale.exe"),
        ]:
            if os.path.exists(default):
                return default

        # PATH hệ thống
        try:
            r = subprocess.run(["where", "tailscale"], capture_output=True, text=True,
                               timeout=3)
            if r.returncode == 0:
                return r.stdout.strip().splitlines()[0]
        except Exception:
            pass

        return None

    # ── Lấy Tailscale IP ────────────────────────────────────────────────────

    @staticmethod
    def get_tailscale_ip(exe: Optional[str] = None) -> Optional[str]:
        """
        Trả về địa chỉ Tailscale IP (100.x.x.x) của máy hiện tại.
        Thử qua lệnh `tailscale ip` trước, fallback sang `tailscale status --json`.
        """
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE

        candidates = []
        if exe:
            candidates.append(exe)
        candidates += ["tailscale"]

        for cmd in candidates:
            # Method 1: tailscale ip -4
            try:
                r = subprocess.run([cmd, "ip", "-4"], capture_output=True, text=True,
                                   timeout=5, startupinfo=si)
                ip = r.stdout.strip()
                if ip and ip.startswith("100."):
                    return ip
            except Exception:
                pass

            # Method 2: tailscale status --json
            try:
                r = subprocess.run([cmd, "status", "--json"], capture_output=True,
                                   text=True, timeout=5, startupinfo=si)
                if r.returncode == 0 and r.stdout.strip():
                    data = json.loads(r.stdout)
                    self_node = data.get("Self", {})
                    ips = self_node.get("TailscaleIPs", [])
                    for ip in ips:
                        if ip.startswith("100."):
                            return ip
            except Exception:
                pass

        return None

    @staticmethod
    def check_connected(exe: Optional[str] = None) -> bool:
        """Kiểm tra Tailscale đang kết nối hay không."""
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE

        candidates = []
        if exe:
            candidates.append(exe)
        candidates += ["tailscale"]

        for cmd in candidates:
            try:
                r = subprocess.run([cmd, "status"], capture_output=True, text=True,
                                   timeout=5, startupinfo=si)
                # Kết nối OK nếu output có chứa địa chỉ 100.x.x.x hoặc không có "Logged out"
                out = r.stdout + r.stderr
                if "Logged out" in out or "not logged in" in out.lower():
                    return False
                if "100." in out or r.returncode == 0:
                    return True
            except Exception:
                pass

        return False

    # ── Start / Stop ─────────────────────────────────────────────────────────

    def start_tunnel(self):
        """Kiểm tra Tailscale và bắt đầu poll IP định kỳ."""
        exe = self.find_exe()
        if not exe:
            self.status_changed.emit("no_exe")
            print("[Tailscale] tailscale.exe không tìm thấy!")
            return

        self._running = True
        self._exe = exe
        print(f"[Tailscale] Tìm thấy exe: {exe}")
        print(f"[Tailscale] Flask đang lắng nghe 0.0.0.0 — Tailscale IP sẽ được detect...")

        # Chạy lần đầu ngay lập tức trong thread riêng
        t = threading.Thread(target=self._initial_check, daemon=True, name="TailscaleInit")
        t.start()

        # Poll mỗi 30 giây để cập nhật IP (gắn parent=self để sống đúng thread)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(30_000)
        self._poll_timer.timeout.connect(self._poll_status)
        self._poll_timer.start()

    def _initial_check(self):
        exe = getattr(self, "_exe", None)
        if not self.check_connected(exe):
            print("[Tailscale] Chưa kết nối — hãy chạy 'tailscale up' để đăng nhập.")
            self.status_changed.emit("not_connected")
            return

        ip = self.get_tailscale_ip(exe)
        if ip:
            self._tailscale_ip = ip
            # Lưu IP vào config để UI hiển thị
            self.data_manager.server_config["tailscale_ip"] = ip
            self.data_manager.save_server_config()
            print(f"[Tailscale] Kết nối OK — IP: {ip}")
            self.status_changed.emit(f"running:{ip}")
        else:
            self.status_changed.emit("not_connected")

    def _poll_status(self):
        if not self._running:
            return
        exe = getattr(self, "_exe", None)
        t = threading.Thread(target=self._initial_check, daemon=True, name="TailscalePoll")
        t.start()

    def stop_tunnel(self):
        self._running = False
        if self._poll_timer:
            self._poll_timer.stop()
            self._poll_timer = None
        self.status_changed.emit("stopped")
        print("[Tailscale] Manager dừng.")

    def is_running(self) -> bool:
        return self._running and bool(self._tailscale_ip)

    def get_ip(self) -> str:
        return self._tailscale_ip


# ══════════════════════════════════════════════════════════════════════════════
#  BROWSER TRACKER THREAD  (BUG FIX #4: thread-safe URL stabilizer)
# ══════════════════════════════════════════════════════════════════════════════

class BrowserTracker(QThread):
    url_found = Signal(int, str)

    BLOCK_PATTERNS = [
        "youtube.com/shorts", "youtube.com/feed", "youtube.com/results",
        "youtube.com/@", "facebook.com/reel", "facebook.com/watch/?",
        "facebook.com/", "tiktok.com", "instagram.com/reel",
    ]
    STABLE_TIME = 2.0

    def __init__(self, data_manager: DataManager, app_state: AppState):
        super().__init__()
        self.data_manager = data_manager
        self.app_state    = app_state
        self.running      = True

        # BUG FIX #4: guard all URL stabilizer state with a lock
        self._url_lock      = threading.Lock()
        self._pending_url   = None
        self._pending_time  = 0
        self._confirmed_url = None
        self._last_emit     = 0
        self._last_emit_url = None

        self.cdp_tracker: Optional[ChromeDevToolsTracker] = None
        try:
            self.cdp_tracker = ChromeDevToolsTracker(data_manager, app_state)
        except Exception as e:
            print(f"[Tracker] CDP init failed: {e}")

    def run(self):
        if not auto and not self.cdp_tracker:
            print("[Tracker] No tracking backend available.")
            return
        print("[Tracker] started")
        while self.running:
            self.msleep(500)
            try:
                if self.cdp_tracker:
                    self._check_cdp()
                if auto:
                    self._check_uia()
            except Exception as e:
                print(f"[Tracker] error: {e}")

    def _check_cdp(self):
        for sector_idx, _ in list(self.app_state.bound_windows.items()):
            gi   = self.app_state.get_global_sector_index(sector_idx)
            sd   = self.data_manager.get_sector_data(gi)
            if not sd.enable_tracking:
                continue
            with self.cdp_tracker._ws_lock:
                connected = sector_idx in self.cdp_tracker.ws_connections
            if not connected and sd.url:
                self.cdp_tracker.track_sector(sector_idx, sd.url)
            url = self.cdp_tracker.get_tab_url(sector_idx)
            if url:
                self._process_url(sector_idx, url, sd, gi)

    def _check_uia(self):
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        matched = next(
            (i for i, h in self.app_state.bound_windows.items() if h == hwnd), None
        )
        if matched is None:
            return
        gi = self.app_state.get_global_sector_index(matched)
        sd = self.data_manager.get_sector_data(gi)
        if not sd.enable_tracking:
            return
        url = self._get_url_uia(hwnd)
        if url and any(p in url for p in self.BLOCK_PATTERNS):
            return
        if url and url.startswith("http"):
            self._process_url(matched, url, sd, gi)

    def _process_url(self, sector_idx, new_url, sector_data, global_idx):
        """BUG FIX #4: entire method now protected by _url_lock."""
        now = time.time()
        with self._url_lock:
            # Fast-track: URL changed and 0.5s debounce elapsed
            if new_url != self._confirmed_url:
                if now - self._last_emit >= 0.5:
                    sector_data.url = new_url
                    self.data_manager.update_sector_data(global_idx, sector_data)
                    self._confirmed_url  = new_url
                    self._last_emit_url  = new_url
                    self._last_emit      = now
                    self.url_found.emit(sector_idx, new_url)
                    return

            if new_url != self._pending_url:
                self._pending_url  = new_url
                self._pending_time = now
                return

            if (now - self._pending_time >= self.STABLE_TIME
                    and new_url != self._confirmed_url):
                sector_data.url = new_url
                self.data_manager.update_sector_data(global_idx, sector_data)
                self._confirmed_url  = new_url
                self._last_emit_url  = new_url
                self._last_emit      = now
                self.url_found.emit(sector_idx, new_url)

    def _get_url_uia(self, hwnd) -> Optional[str]:
        if not auto:
            return None
        try:
            win = auto.ControlFromHandle(hwnd)
            minimized = ctypes.windll.user32.IsIconic(hwnd)
            if minimized:
                ctypes.windll.user32.ShowWindow(hwnd, 9)
                time.sleep(0.05)
                win = auto.ControlFromHandle(hwnd)
            for name in ("Address and search bar", "Thanh địa chỉ và tìm kiếm"):
                bar = win.EditControl(Name=name)
                if bar.Exists(0, 0):
                    url = bar.GetValuePattern().Value
                    if minimized:
                        ctypes.windll.user32.ShowWindow(hwnd, 6)
                    return url
            if minimized:
                ctypes.windll.user32.ShowWindow(hwnd, 6)
        except Exception:
            pass
        return None

    def bind_via_cdp(self, sector_idx: int, initial_url: str):
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if hwnd:
            self.app_state.bound_windows[sector_idx] = hwnd
        if self.cdp_tracker and initial_url:
            QTimer.singleShot(1000, lambda: self.cdp_tracker.track_sector(sector_idx, initial_url))

    def stop(self):
        self.running = False
        if self.cdp_tracker:
            self.cdp_tracker.cleanup()
        self.wait()


# ══════════════════════════════════════════════════════════════════════════════
#  MOUSE BUTTON HOOK  — MB4 / MB5 / MB6  (BUG FIX #8: correct thread ID)
# ══════════════════════════════════════════════════════════════════════════════

class MouseButtonHook(QObject):
    """
    WH_MOUSE_LL low-level hook — thread-safe version.

    • MB4/5/6 → mb_pressed(int) signal
    • Click ngoài launcher → outside_clicked() signal  (debounced 200ms)

    Thiết kế thread-safe:
    - Hook chạy trong daemon thread riêng
    - Giao tiếp với main thread HOÀN TOÀN qua Qt signals (Qt tự marshal cross-thread)
    - Rect cache là Python tuple (gán tuple là atomic trong CPython)
    - KHÔNG dùng QTimer.singleShot từ hook thread (deadlock)
    - KHÔNG gọi Qt GUI API từ hook thread
    """
    mb_pressed      = Signal(int)   # 4 | 5 | 6
    outside_clicked = Signal()      # click ngoài launcher

    WH_MOUSE_LL    = 14
    WM_XBUTTONDOWN = 0x020B
    WM_LBUTTONDOWN = 0x0201
    WM_RBUTTONDOWN = 0x0204
    DEBOUNCE_SEC   = 0.20           # tránh fire liên tục

    def __init__(self, callback: Callable[[int], None],
                 outside_hide_cb: Optional[Callable[[], None]] = None,
                 get_window_rect: Optional[Callable[[], Optional[tuple]]] = None,
                 parent=None):
        super().__init__(parent)
        # Legacy callback wiring
        self.mb_pressed.connect(callback)
        if outside_hide_cb:
            self.outside_clicked.connect(outside_hide_cb)

        # _rect_cache: (x, y, w, h) nếu cửa sổ đang hiện, None nếu ẩn
        # Cập nhật từ main thread, đọc từ hook thread — tuple assign là atomic
        self._rect_cache: Optional[tuple] = None
        self._last_outside = 0.0        # timestamp lần fire cuối (debounce)

        self._thread: Optional[threading.Thread] = None
        self._running  = False
        self._hook_tid = 0

    # ── Cập nhật rect từ main thread (gọi bằng QTimer) ───────────────────────
    def update_rect(self, rect: Optional[tuple]):
        """Gọi từ main thread để cập nhật vùng cửa sổ an toàn."""
        self._rect_cache = rect

    def start(self):
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True, name="MouseHook")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._hook_tid:
            ctypes.windll.user32.PostThreadMessageW(self._hook_tid, 0x0012, 0, 0)

    def _loop(self):
        user32   = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._hook_tid = kernel32.GetCurrentThreadId()

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class MSLL(ctypes.Structure):
            _fields_ = [
                ("pt",        POINT),
                ("mouseData", ctypes.c_ulong),
                ("flags",     ctypes.c_ulong),
                ("time",      ctypes.c_ulong),
                ("dwExtra",   ctypes.POINTER(ctypes.c_ulong)),
            ]

        HOOKPROC = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_int, ctypes.c_ulong, ctypes.POINTER(MSLL)
        )

        def _proc(nCode, wParam, lParam):
            if nCode >= 0:
                if wParam == self.WM_XBUTTONDOWN:
                    try:
                        xbtn = (lParam.contents.mouseData >> 16) & 0xFFFF
                        if 1 <= xbtn <= 3:
                            self.mb_pressed.emit(xbtn + 3)  # 1→4, 2→5, 3→6
                    except Exception:
                        pass

                elif wParam in (self.WM_LBUTTONDOWN, self.WM_RBUTTONDOWN):
                    # Đọc rect_cache (atomic read — không cần lock)
                    rect = self._rect_cache
                    if rect is not None:
                        try:
                            mx = lParam.contents.pt.x
                            my = lParam.contents.pt.y
                            rx, ry, rw, rh = rect
                            outside = not (rx <= mx <= rx + rw and ry <= my <= ry + rh)
                            if outside:
                                now = time.monotonic()
                                if now - self._last_outside >= self.DEBOUNCE_SEC:
                                    self._last_outside = now
                                    # Signal emission từ thread là SAFE trong Qt
                                    self.outside_clicked.emit()
                        except Exception:
                            pass

            return user32.CallNextHookEx(
                self._hook, nCode, wParam,
                ctypes.cast(lParam, ctypes.c_void_p)
            )

        self._proc = HOOKPROC(_proc)

        user32.SetWindowsHookExW.restype  = ctypes.c_void_p
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong
        ]
        user32.CallNextHookEx.restype       = ctypes.c_long
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]

        self._hook = user32.SetWindowsHookExW(
            self.WH_MOUSE_LL, self._proc,
            None,  # hmod PHẢI NULL cho WH_MOUSE_LL
            0
        )
        if not self._hook:
            print(f"[MouseHook] failed (error {ctypes.GetLastError()})")
            return
        print("[MouseHook] MB4/MB5/MB6 + auto-hide active")

        msg = ctypes.wintypes.MSG()
        while self._running:
            r = user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)
            if r:
                if msg.message == 0x0012:  # WM_QUIT
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.005)

        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None


# ══════════════════════════════════════════════════════════════════════════════
#  FILE SCANNER THREAD
# ══════════════════════════════════════════════════════════════════════════════

class FileEntry:
    __slots__ = ("path", "name", "ext", "mtime", "is_folder")

    def __init__(self, path: str, name: str, ext: str, mtime: float, is_folder: bool = False, **_):
        self.path      = path;  self.name = name
        self.ext       = ext;   self.mtime = mtime
        self.is_folder = is_folder

    @property
    def age_category(self) -> str:
        d = time.time() - self.mtime
        if d < 86_400:    return "today"
        if d < 604_800:   return "week"
        if d < 2_592_000: return "month"
        return "older"

    def to_dict(self) -> dict:
        return {"path": self.path, "name": self.name, "ext": self.ext,
                "mtime": self.mtime, "is_folder": self.is_folder}


class FileScannerThread(QThread):
    """
    Quét file nền khi app khởi động.
    Load cache tức thì → scan → ghi cache mới.
    BUG FIX #9: mỗi thư mục có try/except riêng để không crash vì Permission.
    """
    scan_complete = Signal(int)
    scan_progress = Signal(str)

    SCAN_DIRS = [
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~/Downloads"),
        os.path.expanduser("~/Pictures"),
        os.path.expanduser("~/Videos"),
        os.path.expanduser("~/Music"),
        r"C:\Program Files",
        r"C:\Program Files (x86)",
    ]
    ALLOWED_EXT = {
        ".exe", ".lnk", ".url",
        ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".txt",
        ".mp4", ".mkv", ".avi", ".mov", ".mp3", ".flac", ".wav", ".aac",
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg",
        ".zip", ".rar", ".7z",
        ".py", ".js", ".ts", ".json", ".html", ".css",
    }
    # Thư mục top-level từ các dir quen thuộc sẽ được quét riêng
    FOLDER_SCAN_DIRS = [
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~/Downloads"),
    ]
    SKIP_DIRS = {"$RECYCLE.BIN", "Windows", "System32", "SysWOW64",
                 "__pycache__", "node_modules", ".git"}
    MAX_FILES = 50_000

    def __init__(self, cache_path: str, parent=None):
        super().__init__(parent)
        self.cache_path = cache_path
        self._running   = True
        self._lock      = threading.Lock()
        self._entries: List[FileEntry] = []

    def run(self):
        entries: List[FileEntry] = []

        # ── 1. Quét các thư mục con cấp 1 (Desktop / Documents / Downloads)
        for base in self.FOLDER_SCAN_DIRS:
            if not self._running: break
            if not os.path.isdir(base): continue
            try:
                for fname in os.listdir(base):
                    fp = os.path.join(base, fname)
                    if os.path.isdir(fp) and not fname.startswith("."):
                        try:
                            entries.append(FileEntry(fp, fname, ".folder",
                                                     os.stat(fp).st_mtime, is_folder=True))
                        except OSError:
                            pass
            except (OSError, PermissionError):
                pass

        # ── 2. Quét file theo SCAN_DIRS
        for base in self.SCAN_DIRS:
            if not self._running or len(entries) >= self.MAX_FILES:
                break
            if not os.path.isdir(base):
                continue
            try:
                self.scan_progress.emit(base)
                for root, dirs, files in os.walk(base, topdown=True):
                    if not self._running or len(entries) >= self.MAX_FILES:
                        break
                    dirs[:] = [d for d in dirs
                                if d not in self.SKIP_DIRS and not d.startswith(".")]
                    for fname in files:
                        ext = os.path.splitext(fname)[1].lower()
                        if ext not in self.ALLOWED_EXT:
                            continue
                        fp = os.path.join(root, fname)
                        try:
                            entries.append(FileEntry(fp, fname, ext, os.stat(fp).st_mtime))
                        except OSError:
                            continue
            except (OSError, PermissionError):
                continue  # BUG FIX #9: silently skip inaccessible roots

        with self._lock:
            self._entries = entries
        self._save_cache(entries)
        self.scan_complete.emit(len(entries))
        print(f"[FileScanner] {len(entries):,} files indexed")

    def _save_cache(self, entries: List[FileEntry]):
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump([e.to_dict() for e in entries], f, ensure_ascii=False)
        except Exception as ex:
            print(f"[FileScanner] cache save: {ex}")

    def load_cache(self) -> List[FileEntry]:
        if not os.path.exists(self.cache_path):
            return []
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                return [FileEntry(**d) for d in json.load(f)]
        except Exception as ex:
            print(f"[FileScanner] cache load: {ex}")
            return []

    def get_entries(self) -> List[FileEntry]:
        with self._lock:
            return list(self._entries)

    def stop(self):
        self._running = False


# ══════════════════════════════════════════════════════════════════════════════
#  WINDOW ENUMERATOR
# ══════════════════════════════════════════════════════════════════════════════

# WindowEntry / WindowEnumerator removed — Find Window mode đã được xóa.


# ══════════════════════════════════════════════════════════════════════════════
#  SEARCH MODE CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

class SearchMode:
    GOOGLE  = "google"
    PENTAKU = "pentaku"
    FILES   = "files"
    CYCLE   = [GOOGLE, PENTAKU, FILES]
    PLACEHOLDER = {
        GOOGLE:  "Tìm trên Google...",
        PENTAKU: "Tìm trong PentaKu...",
        FILES:   "Tìm file / thư mục...  (click ⬠ để lọc)",
    }
    DOT_COLOR = {
        GOOGLE:  "rgba(255,255,255,50)",
        PENTAKU: "rgba(100,210,255,180)",
        FILES:   "rgba(100,255,160,180)",
    }


# ══════════════════════════════════════════════════════════════════════════════
#  FILTER PANEL
# ══════════════════════════════════════════════════════════════════════════════

class FilterPanel(QFrame):
    filter_changed = Signal()

    _TIME = [("Tất cả", "all"), ("Hôm nay", "today"),
             ("Tuần này", "week"), ("Tháng này", "month")]
    _TYPE = [("Tất cả", "all"), ("App", "app"), ("Tài liệu", "doc"),
             ("PDF", "pdf"), ("Zip", "zip"), ("Thư mục", "folder"),
             ("Ảnh", "image"), ("Video", "video"), ("Nhạc", "audio"), ("Code", "code")]
    _EXT: Dict[str, set] = {
        "app":    {".exe", ".lnk"},
        "doc":    {".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".txt"},
        "pdf":    {".pdf"},
        "zip":    {".zip", ".rar", ".7z"},
        "folder": {".folder"},
        "image":  {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"},
        "video":  {".mp4", ".mkv", ".avi", ".mov"},
        "audio":  {".mp3", ".flac", ".wav", ".aac"},
        "code":   {".py", ".js", ".ts", ".json", ".html", ".css"},
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active_time = "all"
        self.active_type = "all"
        self._t_btns: Dict[str, QPushButton] = {}
        self._k_btns: Dict[str, QPushButton] = {}
        self._build()

    def _build(self):
        self.setStyleSheet(
            "FilterPanel,QFrame{background:rgba(18,18,18,245);border-radius:14px;"
            "border:1px solid rgba(255,255,255,15);}"
        )
        lo = QVBoxLayout(self)
        lo.setContentsMargins(14, 10, 14, 10); lo.setSpacing(6)
        lo.addWidget(self._sec("🕐  Thời gian"))
        row1 = QHBoxLayout(); row1.setSpacing(6)
        for lbl, key in self._TIME:
            b = self._chip(lbl, key, "time"); row1.addWidget(b); self._t_btns[key] = b
        row1.addStretch(); lo.addLayout(row1)
        lo.addWidget(self._sec("📁  Loại file"))
        row2 = QHBoxLayout(); row2.setSpacing(6)
        for lbl, key in self._TYPE:
            b = self._chip(lbl, key, "type"); row2.addWidget(b); self._k_btns[key] = b
        row2.addStretch(); lo.addLayout(row2)
        self._refresh("time"); self._refresh("type")

    def _sec(self, t):
        l = QLabel(t); l.setStyleSheet(
            "color:rgba(255,255,255,100);font-size:11px;font-weight:600;"
            "border:none;background:transparent;"); return l

    def _chip(self, lbl, key, grp):
        b = QPushButton(lbl); b.setFixedHeight(26); b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(self._css(False))
        b.clicked.connect(lambda _, k=key, g=grp: self._click(k, g)); return b

    @staticmethod
    def _css(active: bool) -> str:
        if active:
            return ("QPushButton{background:rgba(255,255,255,200);color:#111;"
                    "border-radius:9px;padding:0 10px;font-size:12px;font-weight:bold;border:none;}")
        return ("QPushButton{background:rgba(255,255,255,18);color:rgba(255,255,255,150);"
                "border-radius:9px;padding:0 10px;font-size:12px;border:none;}"
                "QPushButton:hover{background:rgba(255,255,255,35);color:white;}")

    def _click(self, key, grp):
        if grp == "time": self.active_time = key
        else:             self.active_type = key
        self._refresh(grp); self.filter_changed.emit()

    def _refresh(self, grp):
        btns   = self._t_btns if grp == "time" else self._k_btns
        active = self.active_time if grp == "time" else self.active_type
        for k, b in btns.items():
            b.setStyleSheet(self._css(k == active))

    def matches(self, e: FileEntry) -> bool:
        # Thư mục không lọc theo thời gian
        if self.active_time != "all" and not e.is_folder:
            if e.age_category != self.active_time:
                return False
        if self.active_type != "all":
            if e.ext not in self._EXT.get(self.active_type, set()):
                return False
        return True


# ══════════════════════════════════════════════════════════════════════════════
#  PENTAGON ICON WIDGET
# ══════════════════════════════════════════════════════════════════════════════

class PentagonIcon(QWidget):
    clicked = Signal()

    def __init__(self, size: int = 45, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        self._rotation = 0.0
        self._active   = False

    def get_rotation(self): return self._rotation
    def set_rotation(self, v: float):
        self._rotation = v; self.update()
    rotation = Property(float, get_rotation, set_rotation)

    def set_active(self, f: bool):
        if self._active != f:
            self._active = f; self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.translate(w / 2, h / 2); p.rotate(self._rotation); p.translate(-w / 2, -h / 2)
        stroke = QColor(100, 210, 255, 230) if self._active else QColor(255, 255, 255, 180)
        fill   = QColor(100, 210, 255, 55)  if self._active else QColor(255, 255, 255, 28)
        p.setPen(QPen(stroke, 2)); p.setBrush(QBrush(fill))
        rect = self.rect().adjusted(5, 5, -5, -5)
        r = rect.width() / 2; c = rect.center()
        poly = QPolygonF()
        for i in range(5):
            a = math.radians(i * 72 - 90)
            poly.append(QPoint(int(c.x() + r * math.cos(a)), int(c.y() + r * math.sin(a))))
        p.drawPolygon(poly)


# ══════════════════════════════════════════════════════════════════════════════
#  SEARCH UI WIDGET  (BUG FIX #5 #6 #11 #12)
# ══════════════════════════════════════════════════════════════════════════════

_FILE_ICON: Dict[str, str] = {
    **{e: "🎬" for e in (".mp4",".mkv",".avi",".mov")},
    **{e: "🎵" for e in (".mp3",".flac",".wav",".aac")},
    **{e: "🖼️" for e in (".jpg",".jpeg",".png",".gif",".webp",".bmp",".svg")},
    **{e: "📄" for e in (".docx",".doc",".txt")},
    **{e: "📊" for e in (".xlsx",".xls",".pptx",".ppt")},
    **{e: "💻" for e in (".py",".js",".ts",".html",".css",".json")},
    **{e: "📦" for e in (".zip",".rar",".7z")},
    ".pdf": "📕", ".exe": "⚙️", ".lnk": "🔗", ".url": "🌐",
    ".folder": "📁",
}


def _open_incognito(url: str):
    for path, arg in [
        (r"C:\Program Files\Google\Chrome\Application\chrome.exe", "--incognito"),
        (r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe", "--incognito"),
        (r"C:\Program Files\Microsoft\Edge\Application\msedge.exe", "-inprivate"),
    ]:
        if os.path.exists(path):
            try:
                subprocess.Popen([path, arg, url]); return
            except Exception:
                continue
    webbrowser.open(url)


class SearchUIWidget(QWidget):
    sectors_updated      = Signal()
    mouse_button_pressed = Signal(int)   # 4 | 5 | 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setContentsMargins(0, 0, 0, 0)

        self.data_manager: Optional[DataManager] = None
        self.sectors_data: Dict = {}
        self.search_mode = SearchMode.GOOGLE

        self.target_url:    Optional[str] = None
        self.target_exe:    Optional[str] = None
        self.use_incognito: bool          = False

        self._filter_visible  = False
        self._file_entries:   List[FileEntry]   = []

        self.sectors_data = self._load_sectors_from_disk()

        # BUG FIX #11: build UI FIRST, then center
        self._build_ui()

        cache_path = self._resolve_cache_path()
        self.file_scanner = FileScannerThread(cache_path, parent=self)
        cached = self.file_scanner.load_cache()
        if cached:
            self._file_entries = cached
            self._show_status(f"📂 {len(cached):,} files (đang cập nhật...)", 3000)
        self.file_scanner.scan_complete.connect(self._on_scan_done)
        self.file_scanner.start()

        self.mouse_hook = MouseButtonHook(self._on_mouse_btn, parent=self)
        self.mouse_hook.start()

        # BUG FIX #11: center AFTER setFixedWidth is applied
        self.center_on_screen()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setFixedWidth(800)
        ml = QVBoxLayout(self)
        ml.setContentsMargins(10, 10, 10, 10)
        ml.setSizeConstraint(QVBoxLayout.SetFixedSize)

        self.container = QFrame()
        self.container.setStyleSheet(
            "QFrame{background-color:rgb(0,0,0);border-radius:20px;border:none;}"
        )
        cl = QVBoxLayout(self.container)
        cl.setContentsMargins(10, 5, 10, 5); cl.setSpacing(0)

        # Search bar row
        sf = QFrame(); sf.setFixedHeight(70)
        row = QHBoxLayout(sf); row.setContentsMargins(0, 0, 0, 0)
        self.icon_pentagon = PentagonIcon(size=45)
        self.icon_pentagon.clicked.connect(self._on_penta_click)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(SearchMode.PLACEHOLDER[SearchMode.GOOGLE])
        self.search_input.setFont(QFont("Segoe UI Variable Display", 18))
        self.search_input.setStyleSheet(
            "QLineEdit{background:transparent;color:white;border:none;padding-left:15px;}"
        )
        self.mode_dot = QLabel("●")
        self.mode_dot.setFixedWidth(14); self.mode_dot.setAlignment(Qt.AlignCenter)
        self.mode_dot.setStyleSheet(
            f"color:{SearchMode.DOT_COLOR[SearchMode.GOOGLE]};"
            "font-size:7px;border:none;background:transparent;"
        )
        row.addWidget(self.icon_pentagon); row.addWidget(self.search_input); row.addWidget(self.mode_dot)
        cl.addWidget(sf)

        self.filter_panel = FilterPanel(self)
        self.filter_panel.filter_changed.connect(self._refresh_suggestions)
        self.filter_panel.hide()
        cl.addWidget(self.filter_panel)

        self.list_widget = QListWidget()
        self.list_widget.setFocusPolicy(Qt.NoFocus)
        self.list_widget.setStyleSheet("""
            QListWidget{background:transparent;border:none;outline:none;margin:5px;}
            QListWidget::item{padding:10px 12px;color:#CCC;border-radius:10px;
                              margin-bottom:2px;font-size:14px;}
            QListWidget::item:selected{background:rgba(255,255,255,30);color:white;font-weight:bold;}
            QListWidget::item:hover{background:rgba(255,255,255,10);}
        """)
        cl.addWidget(self.list_widget)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            "QLabel{color:rgba(255,255,255,55);font-size:11px;"
            "padding:4px 14px;border:none;background:transparent;}"
        )
        self.status_label.hide(); cl.addWidget(self.status_label)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(50); shadow.setColor(QColor(0, 0, 0, 200))
        self.container.setGraphicsEffect(shadow)
        ml.addWidget(self.container)

        self.search_input.textChanged.connect(self.update_suggestions)
        self.search_input.returnPressed.connect(self._handle_enter)
        self.list_widget.itemClicked.connect(self._handle_item_click)

    # ── DataManager bridge ────────────────────────────────────────────────────

    def set_data_manager(self, dm: DataManager):
        self.data_manager = dm
        self.update_sectors_data()

    def update_sectors_data(self):
        if not self.data_manager:
            return
        self.sectors_data = {}
        for idx, sd in self.data_manager.sector_data.items():
            self.sectors_data[str(idx)] = {
                "name": sd.name, "url": sd.url,
                "exe_path": sd.exe_path, "use_incognito": sd.use_incognito,
            }
        self.sectors_updated.emit()

    # BUG FIX #5: expose load_sectors as public alias for backward compat
    def load_sectors(self) -> Dict:
        return self._load_sectors_from_disk()

    # ── Scan callbacks ─────────────────────────────────────────────────────────

    @Slot(int)
    def _on_scan_done(self, count: int):
        self._file_entries = self.file_scanner.get_entries()
        self._show_status(f"✅ {count:,} files đã được index", 2000)
        if self.search_mode == SearchMode.FILES:
            self._refresh_suggestions()

    def _show_status(self, text: str, ms: int = 2000):
        self.status_label.setText(text); self.status_label.show(); self.adjustSize()
        QTimer.singleShot(ms, lambda: (self.status_label.hide(), self.adjustSize()))

    # ── Mode ──────────────────────────────────────────────────────────────────

    def _on_penta_click(self):
        if self.search_mode == SearchMode.FILES:
            self._toggle_filter()
        else:
            self._next_mode()

    def _next_mode(self):
        idx = SearchMode.CYCLE.index(self.search_mode)
        self.search_mode = SearchMode.CYCLE[(idx + 1) % len(SearchMode.CYCLE)]
        self._apply_mode()

    def _apply_mode(self):
        self.search_input.clear(); self.list_widget.clear(); self.list_widget.hide()
        self._hide_filter()
        self.search_input.setPlaceholderText(SearchMode.PLACEHOLDER[self.search_mode])
        self.mode_dot.setStyleSheet(
            f"color:{SearchMode.DOT_COLOR[self.search_mode]};"
            "font-size:7px;border:none;background:transparent;"
        )
        self.search_input.setFocus(); self.adjustSize()

    def _toggle_filter(self):
        self._filter_visible = not self._filter_visible
        self.filter_panel.setVisible(self._filter_visible)
        self.icon_pentagon.set_active(self._filter_visible)
        self.adjustSize()

    def _hide_filter(self):
        self._filter_visible = False
        self.filter_panel.hide()
        self.icon_pentagon.set_active(False)

    # ── Suggestions ───────────────────────────────────────────────────────────

    @Slot()
    def _refresh_suggestions(self):
        self.update_suggestions(self.search_input.text())

    def update_suggestions(self, text: str):
        text = text.strip(); self.list_widget.clear()
        mode = self.search_mode
        if mode == SearchMode.GOOGLE:
            self.list_widget.hide(); self.adjustSize(); return
        if not text:
            self.list_widget.hide(); self.adjustSize(); return

        found = False
        if   mode == SearchMode.PENTAKU: found = self._fill_sectors(text)
        elif mode == SearchMode.FILES:   found = self._fill_files(text)

        if found:
            self.list_widget.show(); self.list_widget.setCurrentRow(0)
            self.list_widget.setFixedHeight(min(self.list_widget.count() * 50, 420))
        else:
            self.list_widget.hide()
        self.adjustSize()

    def _fill_sectors(self, text: str) -> bool:
        tl = text.lower(); found = False
        for key, data in self.sectors_data.items():
            if tl in data.get("name", "").lower():
                item = QListWidgetItem(f"   {data['name']}")
                item.setData(Qt.UserRole, ("sector", key))
                self.list_widget.addItem(item); found = True
        return found

    def _fill_files(self, text: str) -> bool:
        tl = text.lower(); n = 0; MAX = 15
        for e in self._file_entries:
            if n >= MAX: break
            if tl and tl not in e.name.lower(): continue
            if not self.filter_panel.matches(e):  continue
            icon = _FILE_ICON.get(e.ext, "📂")
            date = datetime.fromtimestamp(e.mtime).strftime("%d/%m/%y")
            item = QListWidgetItem(f"  {icon}  {e.name}   •   {date}")
            item.setData(Qt.UserRole, ("file", e.path))
            item.setToolTip(e.path); self.list_widget.addItem(item); n += 1
        return n > 0

    # ── Execute ───────────────────────────────────────────────────────────────

    def _handle_enter(self):
        if self.list_widget.isVisible() and self.list_widget.currentItem():
            self._execute(self.list_widget.currentItem())
        elif self.search_mode == SearchMode.GOOGLE:
            self._start_anim()

    def _handle_item_click(self, item: QListWidgetItem):
        self._execute(item)

    def _execute(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole)
        if not data: return
        kind, value = data
        self.target_url = self.target_exe = None
        self.use_incognito = False
        if kind == "sector":
            sec = self.sectors_data.get(value, {})
            self.target_url    = sec.get("url") or None
            self.target_exe    = sec.get("exe_path") or None
            self.use_incognito = sec.get("use_incognito", False)
        elif kind == "file":
            self.target_exe = value
        self._start_anim()

    def _start_anim(self):
        self.anim_group = QParallelAnimationGroup()
        rot = QPropertyAnimation(self.icon_pentagon, b"rotation")
        rot.setDuration(1250); rot.setEndValue(360); rot.setEasingCurve(QEasingCurve.OutBack)
        fade = QPropertyAnimation(self, b"windowOpacity")
        fade.setDuration(400); fade.setStartValue(1.0); fade.setEndValue(0.0)
        self.anim_group.addAnimation(rot); self.anim_group.addAnimation(fade)
        self.anim_group.finished.connect(self._perform)
        self.anim_group.start()

    def _perform(self):
        query = self.search_input.text().strip()
        if self.target_url:
            _open_incognito(self.target_url) if self.use_incognito else webbrowser.open(self.target_url)
        elif self.target_exe:
            try: os.startfile(self.target_exe)
            except Exception as e: print(f"[SearchUI] open: {e}")
        elif query:
            _open_incognito(f"https://www.google.com/search?q={query}")
        self.target_url = self.target_exe = None
        self.use_incognito = False
        self.hide()

    # ── Show / hide ────────────────────────────────────────────────────────────

    def show_search(self):
        self.setWindowOpacity(1.0)
        self.search_input.clear(); self.list_widget.clear(); self.list_widget.hide()
        self._hide_filter()
        self.show(); self.raise_(); self.activateWindow()
        parent = self.parent()
        if parent and hasattr(parent, "app_state"):
            parent.app_state.last_text_active_time = time.time()
            parent.app_state.text_opacity = 1.0
            parent.update()
        QTimer.singleShot(50, self.search_input.setFocus)

    def center_on_screen(self):
        s = QApplication.primaryScreen().availableGeometry()
        self.move((s.width() - self.width()) // 2, s.height() // 5)

    # ── Keyboard ──────────────────────────────────────────────────────────────

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_Escape:
            self.hide(); return
        if k == Qt.Key_Tab:
            self._next_mode(); return
        if k in (Qt.Key_Down, Qt.Key_Up) and self.list_widget.isVisible():
            n = self.list_widget.count()
            if n:
                cur = self.list_widget.currentRow()
                new = (cur + 1) % n if k == Qt.Key_Down else (cur - 1) % n
                self.list_widget.setCurrentRow(new)
            return
        super().keyPressEvent(e)

    # ── MB4/5/6 ───────────────────────────────────────────────────────────────

    def _on_mouse_btn(self, btn: int):
        # hop to main thread safely
        QTimer.singleShot(0, lambda: self._mb_main(btn))

    def _mb_main(self, btn: int):
        print(f"[SearchUI] Mouse button {btn}")
        self.mouse_button_pressed.emit(btn)
        if btn == 4:
            idx = SearchMode.CYCLE.index(self.search_mode)
            self.search_mode = SearchMode.CYCLE[(idx - 1) % len(SearchMode.CYCLE)]
            if self.isVisible(): self._apply_mode()
        elif btn == 5:
            if self.isVisible(): self._next_mode()
        elif btn == 6:
            self.hide() if self.isVisible() else self.show_search()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _load_sectors_from_disk(self) -> Dict:
        if getattr(sys, "frozen", False):
            root = os.path.dirname(sys.executable)
        else:
            root = os.path.dirname(os.path.abspath(__file__))
        for sub in ("data", "memory"):
            p = os.path.join(root, sub, "sectors.json")
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
        return {}

    def _resolve_cache_path(self) -> str:
        if getattr(sys, "frozen", False):
            root = os.path.dirname(sys.executable)
        else:
            root = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(root, "data", "file_cache.json")

    # backward compat for old EventHandler call
    def toggle_search_mode(self):
        self._next_mode()

    # BUG FIX #6: expose placeholder constant so old code still compiles
    @property
    def PH_GOOGLE(self):
        return SearchMode.PLACEHOLDER[SearchMode.GOOGLE]

    def cleanup(self):
        if hasattr(self, "file_scanner"):
            self.file_scanner.stop()
        if hasattr(self, "mouse_hook"):
            self.mouse_hook.stop()


# ══════════════════════════════════════════════════════════════════════════════
#  UI COMPONENTS  (TriangleWidget, CenterCircleWidget, DropZoneWidget,
#                  UrlUIWidget, SettingUIWidget)
# ══════════════════════════════════════════════════════════════════════════════

class TriangleWidget(QWidget):
    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index        = index
        self.parent_menu  = parent
        self._current_offset = 0.0
        self._fade_factor    = 0.0
        self.target_offset   = 0.0
        self.sector_data     = SectorData()
        self.icon_pixmap: Optional[QPixmap] = None
        self.offset_animation = QPropertyAnimation(self, b"current_offset")
        self.fade_animation   = QPropertyAnimation(self, b"fade_factor")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def get_current_offset(self): return self._current_offset
    def set_current_offset(self, v):
        self._current_offset = v; self.update()
    def get_fade_factor(self):    return self._fade_factor
    def set_fade_factor(self, v):
        self._fade_factor = v; self.update()
    current_offset = Property(float, get_current_offset, set_current_offset)
    fade_factor    = Property(float, get_fade_factor,    set_fade_factor)

    def update_state(self, hovered: bool, center_hovered: bool, setting_mode: bool):
        self.target_offset = 15.0 if hovered else (10.0 if center_hovered else 0.0)
        if (self.offset_animation.state() != QPropertyAnimation.Running
                and abs(self._current_offset - self.target_offset) > 0.1):
            self.offset_animation.stop()
            self.offset_animation.setDuration(150)
            self.offset_animation.setStartValue(self._current_offset)
            self.offset_animation.setEndValue(self.target_offset)
            self.offset_animation.setEasingCurve(QEasingCurve.OutCubic)
            self.offset_animation.start()
        tf = 1.0 if hovered else 0.0
        if (self.fade_animation.state() != QPropertyAnimation.Running
                and abs(self._fade_factor - tf) > 0.01):
            self.fade_animation.stop()
            self.fade_animation.setDuration(200)
            self.fade_animation.setStartValue(self._fade_factor)
            self.fade_animation.setEndValue(tf)
            self.fade_animation.setEasingCurve(QEasingCurve.OutCubic)
            self.fade_animation.start()

    def load_data(self, sector_data: SectorData):
        self.sector_data = sector_data
        if sector_data.icon_path and os.path.exists(sector_data.icon_path):
            try:
                px = QPixmap(sector_data.icon_path)
                ms = int(Constants.RADIUS * 0.5)
                if px.width() > ms or px.height() > ms:
                    px = px.scaled(ms, ms, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.icon_pixmap = px
            except Exception:
                self.icon_pixmap = None
        else:
            self.icon_pixmap = None

    def get_display_text(self) -> str:
        t = self.sector_data.name
        if not t:
            ep = self.sector_data.exe_path
            if not ep:
                return ""
            if os.path.isdir(ep):
                t = os.path.basename(ep) or os.path.splitdrive(ep)[0] or "ROOT"
            else:
                t = os.path.splitext(os.path.basename(ep))[0]
        return (t[:11] + "..") if len(t) > 12 else t

    def has_data(self): return self.sector_data.has_data()

    def paintEvent(self, _):
        if not self.parent_menu:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        f   = self._fade_factor
        ic  = QColor(*Constants.COLOR_IDLE)
        hc  = QColor(*Constants.COLOR_HOVER)
        color = QColor(
            int(ic.red()   + (hc.red()   - ic.red())   * f),
            int(ic.green() + (hc.green() - ic.green()) * f),
            int(ic.blue()  + (hc.blue()  - ic.blue())  * f),
            int(ic.alpha() + (hc.alpha() - ic.alpha()) * f),
        )
        center = self.parent_menu.center
        step   = 2 * math.pi / Constants.NUM_SIDES
        sa     = self.index * step - math.pi / 2
        ea     = (self.index + 1) * step - math.pi / 2
        ma     = (sa + ea) / 2
        off    = self._current_offset
        cx     = center.x() + math.cos(ma) * off
        cy     = center.y() + math.sin(ma) * off
        ri     = Constants.CENTER_RADIUS + 2
        ro     = Constants.RADIUS
        path   = QPainterPath()
        path.moveTo(QPointF(cx + ri * math.cos(sa), cy + ri * math.sin(sa)))
        path.lineTo(QPointF(cx + ro * math.cos(sa), cy + ro * math.sin(sa)))
        path.lineTo(QPointF(cx + ro * math.cos(ea), cy + ro * math.sin(ea)))
        path.lineTo(QPointF(cx + ri * math.cos(ea), cy + ri * math.sin(ea)))
        path.closeSubpath()
        painter.setBrush(QBrush(color))
        oc = QColor(*Constants.COLOR_OUTLINE)
        pw = 2.0 if f > 0.5 else 1.5
        if f > 0.5: oc.setAlpha(180)
        painter.setPen(QPen(oc, pw))
        painter.drawPath(path)
        if self.has_data():
            dist = (ri + ro) / 2
            px   = cx + math.cos(ma) * dist
            py   = cy + math.sin(ma) * dist
            if self.icon_pixmap:
                iw, ih = self.icon_pixmap.width(), self.icon_pixmap.height()
                painter.drawPixmap(
                    QRectF(px - iw/2, py - ih/2, iw, ih),
                    self.icon_pixmap, QRectF(0, 0, iw, ih)
                )
            else:
                txt = self.get_display_text()
                if txt:
                    painter.save()
                    painter.translate(px, py)
                    deg = math.degrees(ma) + 90
                    if 90 < (deg % 360) < 270:
                        deg += 180
                    painter.rotate(deg)
                    auto_hide = getattr(self.parent_menu.app_state, "auto_hide_labels", True)
                    if auto_hide:
                        op = self.parent_menu.app_state.text_opacity
                        if op < 0.01:
                            painter.restore(); return
                        alpha = int(op * 230)
                    else:
                        alpha = 230
                    font = QFont("Segoe UI", 7, QFont.Bold)
                    painter.setFont(font)
                    m = QFontMetrics(font)
                    tr = m.boundingRect(txt)
                    rc = QRectF(-tr.width()/2 - 10, -tr.height()/2, tr.width() + 20, tr.height() + 5)
                    painter.setPen(QColor(0, 0, 0, int(alpha * 0.65)))
                    painter.drawText(rc, Qt.AlignCenter | Qt.TextWordWrap, txt)
                    painter.setPen(QColor(255, 255, 255, alpha))
                    painter.drawText(rc, Qt.AlignCenter | Qt.TextWordWrap, txt)
                    painter.restore()


class CenterCircleWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_menu  = parent
        self._fade_factor = 0.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def update_fade(self, v: float):
        if self._fade_factor != v:
            self._fade_factor = v; self.update()

    def enterEvent(self, e):
        if self.parent_menu and hasattr(self.parent_menu, "trigger_text_reveal"):
            self.parent_menu.trigger_text_reveal()
        super().enterEvent(e)

    def paintEvent(self, _):
        if not self.parent_menu:
            return
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        f  = self._fade_factor
        ic = QColor(*Constants.COLOR_IDLE); hc = QColor(*Constants.COLOR_HOVER)
        r  = int(ic.red()   + (hc.red()   - ic.red())   * f)
        g  = int(ic.green() + (hc.green() - ic.green()) * f)
        b  = int(ic.blue()  + (hc.blue()  - ic.blue())  * f)
        a  = int(ic.alpha() + (hc.alpha() - ic.alpha()) * f)
        if self.parent_menu.app_state.is_setting_mode:
            color = QColor(150, 50, 50, a)
        else:
            color = QColor(r, g, b, a)
        center = self.parent_menu.center
        p.setBrush(QBrush(color))
        oc = QColor(*Constants.COLOR_OUTLINE); oc.setAlpha(150 if f > 0.5 else 100)
        p.setPen(QPen(oc, 2))
        p.drawEllipse(center, Constants.CENTER_RADIUS, Constants.CENTER_RADIUS)
        if self.parent_menu.app_state.show_page_indicator:
            s = self.parent_menu.app_state
            txt = f"{s.current_page+1}/{s.total_pages}"
            ir  = 25
            p.setBrush(QBrush(QColor(0, 0, 0, 200))); p.setPen(Qt.NoPen)
            p.drawEllipse(center, ir, ir)
            font = QFont("Arial", 12, QFont.Bold)
            p.setFont(font); p.setPen(QColor(255, 255, 255))
            m = QFontMetrics(font); tr = m.boundingRect(txt)
            p.drawText(
                int(center.x() - tr.width()/2),
                int(center.y() + tr.height()/2 - m.descent()), txt
            )


class DropZoneWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_menu = parent
        self.current_sector_index = -1
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._setup()

    def _setup(self):
        self.setFixedSize(Constants.DROP_ZONE_WIDTH, Constants.DROP_ZONE_HEIGHT)
        self.setStyleSheet("""
            QFrame{background-color:rgba(15,15,20,250);border:2px solid rgba(100,100,100,255);
                   border-radius:12px;}
            QLabel{color:white;font-family:'Segoe UI';border:none;background:transparent;}
            QLineEdit{background-color:rgba(40,40,40,255);border:1px solid rgba(100,100,100,255);
                      border-radius:5px;color:white;padding:8px;font-size:13px;min-height:30px;}
            QPushButton{border-radius:5px;padding:8px 15px;background-color:rgba(50,50,50,255);
                        color:white;border:1px solid rgba(150,150,150,255);font-weight:bold;}
            QPushButton:hover{background-color:white;color:black;}
        """)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(20, 15, 20, 15); lo.setSpacing(8)
        self.title_lbl = QLabel("DROP FILE / FOLDER HERE")
        self.title_lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.title_lbl.setAlignment(Qt.AlignCenter)
        lo.addWidget(self.title_lbl)
        self.info_lbl = QLabel("Sector — Page —")
        self.info_lbl.setAlignment(Qt.AlignCenter)
        self.info_lbl.setStyleSheet("color:#888;font-size:11px;")
        lo.addWidget(self.info_lbl)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Custom name (optional)")
        self.name_input.setMaxLength(20)
        lo.addWidget(self.name_input)
        close_btn = QPushButton("✕ Close")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self._close_handler)
        lo.addWidget(close_btn)

    def update_info(self, sector_idx: int, page: int):
        self.current_sector_index = sector_idx
        self.info_lbl.setText(f"Sector {sector_idx + 1}  —  Page {page + 1}")

    def _close_handler(self):
        if self.parent_menu:
            self.parent_menu.app_state.editing_index = None
            self.parent_menu.app_state.is_url_mode   = False
            self.parent_menu.update_overlay_logic()
        self.hide()

    def keyPressEvent(self, e: QKeyEvent):
        # BUG FIX #13: propagate to parent directly instead of creating fake QKeyEvent
        if e.key() == Qt.Key_Backspace and not self.name_input.hasFocus():
            if self.parent_menu and hasattr(self.parent_menu, "event_handler"):
                self.parent_menu.event_handler.handle_key_press(e)
            return
        super().keyPressEvent(e)


class UrlUIWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_menu = parent
        self.sector_index = -1
        self.setFocusPolicy(Qt.StrongFocus)
        self._setup()

    def _setup(self):
        self.setFixedSize(Constants.URL_UI_WIDTH, Constants.URL_UI_HEIGHT)
        self.setStyleSheet("""
            QFrame{background-color:rgba(10,10,10,240);border:2px solid rgba(200,200,200,200);border-radius:12px;}
            QLabel{color:white;background:transparent;border:none;}
            QLineEdit{background-color:rgba(40,40,40,255);border:1px solid rgba(100,100,100,255);
                      border-radius:5px;color:white;padding:8px;font-size:13px;min-height:30px;}
            QPushButton{border-radius:5px;padding:8px 15px;background-color:rgba(50,50,50,255);
                        color:white;border:1px solid rgba(150,150,150,255);font-weight:bold;}
            QPushButton:hover{background-color:white;color:black;}
            QCheckBox{color:white;background:transparent;border:none;font-size:12px;}
            QCheckBox::indicator{width:15px;height:15px;border:1px solid #888;border-radius:3px;background:#333;}
            QCheckBox::indicator:checked{background:#00AA00;border:1px solid #00FF00;}
        """)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(25, 25, 25, 25); lo.setSpacing(12)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter name...")
        self.name_input.setMaxLength(20)
        self.name_input.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.name_input.returnPressed.connect(self._on_name_enter)
        lo.addWidget(self.name_input)
        cr = QHBoxLayout(); cr.setSpacing(20)
        self.chk_incognito = QCheckBox(" Incognito Mode")
        self.chk_tracking  = QCheckBox(" Track URL ID")
        self.chk_incognito.toggled.connect(self._on_incognito)
        self.chk_tracking.toggled.connect(self._on_tracking)
        self.chk_incognito.stateChanged.connect(self._save_checks)
        self.chk_tracking.stateChanged.connect(self._save_checks)
        cr.addWidget(self.chk_incognito); cr.addWidget(self.chk_tracking); cr.addStretch()
        lo.addLayout(cr)
        br = QHBoxLayout(); br.setSpacing(10)
        self.rename_btn = QPushButton("RENAME"); self.rename_btn.setCursor(Qt.PointingHandCursor)
        self.paste_btn  = QPushButton("PASTE URL"); self.paste_btn.setCursor(Qt.PointingHandCursor)
        br.addWidget(self.rename_btn); br.addWidget(self.paste_btn)
        lo.addLayout(br)
        self.url_label = QLabel("No URL set")
        self.url_label.setStyleSheet("color:#999;font-size:11px;padding:5px;border-top:1px solid #333;")
        self.url_label.setWordWrap(True)
        lo.addWidget(self.url_label)
        self.rename_btn.clicked.connect(self._on_rename)
        self.paste_btn.clicked.connect(self._on_paste)

    def update_data(self, idx: int, sd: SectorData):
        self.sector_index = idx
        self.name_input.clear()
        self.chk_incognito.blockSignals(True); self.chk_tracking.blockSignals(True)
        self.chk_incognito.setChecked(sd.use_incognito)
        self.chk_tracking.setChecked(sd.enable_tracking)
        self.chk_incognito.blockSignals(False); self.chk_tracking.blockSignals(False)
        if sd.url:
            dn = sd.url[:50] + "..." if len(sd.url) > 50 else sd.url
            self.url_label.setText(f"URL: {dn}"); self.paste_btn.setText("UPDATE URL")
        else:
            self.url_label.setText("No URL set"); self.paste_btn.setText("PASTE URL")

    def _save_checks(self):
        if self.parent_menu and self.sector_index >= 0:
            gi = self.parent_menu.app_state.get_global_sector_index(self.sector_index)
            sd = self.parent_menu.data_manager.get_sector_data(gi)
            sd.use_incognito  = self.chk_incognito.isChecked()
            sd.enable_tracking = self.chk_tracking.isChecked()
            self.parent_menu.data_manager.update_sector_data(gi, sd)

    def _on_incognito(self, checked):
        if checked:
            self.chk_tracking.blockSignals(True); self.chk_tracking.setChecked(False)
            self.chk_tracking.blockSignals(False)

    def _on_tracking(self, checked):
        if checked:
            self.chk_incognito.blockSignals(True); self.chk_incognito.setChecked(False)
            self.chk_incognito.blockSignals(False)

    def _on_rename(self):
        self.name_input.setFocus(); self.name_input.selectAll()
        if self.parent_menu:
            self.parent_menu.app_state.input_active = True
            self.parent_menu.app_state.input_text   = self.name_input.text()

    def _on_name_enter(self):
        name = self.name_input.text().strip()
        if self.parent_menu and self.sector_index >= 0:
            gi = self.parent_menu.app_state.get_global_sector_index(self.sector_index)
            sd = self.parent_menu.data_manager.get_sector_data(gi)
            if name: sd.name = name
            sd.use_incognito   = self.chk_incognito.isChecked()
            sd.enable_tracking = self.chk_tracking.isChecked()
            self.parent_menu.data_manager.update_sector_data(gi, sd)
            self.parent_menu.reload_sector_data(self.sector_index)
            self.name_input.clear()
            self.parent_menu.app_state.input_active  = False
            self.parent_menu.app_state.editing_index = None
            self.parent_menu.app_state.is_url_mode   = False
            self.hide(); self.parent_menu.update_overlay_logic()

    def _on_paste(self):
        if self.parent_menu and hasattr(self.parent_menu, "event_handler"):
            self.parent_menu.event_handler.paste_url_from_clipboard()


class SettingUIWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_menu = parent
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.is_selecting_launcher = False
        self.is_selecting_search   = False
        self.reset_count = 0
        self.reset_timer = QTimer(self)
        self.reset_timer.setSingleShot(True)
        self.reset_timer.timeout.connect(self._reset_counter)
        self._setup()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.fillRect(self.rect(), Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.setBrush(QBrush(QColor(15, 15, 15, 245)))
        p.setPen(QPen(QColor(100, 100, 100), 1.5))
        p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 12, 12)

    def show_animated(self): self.show()
    def hide_animated(self): self.hide()

    def _make_collapsible_header(self, title: str, expanded: bool = True) -> Tuple[QPushButton, QFrame]:
        """Tạo header collapsible với mũi tên ▼/▶ và content frame."""
        header = QPushButton(f"{'▼' if expanded else '▶'} {title}")
        header.setStyleSheet(
            "QPushButton{background:#1a1a1a;color:#E0E0E0;border:1px solid #333;border-radius:4px;"
            "padding:8px;text-align:left;font-weight:bold;}"
            "QPushButton:hover{background:#252525;}")
        header.setCursor(Qt.PointingHandCursor)
        
        content = QFrame()
        content.setStyleSheet("background:#131313;border:1px solid #2a2a2a;border-radius:4px;")
        content.setVisible(expanded)
        
        def toggle_expand():
            is_expanded = content.isVisible()
            content.setVisible(not is_expanded)
            header.setText(f"{'▶' if is_expanded else '▼'} {title}")
        
        header.clicked.connect(toggle_expand)
        return header, content

    def _setup(self):
        self.setFixedSize(560, 680)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { background: #0f0f0f; border: none; }
            QScrollBar:vertical { width: 8px; background: #1a1a1a; }
            QScrollBar::handle:vertical { background: #444; border-radius: 4px; min-height: 30px; }
            QScrollBar::handle:vertical:hover { background: #555; }
        """)

        content = QWidget()
        content.setStyleSheet("background:#0f0f0f;")
        lo = QVBoxLayout(content)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(10)
        title = QLabel("⚙ SYSTEM SETTINGS")
        title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        title.setAlignment(Qt.AlignCenter); title.setStyleSheet("color:#E0E0E0;")
        lo.addWidget(title)
        line = QFrame(); line.setFixedHeight(1); line.setStyleSheet("background:#555;")
        lo.addWidget(line)
        # Launcher
        lo.addWidget(self._lbl("🚀 Launcher Hotkey"))
        self.btn_launcher = QPushButton("Change Launcher Key")
        self.btn_launcher.setCursor(Qt.PointingHandCursor)
        self.btn_launcher.setStyleSheet(self._btn_css())
        self.btn_launcher.clicked.connect(self._start_launcher)
        lo.addWidget(self.btn_launcher)
        self.lbl_launcher = QLabel("Current: ..."); self.lbl_launcher.setAlignment(Qt.AlignCenter)
        self.lbl_launcher.setStyleSheet("color:#888;font-size:11px;"); lo.addWidget(self.lbl_launcher)
        # Search
        lo.addWidget(self._lbl("🔍 Search Hotkey"))
        self.btn_search = QPushButton("Change Search Key")
        self.btn_search.setCursor(Qt.PointingHandCursor)
        self.btn_search.setStyleSheet(self._btn_css())
        self.btn_search.clicked.connect(self._start_search)
        lo.addWidget(self.btn_search)
        self.lbl_search = QLabel("Current: ..."); self.lbl_search.setAlignment(Qt.AlignCenter)
        self.lbl_search.setStyleSheet("color:#888;font-size:11px;"); lo.addWidget(self.lbl_search)
        # Detect box
        self.detected_bg = QFrame()
        self.detected_bg.setStyleSheet("background:#111;border-radius:6px;border:1px solid #444;")
        self.detected_bg.setFixedHeight(40)
        bl = QVBoxLayout(self.detected_bg); bl.setContentsMargins(5, 4, 5, 4)
        self.detected_label = QLabel("Settings Ready")
        self.detected_label.setAlignment(Qt.AlignCenter); self.detected_label.setFont(QFont("Segoe UI", 10))
        self.detected_label.setStyleSheet("color:#666;background:transparent;border:none;")
        bl.addWidget(self.detected_label); lo.addWidget(self.detected_bg)
        # Auto-hide text checkbox
        self.chk_hide_text = QCheckBox("Auto Hide Text (1.8s)")
        self.chk_hide_text.setFont(QFont("Segoe UI", 10))
        self.chk_hide_text.setStyleSheet("""
            QCheckBox{color:#E0E0E0;spacing:8px;}
            QCheckBox::indicator{width:18px;height:18px;border-radius:4px;border:1px solid #666;background:#333;}
            QCheckBox::indicator:checked{background:#00AAFF;border-color:#0088CC;}
        """)
        self.chk_hide_text.setCursor(Qt.PointingHandCursor)
        if self.parent_menu and self.parent_menu.data_manager:
            self.chk_hide_text.setChecked(
                self.parent_menu.data_manager.app_config.get("text_auto_hide", True))
        self.chk_hide_text.stateChanged.connect(self._on_hide_text)
        lo.addWidget(self.chk_hide_text)

        # ── Remote Server Section ─────────────────────────────────────────────
        sep = QFrame(); sep.setFixedHeight(1); sep.setStyleSheet("background:#444;")
        lo.addWidget(sep)
        lo.addWidget(self._lbl("Remote Access (Tailscale/LAN)"))

        # Status indicator
        self.lbl_server_status = QLabel("● Chưa khởi động")
        self.lbl_server_status.setFont(QFont("Segoe UI", 10))
        self.lbl_server_status.setStyleSheet("color:#888;background:transparent;")
        lo.addWidget(self.lbl_server_status)

        mode_row = QHBoxLayout(); mode_row.setSpacing(10)
        self.chk_use_tailscale = QCheckBox("Use Tailscale")
        self.chk_allow_lan = QCheckBox("Allow LAN")
        self.chk_prefer_tailscale = QCheckBox("Prefer Tailscale")
        for chk in (self.chk_use_tailscale, self.chk_allow_lan, self.chk_prefer_tailscale):
            chk.setFont(QFont("Segoe UI", 9))
            chk.setStyleSheet("QCheckBox{color:#E0E0E0;spacing:6px;}")
            chk.setCursor(Qt.PointingHandCursor)
        if self.parent_menu and self.parent_menu.data_manager:
            cfg = self.parent_menu.data_manager.server_config
            use_ts = bool(cfg.get("use_tailscale", True))
            use_lan = bool(cfg.get("allow_lan", False))
            
            # Priority: Tailscale > LAN
            if use_ts:
                self.chk_use_tailscale.setChecked(True)
                self.chk_allow_lan.setChecked(False)
            elif use_lan:
                self.chk_allow_lan.setChecked(True)
                self.chk_use_tailscale.setChecked(False)
            else:
                # Default to Tailscale
                self.chk_use_tailscale.setChecked(True)
                
            self.chk_prefer_tailscale.setChecked(bool(cfg.get("prefer_tailscale", True)))
        mode_row.addWidget(self.chk_use_tailscale)
        mode_row.addWidget(self.chk_allow_lan)
        mode_row.addWidget(self.chk_prefer_tailscale)
        lo.addLayout(mode_row)
        
        # Connect connection mode checkboxes to enforce mutual exclusivity
        self.chk_use_tailscale.toggled.connect(self._on_connection_mode_changed)
        self.chk_allow_lan.toggled.connect(self._on_connection_mode_changed)

        shared_row = QHBoxLayout(); shared_row.setSpacing(10)
        self.chk_allow_teamviewer = QCheckBox("Allow TeamViewer Control")
        self.chk_shared_executor = QCheckBox("Shared Executor")
        for chk in (self.chk_allow_teamviewer, self.chk_shared_executor):
            chk.setFont(QFont("Segoe UI", 9))
            chk.setStyleSheet("QCheckBox{color:#E0E0E0;spacing:6px;}")
            chk.setCursor(Qt.PointingHandCursor)
        if self.parent_menu and self.parent_menu.data_manager:
            cfg = self.parent_menu.data_manager.server_config
            self.chk_allow_teamviewer.setChecked(bool(cfg.get("allow_teamviewer_control", True)))
            self.chk_shared_executor.setChecked(str(cfg.get("controller_mode", "default_server_only")) != "default_server_only")
        shared_row.addWidget(self.chk_allow_teamviewer)
        shared_row.addWidget(self.chk_shared_executor)
        lo.addLayout(shared_row)

        # ── TAILSCALE COLLAPSIBLE SECTION ────────────────────────────────────
        ts_header, ts_content = self._make_collapsible_header("🔗 Tailscale Settings", expanded=False)
        lo.addWidget(ts_header)
        
        ts_lo = QVBoxLayout(ts_content)
        ts_lo.setContentsMargins(12, 12, 12, 12)
        ts_lo.setSpacing(6)

        # Tailscale IP row (read-only, tự detect)
        ts_row = QHBoxLayout(); ts_row.setSpacing(6)
        ts_row.addWidget(QLabel("Tailscale IP:"))
        self.inp_ts_ip = QLineEdit()
        self.inp_ts_ip.setPlaceholderText("100.x.x.x  (tự detect khi bật)")
        self.inp_ts_ip.setReadOnly(True)
        self.inp_ts_ip.setStyleSheet(
            "QLineEdit{background:#111;border:1px solid #333;border-radius:4px;"
            "color:#4dffb4;padding:4px 8px;font-size:11px;font-family:monospace;}")
        if self.parent_menu and self.parent_menu.data_manager:
            saved_ip = self.parent_menu.data_manager.server_config.get("tailscale_ip", "")
            if saved_ip:
                self.inp_ts_ip.setText(saved_ip)
        ts_row.addWidget(self.inp_ts_ip)
        btn_copy_ip = QPushButton("📋")
        btn_copy_ip.setFixedWidth(30); btn_copy_ip.setCursor(Qt.PointingHandCursor)
        btn_copy_ip.setToolTip("Copy Tailscale IP")
        btn_copy_ip.setStyleSheet(self._btn_css())
        btn_copy_ip.clicked.connect(self._copy_ts_ip)
        ts_row.addWidget(btn_copy_ip)
        ts_lo.addLayout(ts_row)
        
        lo.addWidget(ts_content)
        self.ts_wrap = ts_content

        # ── LAN COLLAPSIBLE SECTION ──────────────────────────────────────────
        lan_header, lan_content = self._make_collapsible_header("🏠 LAN Access", expanded=False)
        lo.addWidget(lan_header)
        
        lan_lo = QVBoxLayout(lan_content)
        lan_lo.setContentsMargins(12, 12, 12, 12)
        lan_lo.setSpacing(6)

        lan_row = QHBoxLayout(); lan_row.setSpacing(6)
        lan_row.addWidget(QLabel("LAN URL:"))
        self.inp_lan_url = QLineEdit()
        self.inp_lan_url.setReadOnly(True)
        self.inp_lan_url.setStyleSheet(
            "QLineEdit{background:#111;border:1px solid #333;border-radius:4px;"
            "color:#99d6ff;padding:4px 8px;font-size:11px;font-family:monospace;}")
        if self.parent_menu and self.parent_menu.data_manager:
            cfg = self.parent_menu.data_manager.server_config
            if cfg.get("allow_lan", False):
                self.inp_lan_url.setText(f"http://{SystemUtils.get_lan_ip()}:{cfg.get('port', 7777)}")
        lan_row.addWidget(self.inp_lan_url)
        btn_copy_lan = QPushButton("📋")
        btn_copy_lan.setFixedWidth(30); btn_copy_lan.setCursor(Qt.PointingHandCursor)
        btn_copy_lan.setToolTip("Copy LAN URL")
        btn_copy_lan.setStyleSheet(self._btn_css())
        btn_copy_lan.clicked.connect(self._copy_lan_url)
        lan_row.addWidget(btn_copy_lan)
        lan_lo.addLayout(lan_row)
        
        lo.addWidget(lan_content)
        self.lan_wrap = lan_content

        # ── AI SERVER (PUSH SECTORS) COLLAPSIBLE SECTION ─────────────────────
        ai_hdr, ai_content = self._make_collapsible_header("🤖 AI Server — nhận sectors từ PentaKuRu", expanded=False)
        lo.addWidget(ai_hdr)

        ai_lo = QVBoxLayout(ai_content)
        ai_lo.setContentsMargins(12, 12, 12, 12)
        ai_lo.setSpacing(6)

        ai_url_lbl = QLabel("Mỗi khi sector thay đổi, PentaKuRu tự động push lên AI server.")
        ai_url_lbl.setStyleSheet("color:#88aacc;font-size:10px;background:transparent;")
        ai_url_lbl.setWordWrap(True)
        ai_lo.addWidget(ai_url_lbl)

        ai_url_row = QHBoxLayout(); ai_url_row.setSpacing(6)
        ai_url_row.addWidget(QLabel("AI URL:"))
        self.inp_ai_url = QLineEdit()
        self.inp_ai_url.setPlaceholderText("http://100.x.x.x:9090")
        self.inp_ai_url.setStyleSheet(
            "QLineEdit{background:#1a1a1a;border:1px solid #444;border-radius:4px;"
            "color:white;padding:4px 8px;font-size:11px;font-family:monospace;}")
        if self.parent_menu and self.parent_menu.data_manager:
            self.inp_ai_url.setText(
                self.parent_menu.data_manager.server_config.get("ai_server_url", ""))
        ai_url_row.addWidget(self.inp_ai_url)
        ai_lo.addLayout(ai_url_row)

        ai_tok_row = QHBoxLayout(); ai_tok_row.setSpacing(6)
        ai_tok_row.addWidget(QLabel("AI Token:"))
        self.inp_ai_token = QLineEdit()
        self.inp_ai_token.setPlaceholderText("Bearer token của AI server (config.json → auth_token)")
        self.inp_ai_token.setEchoMode(QLineEdit.Password)
        self.inp_ai_token.setStyleSheet(
            "QLineEdit{background:#1a1a1a;border:1px solid #444;border-radius:4px;"
            "color:white;padding:4px 8px;font-size:11px;}")
        if self.parent_menu and self.parent_menu.data_manager:
            self.inp_ai_token.setText(
                self.parent_menu.data_manager.server_config.get("ai_server_token", ""))
        ai_tok_row.addWidget(self.inp_ai_token)
        ai_lo.addLayout(ai_tok_row)

        btn_test_push = QPushButton("📤 Test Push Sectors")
        btn_test_push.setCursor(Qt.PointingHandCursor)
        btn_test_push.setStyleSheet(self._btn_css())
        btn_test_push.clicked.connect(self._test_push_sectors)
        ai_lo.addWidget(btn_test_push)

        lo.addWidget(ai_content)
        self.ai_wrap = ai_content

        # ── ADVANCED / AUTH COLLAPSIBLE SECTION ──────────────────────────────
        adv_header, adv_content = self._make_collapsible_header("⚙️ Advanced / Port & Auth", expanded=False)
        lo.addWidget(adv_header)
        
        adv_lo = QVBoxLayout(adv_content)
        adv_lo.setContentsMargins(12, 12, 12, 12)
        adv_lo.setSpacing(6)

        # Auth token row
        auth_row = QHBoxLayout(); auth_row.setSpacing(6)
        auth_row.addWidget(QLabel("Token:"))
        self.inp_auth = QLineEdit()
        self.inp_auth.setPlaceholderText("Bearer auth token (tự sinh nếu trống)")
        self.inp_auth.setEchoMode(QLineEdit.Password)
        self.inp_auth.setStyleSheet(
            "QLineEdit{background:#1a1a1a;border:1px solid #444;border-radius:4px;"
            "color:white;padding:4px 8px;font-size:11px;}")
        if self.parent_menu and self.parent_menu.data_manager:
            self.inp_auth.setText(
                self.parent_menu.data_manager.server_config.get("auth_token", ""))
        auth_row.addWidget(self.inp_auth)
        btn_copy = QPushButton("📋")
        btn_copy.setFixedWidth(30); btn_copy.setCursor(Qt.PointingHandCursor)
        btn_copy.setToolTip("Copy token")
        btn_copy.setStyleSheet(self._btn_css())
        btn_copy.clicked.connect(self._copy_token)
        auth_row.addWidget(btn_copy)
        adv_lo.addLayout(auth_row)

        controller_row = QHBoxLayout(); controller_row.setSpacing(6)
        controller_row.addWidget(QLabel("Default Controller:"))
        self.inp_default_controller = QLineEdit()
        self.inp_default_controller.setPlaceholderText("penta_ai")
        self.inp_default_controller.setStyleSheet(
            "QLineEdit{background:#1a1a1a;border:1px solid #444;border-radius:4px;"
            "color:white;padding:4px 8px;font-size:11px;}")
        if self.parent_menu and self.parent_menu.data_manager:
            self.inp_default_controller.setText(
                self.parent_menu.data_manager.server_config.get("default_controller", "penta_ai"))
        controller_row.addWidget(self.inp_default_controller)
        adv_lo.addLayout(controller_row)

        # Port row
        port_row = QHBoxLayout(); port_row.setSpacing(6)
        port_row.addWidget(QLabel("Port:"))
        self.inp_port = QLineEdit()
        self.inp_port.setFixedWidth(60)
        self.inp_port.setStyleSheet(
            "QLineEdit{background:#1a1a1a;border:1px solid #444;border-radius:4px;"
            "color:white;padding:4px;font-size:11px;text-align:center;}")
        if self.parent_menu and self.parent_menu.data_manager:
            self.inp_port.setText(
                str(self.parent_menu.data_manager.server_config.get("port", 7777)))
        port_row.addWidget(self.inp_port)
        port_row.addStretch()
        adv_lo.addLayout(port_row)
        
        lo.addWidget(adv_content)
        self.adv_wrap = adv_content

        # Save + Toggle row
        ctrl_row = QHBoxLayout(); ctrl_row.setSpacing(6)
        self.btn_save_server = QPushButton("💾 Lưu")
        self.btn_save_server.setCursor(Qt.PointingHandCursor)
        self.btn_save_server.setStyleSheet(self._btn_css())
        self.btn_save_server.clicked.connect(self._save_server_config)
        ctrl_row.addWidget(self.btn_save_server)
        self.btn_toggle_server = QPushButton("▶ Bật Server")
        self.btn_toggle_server.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_server.setStyleSheet(
            "QPushButton{background:#1a3320;border:1px solid #2d6e45;border-radius:5px;"
            "padding:6px;color:#4dffb4;font-weight:bold;}"
            "QPushButton:hover{background:#224433;}")
        self.btn_toggle_server.clicked.connect(self._toggle_server)
        ctrl_row.addWidget(self.btn_toggle_server)
        lo.addLayout(ctrl_row)

        # Reset
        self.btn_reset = QPushButton("🔄 RESET DEFAULTS")
        self.btn_reset.setCursor(Qt.PointingHandCursor)
        self.btn_reset.setStyleSheet("""
            QPushButton{background:#402020;border:1px solid #804040;border-radius:5px;
                        padding:6px;color:#FFAAAA;font-weight:bold;}
            QPushButton:hover{background:#603030;color:white;}
        """)
        self.btn_reset.clicked.connect(self._reset_defaults); lo.addWidget(self.btn_reset)
        hint = QLabel("Enter to Save • Esc to Cancel • Shift+. to Reset")
        hint.setAlignment(Qt.AlignCenter); hint.setStyleSheet("color:#555;font-size:10px;background:transparent;")
        lo.addWidget(hint)
        ts_hint = QLabel("🔒 Mặc định ưu tiên AI server của bạn. Có thể bật LAN hoặc Shared Executor để AI/token client khác dùng chung.")
        ts_hint.setAlignment(Qt.AlignCenter)
        ts_hint.setStyleSheet("color:#446688;font-size:10px;background:transparent;")
        ts_hint.setWordWrap(True)
        lo.addWidget(ts_hint)

        lo.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        self.update_current_keys_display()

    def _copy_token(self):
        if pyperclip:
            pyperclip.copy(self.inp_auth.text())
        else:
            cb = QApplication.clipboard()
            if cb: cb.setText(self.inp_auth.text())

    def _copy_ts_ip(self):
        ip = self.inp_ts_ip.text().strip()
        if not ip: return
        port = ""
        if self.parent_menu and self.parent_menu.data_manager:
            port = str(self.parent_menu.data_manager.server_config.get("port", 7777))
        full = f"http://{ip}:{port}" if port else ip
        if pyperclip:
            pyperclip.copy(full)
        else:
            cb = QApplication.clipboard()
            if cb: cb.setText(full)

    def _copy_lan_url(self):
        url = self.inp_lan_url.text().strip()
        if not url:
            return
        if pyperclip:
            pyperclip.copy(url)
        else:
            cb = QApplication.clipboard()
            if cb: cb.setText(url)

    def _save_server_config(self):
        if not (self.parent_menu and self.parent_menu.data_manager): return
        dm = self.parent_menu.data_manager
        dm.server_config["auth_token"] = self.inp_auth.text().strip() or dm.server_config["auth_token"]
        dm.server_config["use_tailscale"] = self.chk_use_tailscale.isChecked()
        dm.server_config["allow_lan"] = self.chk_allow_lan.isChecked()
        dm.server_config["prefer_tailscale"] = self.chk_prefer_tailscale.isChecked()
        dm.server_config["allow_teamviewer_control"] = self.chk_allow_teamviewer.isChecked()
        dm.server_config["controller_mode"] = "shared_executor" if self.chk_shared_executor.isChecked() else "default_server_only"
        dm.server_config["default_controller"] = self.inp_default_controller.text().strip() or "penta_ai"
        dm.server_config["ai_server_url"]   = self.inp_ai_url.text().strip()
        dm.server_config["ai_server_token"] = self.inp_ai_token.text().strip()
        try:
            dm.server_config["port"] = int(self.inp_port.text().strip())
        except ValueError:
            pass
        dm.save_server_config()
        if dm.server_config.get("allow_lan", False):
            self.inp_lan_url.setText(f"http://{SystemUtils.get_lan_ip()}:{dm.server_config.get('port', 7777)}")
        else:
            self.inp_lan_url.setText("")
        self.detected_label.setText("✓ Đã lưu cấu hình server")
        self.detected_label.setStyleSheet("color:#4dffb4;background:transparent;border:none;")

    def _test_push_sectors(self):
        """Test push sectors lên AI server ngay lập tức."""
        if not (self.parent_menu and self.parent_menu.data_manager): return
        dm = self.parent_menu.data_manager
        # Lưu URL/token mới trước khi test
        dm.server_config["ai_server_url"]   = self.inp_ai_url.text().strip()
        dm.server_config["ai_server_token"] = self.inp_ai_token.text().strip()
        dm.save_server_config()
        dm.save_all_data()  # triggers push
        self.detected_label.setText("📤 Đang push sectors lên AI server...")
        self.detected_label.setStyleSheet("color:#ffcc44;background:transparent;border:none;")

    def _save_connection_mode_only(self):
        """Save only connection mode choices (auto-called when toggle changes)"""
        if not (self.parent_menu and self.parent_menu.data_manager): return
        dm = self.parent_menu.data_manager
        dm.server_config["use_tailscale"] = self.chk_use_tailscale.isChecked()
        dm.server_config["allow_lan"] = self.chk_allow_lan.isChecked()
        dm.server_config["prefer_tailscale"] = self.chk_prefer_tailscale.isChecked()
        dm.save_server_config()
        # Update LAN URL display if LAN is enabled
        if dm.server_config.get("allow_lan", False):
            self.inp_lan_url.setText(f"http://{SystemUtils.get_lan_ip()}:{dm.server_config.get('port', 7777)}")
        else:
            self.inp_lan_url.setText("")

    def _on_connection_mode_changed(self):
        """Enforce mutual exclusivity: only ONE connection method can be active at a time"""
        sender = self.sender()
        
        if not sender:
            return
            
        # If sender is checked, uncheck the others
        if sender.isChecked():
            if sender == self.chk_use_tailscale:
                self.chk_allow_lan.blockSignals(True)
                self.chk_allow_lan.setChecked(False)
                self.chk_allow_lan.blockSignals(False)
            elif sender == self.chk_allow_lan:
                self.chk_use_tailscale.blockSignals(True)
                self.chk_use_tailscale.setChecked(False)
                self.chk_use_tailscale.blockSignals(False)
        
        # Auto-save connection mode choice immediately (no need to click Save button)
        self._save_connection_mode_only()

    def _toggle_server(self):
        if not self.parent_menu: return
        mw = self.parent_menu
        if hasattr(mw, "flask_thread") and mw.flask_thread and mw.flask_thread.isRunning():
            mw.stop_remote_server()
        else:
            self._save_server_config()
            mw.start_remote_server()

    def update_server_status(self, status: str):
        """Được gọi từ MainWindow khi Flask/Tailscale thay đổi trạng thái."""
        if status == "running":
            base = "● Flask đang chạy"
            if self.parent_menu and self.parent_menu.data_manager:
                cfg = self.parent_menu.data_manager.server_config
                waits = []
                if cfg.get("use_tailscale", True):
                    waits.append("Tailscale")
                if waits:
                    base += " — chờ " + "/".join(waits) + "..."
            self.lbl_server_status.setText(base)
            self.lbl_server_status.setStyleSheet("color:#aaddff;background:transparent;")
            self.btn_toggle_server.setText("■ Tắt Server")
            self.btn_toggle_server.setStyleSheet(
                "QPushButton{background:#332020;border:1px solid #6e2d2d;border-radius:5px;"
                "padding:6px;color:#ff8888;font-weight:bold;}"
                "QPushButton:hover{background:#442828;}")
        elif status.startswith("running:"):
            ip = status.split(":", 1)[1]
            self.lbl_server_status.setText(f"● Tailscale kết nối  [{ip}]")
            self.lbl_server_status.setStyleSheet("color:#4dffb4;background:transparent;")
            if hasattr(self, "inp_ts_ip"):
                self.inp_ts_ip.setText(ip)
            self.btn_toggle_server.setText("■ Tắt Server")
            self.btn_toggle_server.setStyleSheet(
                "QPushButton{background:#332020;border:1px solid #6e2d2d;border-radius:5px;"
                "padding:6px;color:#ff8888;font-weight:bold;}"
                "QPushButton:hover{background:#442828;}")
        elif status == "stopped":
            self.lbl_server_status.setText("● Đã dừng")
            self.lbl_server_status.setStyleSheet("color:#888;background:transparent;")
            self.btn_toggle_server.setText("▶ Bật Server")
            self.btn_toggle_server.setStyleSheet(
                "QPushButton{background:#1a3320;border:1px solid #2d6e45;border-radius:5px;"
                "padding:6px;color:#4dffb4;font-weight:bold;}"
                "QPushButton:hover{background:#224433;}")
        elif status == "no_exe":
            self.lbl_server_status.setText("⚠ Tailscale chưa cài — tải tại tailscale.com")
            self.lbl_server_status.setStyleSheet("color:#ffaa44;background:transparent;")
        elif status == "not_connected":
            self.lbl_server_status.setText("⚠ Tailscale chưa đăng nhập — chạy: tailscale up")
            self.lbl_server_status.setStyleSheet("color:#ffaa44;background:transparent;")
        elif status.startswith("error:"):
            self.lbl_server_status.setText(f"✗ {status[6:]}")
            self.lbl_server_status.setStyleSheet("color:#ff6666;background:transparent;")

        if self.parent_menu and self.parent_menu.data_manager:
            cfg = self.parent_menu.data_manager.server_config
            if cfg.get("allow_lan", False):
                self.inp_lan_url.setText(f"http://{SystemUtils.get_lan_ip()}:{cfg.get('port', 7777)}")
            else:
                self.inp_lan_url.setText("")

    @staticmethod
    def _btn_css() -> str:
        return ("QPushButton{background:#333;color:#CCC;border:1px solid #555;"
                "padding:6px;border-radius:5px;}"
                "QPushButton:hover{background:#444;color:white;}")

    @staticmethod
    def _lbl(t: str) -> QLabel:
        l = QLabel(t); l.setFont(QFont("Segoe UI", 11, QFont.Bold))
        l.setStyleSheet("color:#E0E0E0;"); return l

    def _on_hide_text(self, state):
        if self.parent_menu and self.parent_menu.data_manager:
            enabled = bool(state)
            self.parent_menu.data_manager.app_config["text_auto_hide"] = enabled
            self.parent_menu.data_manager.save_config()
            if hasattr(self.parent_menu, "update_labels_visibility_mode"):
                self.parent_menu.update_labels_visibility_mode()

    def _start_launcher(self):
        self.is_selecting_launcher = True; self.is_selecting_search = False
        self.btn_launcher.setText("⌨ Press your key combo...")
        self.btn_launcher.setStyleSheet("QPushButton{background:#004488;color:white;border:1px solid #0088FF;padding:6px;border-radius:5px;}")
        self.detected_label.setText("Waiting for key..."); self.setFocus()

    def _start_search(self):
        self.is_selecting_search = True; self.is_selecting_launcher = False
        self.btn_search.setText("⌨ Press your key combo...")
        self.btn_search.setStyleSheet("QPushButton{background:#004488;color:white;border:1px solid #0088FF;padding:6px;border-radius:5px;}")
        self.detected_label.setText("Waiting for key..."); self.setFocus()

    def _cancel(self):
        self.is_selecting_launcher = self.is_selecting_search = False
        self.btn_launcher.setText("Change Launcher Key"); self.btn_launcher.setStyleSheet(self._btn_css())
        self.btn_search.setText("Change Search Key");     self.btn_search.setStyleSheet(self._btn_css())
        self.detected_label.setText("Cancelled"); self.update_current_keys_display()

    def _reset_defaults(self):
        self.reset_count += 1
        self.reset_timer.start(1500)
        if self.reset_count >= 2 and self.parent_menu:
            self.parent_menu.hotkey_manager.reset_hotkey()
            self.detected_label.setText("Reset to defaults!")
            self.reset_count = 0; self.update_current_keys_display()
        else:
            self.detected_label.setText(f"Click again to confirm ({self.reset_count}/2)")

    def _reset_counter(self): self.reset_count = 0

    def handle_shift_period_hotkey(self):
        self._reset_defaults()

    def update_display(self, mods: Set[int], key: Optional[int]):
        if not self.is_selecting_launcher and not self.is_selecting_search:
            return
        if key:
            self.detected_label.setText(f"Detected: {self.format_keys(mods, key)}")
            self.detected_label.setStyleSheet("color:#00FF88;background:transparent;border:none;")

    def update_current_keys_display(self):
        if not self.parent_menu or not hasattr(self.parent_menu, "hotkey_manager"):
            return
        hm = self.parent_menu.hotkey_manager
        lk = hm.launcher_key
        l_text = "Default (Shift + /)" if not lk else self.format_keys(hm.launcher_modifiers, lk)
        sd = hm.search_hotkey
        sm, sk = sd.get("mods", 0), sd.get("key", 0)
        s_set: Set[int] = set()
        if sm & 0x0001: s_set.add(Constants.VK_MENU)
        if sm & 0x0002: s_set.add(Constants.VK_CONTROL)
        if sm & 0x0004: s_set.add(Constants.VK_SHIFT)
        if sm & 0x0008: s_set.add(Constants.VK_LWIN)
        s_text = "Default (Alt + Space)" if (sk == Constants.SEARCH_DEFAULT_KEY and sm == Constants.SEARCH_DEFAULT_MODS) else self.format_keys(s_set, sk)
        self.lbl_launcher.setText(f"Current: {l_text}")
        self.lbl_search.setText(f"Current: {s_text}")

    # alias used by MainWindow
    def update_current_hotkeys_display(self, l_text: str, s_text: str):
        self.lbl_launcher.setText(f"Current: {l_text}")
        self.lbl_search.setText(f"Current: {s_text}")
        if not self.is_selecting_launcher and not self.is_selecting_search:
            self.btn_launcher.setText("Change Launcher Key"); self.btn_launcher.setStyleSheet(self._btn_css())
            self.btn_search.setText("Change Search Key");     self.btn_search.setStyleSheet(self._btn_css())
            self.detected_label.setText("Settings Ready")
            self.detected_label.setStyleSheet("color:#888;border:none;background:transparent;")

    def keyPressEvent(self, e: QKeyEvent):
        if not self.is_selecting_launcher and not self.is_selecting_search:
            super().keyPressEvent(e); return
        k = e.key(); mods = e.modifiers()
        if k == Qt.Key_Escape:
            self._cancel(); return
        if k in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta):
            mods_set: Set[int] = set()
            if mods & Qt.ShiftModifier: mods_set.add(Constants.VK_SHIFT)
            if mods & Qt.ControlModifier: mods_set.add(Constants.VK_CONTROL)
            if mods & Qt.AltModifier: mods_set.add(Constants.VK_MENU)
            if mods & Qt.MetaModifier: mods_set.add(Constants.VK_LWIN)
            self.detected_label.setText(f"Modifiers: {self.format_keys(mods_set, 0)}")
            return
        mods_set = set()
        bm = 0
        if mods & Qt.ShiftModifier:   mods_set.add(Constants.VK_SHIFT);   bm |= 0x0004
        if mods & Qt.ControlModifier: mods_set.add(Constants.VK_CONTROL); bm |= 0x0002
        if mods & Qt.AltModifier:     mods_set.add(Constants.VK_MENU);    bm |= 0x0001
        if mods & Qt.MetaModifier:    mods_set.add(Constants.VK_LWIN);    bm |= 0x0008
        vk = self._qt_to_vk(k)
        if self.is_selecting_launcher:
            self.parent_menu.hotkey_manager.set_launcher_hotkey(mods_set, vk)
            if hasattr(self.parent_menu, "apply_new_hotkey"):
                self.parent_menu.apply_new_hotkey(vk, mods_set)
            self.is_selecting_launcher = False
        elif self.is_selecting_search:
            ss: Set[int] = set()
            if bm & 0x0001: ss.add(Constants.VK_MENU)
            if bm & 0x0002: ss.add(Constants.VK_CONTROL)
            if bm & 0x0004: ss.add(Constants.VK_SHIFT)
            if bm & 0x0008: ss.add(Constants.VK_LWIN)
            self.parent_menu.hotkey_manager.set_search_hotkey_from_set(ss, vk)
            self.is_selecting_search = False
        self.update_current_keys_display()
        self.btn_launcher.setText("Change Launcher Key"); self.btn_launcher.setStyleSheet(self._btn_css())
        self.btn_search.setText("Change Search Key");     self.btn_search.setStyleSheet(self._btn_css())
        self.detected_label.setText("Hotkey Saved!")
        e.accept()

    @staticmethod
    def _qt_to_vk(qt_key) -> int:
        mapping = {
            Qt.Key_Space: Constants.VK_SPACE, Qt.Key_Return: Constants.VK_RETURN,
            Qt.Key_Enter: Constants.VK_RETURN, Qt.Key_Tab: Constants.VK_TAB,
            Qt.Key_Backspace: Constants.VK_BACK, Qt.Key_Delete: Constants.VK_DELETE,
            Qt.Key_Escape: Constants.VK_ESCAPE, Qt.Key_Pause: Constants.VK_PAUSE,
            Qt.Key_Print: Constants.VK_PRINTSCREEN, Qt.Key_Insert: Constants.VK_INSERT,
            Qt.Key_Home: Constants.VK_HOME, Qt.Key_End: Constants.VK_END,
            Qt.Key_PageUp: Constants.VK_PAGEUP, Qt.Key_PageDown: Constants.VK_PAGEDOWN,
            Qt.Key_Left: Constants.VK_LEFT, Qt.Key_Right: Constants.VK_RIGHT,
            Qt.Key_Up: Constants.VK_UP, Qt.Key_Down: Constants.VK_DOWN,
            Qt.Key_Period: Constants.VK_PERIOD, Qt.Key_Comma: 0xBC,
            Qt.Key_Minus: 0xBD, Qt.Key_Equal: 0xBB, Qt.Key_Slash: Constants.VK_SLASH,
            Qt.Key_Semicolon: 0xBA, Qt.Key_Apostrophe: 0xDE,
            Qt.Key_BracketLeft: 0xDB, Qt.Key_BracketRight: 0xDD,
            Qt.Key_Backslash: 0xDC, Qt.Key_QuoteLeft: 0xC0,
            Qt.Key_NumLock: Constants.VK_NUMLOCK, Qt.Key_ScrollLock: Constants.VK_SCROLLLOCK,
        }
        if qt_key in mapping:    return mapping[qt_key]
        if Qt.Key_A <= qt_key <= Qt.Key_Z:  return qt_key
        if Qt.Key_0 <= qt_key <= Qt.Key_9:  return qt_key
        if Qt.Key_F1 <= qt_key <= Qt.Key_F24:
            return 0x70 + (qt_key - Qt.Key_F1)
        return qt_key

    # used by EventHandler
    def qt_key_to_vk(self, qt_key) -> int:
        return self._qt_to_vk(qt_key)

    def format_keys(self, mods: Set[int], key: int) -> str:
        parts = []
        if Constants.VK_SHIFT   in mods: parts.append("Shift")
        if Constants.VK_CONTROL in mods: parts.append("Ctrl")
        if Constants.VK_MENU    in mods: parts.append("Alt")
        if Constants.VK_LWIN    in mods: parts.append("Win")
        if key:
            km = {
                Constants.VK_RETURN: "Enter", Constants.VK_ESCAPE: "Esc",
                Constants.VK_SLASH: "/", Constants.VK_PERIOD: ".",
                Constants.VK_DELETE: "Delete", Constants.VK_SPACE: "Space",
                Constants.VK_BACK: "Backspace", Constants.VK_TAB: "Tab",
                Constants.VK_UP: "↑", Constants.VK_DOWN: "↓",
                Constants.VK_LEFT: "←", Constants.VK_RIGHT: "→",
                Constants.VK_MB_LEFT: "MouseLeft", Constants.VK_MB_RIGHT: "MouseRight",
                Constants.VK_MB_MIDDLE: "MouseMiddle",
                Constants.VK_MB_BACK: "MB4 (Back)", Constants.VK_MB_FORWARD: "MB5 (Fwd)",
            }
            for i in range(1, 25):
                vkf = getattr(Constants, f"VK_F{i}", 0)
                if key == vkf: parts.append(f"F{i}"); break
            else:
                parts.append(km.get(key, chr(key).upper() if 0x41 <= key <= 0x5A else f"Key_{key}"))
        return " + ".join(parts) if parts else "None"


# ══════════════════════════════════════════════════════════════════════════════
#  HOTKEY MANAGER + WIN EVENT FILTER  (BUG FIX #2 #7)
# ══════════════════════════════════════════════════════════════════════════════

class WinEventFilter(QAbstractNativeEventFilter):
    """
    BUG FIX #7: Use ctypes.cast to properly dereference the message pointer
    instead of bare int(message) which is fragile across Qt versions.
    """
    def __init__(self, hotkey_manager: "HotkeyManager"):
        super().__init__()
        self.hotkey_manager = hotkey_manager

    def nativeEventFilter(self, eventType, message):
        if eventType in (b"windows_generic_MSG", "windows_generic_MSG"):
            try:
                # BUG FIX #7: safe conversion via ctypes.cast
                msg_ptr = ctypes.cast(int(message), ctypes.POINTER(ctypes.wintypes.MSG))
                msg = msg_ptr.contents
                if msg.message == 0x0312:   # WM_HOTKEY
                    self.hotkey_manager.on_hotkey_triggered(msg.wParam)
                    return True, 0
            except Exception as e:
                print(f"[WinEventFilter] {e}")
        return False, 0


class HotkeyManager(QObject):
    hotkey_triggered = Signal(int)

    def __init__(self):
        super().__init__()
        # BUG FIX #2: use shared singleton instead of creating a new DataManager
        self.data_manager    = DataManager.instance()
        self.registered_ids: Set[int] = set()
        self.running         = True
        self.user32          = ctypes.windll.user32
        self.MOD_ALT         = 0x0001; self.MOD_CONTROL = 0x0002
        self.MOD_SHIFT       = 0x0004; self.MOD_WIN     = 0x0008
        self.MOD_NOREPEAT    = 0x4000
        self.event_filter    = WinEventFilter(self)
        self.launcher_modifiers: Set[int] = set()
        self.launcher_key: Optional[int]  = None
        self.search_hotkey: Dict          = {}
        self.load_hotkeys()

    def install_event_filter(self, app):
        app.installNativeEventFilter(self.event_filter)
        print("[HOTKEY] Native event filter installed")

    def on_hotkey_triggered(self, hotkey_id):
        self.hotkey_triggered.emit(hotkey_id)

    def _mods_to_fs(self, mods: Set[int]) -> int:
        fs = self.MOD_NOREPEAT
        if Constants.VK_MENU    in mods: fs |= self.MOD_ALT
        if Constants.VK_CONTROL in mods: fs |= self.MOD_CONTROL
        if Constants.VK_SHIFT   in mods: fs |= self.MOD_SHIFT
        if Constants.VK_LWIN    in mods: fs |= self.MOD_WIN
        return fs

    def register_hotkey(self, hid: int, mods: Set[int], key: int):
        self.unregister_hotkey(hid)
        if not key: return
        fs = self._mods_to_fs(mods)
        if self.user32.RegisterHotKey(None, hid, fs, key):
            self.registered_ids.add(hid)
            print(f"[HOTKEY] Registered ID={hid} key={key} mods={fs}")
        else:
            print(f"[HOTKEY] Failed ID={hid} error={ctypes.GetLastError()}")

    def unregister_hotkey(self, hid: int):
        if hid in self.registered_ids:
            self.user32.UnregisterHotKey(None, hid)
            self.registered_ids.discard(hid)

    def unregister_all(self):
        for hid in list(self.registered_ids):
            self.unregister_hotkey(hid)

    def load_hotkeys(self):
        self.launcher_modifiers = set(self.data_manager.hotkey_data.get("custom_modifiers", []))
        self.launcher_key       = self.data_manager.hotkey_data.get("custom_key")
        if not self.launcher_key:
            self.launcher_modifiers = {Constants.VK_SHIFT}
            self.launcher_key       = Constants.VK_SLASH
        self.register_hotkey(Constants.ID_LAUNCHER, self.launcher_modifiers, self.launcher_key)
        sh = self.data_manager.load_search_hotkey()
        sm, sk = sh.get("mods", Constants.SEARCH_DEFAULT_MODS), sh.get("key", Constants.SEARCH_DEFAULT_KEY)
        self.search_hotkey = {"mods": sm, "key": sk}
        s_set: Set[int] = set()
        if sm & 0x0001: s_set.add(Constants.VK_MENU)
        if sm & 0x0002: s_set.add(Constants.VK_CONTROL)
        if sm & 0x0004: s_set.add(Constants.VK_SHIFT)
        if sm & 0x0008: s_set.add(Constants.VK_LWIN)
        self.register_hotkey(Constants.ID_SEARCH, s_set, sk)
        self.register_hotkey(3, {Constants.VK_SHIFT}, Constants.VK_PERIOD)

    def set_launcher_hotkey(self, mods: Set[int], key: int):
        self.launcher_modifiers = mods; self.launcher_key = key
        self.data_manager.hotkey_data["custom_modifiers"] = list(mods)
        self.data_manager.hotkey_data["custom_key"]       = key
        self.data_manager.save_hotkey_data()
        self.register_hotkey(Constants.ID_LAUNCHER, mods, key)

    def set_search_hotkey_from_set(self, mods: Set[int], key: int):
        bm = 0
        if Constants.VK_MENU    in mods: bm |= 0x0001
        if Constants.VK_CONTROL in mods: bm |= 0x0002
        if Constants.VK_SHIFT   in mods: bm |= 0x0004
        if Constants.VK_LWIN    in mods: bm |= 0x0008
        self.data_manager.save_search_hotkey(bm, key)
        self.search_hotkey = {"mods": bm, "key": key}
        self.register_hotkey(Constants.ID_SEARCH, mods, key)

    def reset_hotkey(self):
        self.data_manager.hotkey_data = {}
        self.data_manager.save_hotkey_data()
        self.data_manager.reset_search_hotkey()
        self.load_hotkeys()

    def update_trigger(self, key: int, mods: Set[int]):
        self.set_launcher_hotkey(mods, key)

    def start(self):
        self.running = True; self.load_hotkeys()

    def stop(self):
        self.running = False

    def cleanup(self):
        self.unregister_all()


# ══════════════════════════════════════════════════════════════════════════════
#  EVENT HANDLER  (BUG FIX #3 #5 #6)
# ══════════════════════════════════════════════════════════════════════════════

class EventHandler:
    def __init__(self, radial_menu):
        self.radial_menu = radial_menu
        self.app_state   = radial_menu.app_state
        self.data_manager = radial_menu.data_manager
        self.app_start_time = time.time()
        self.is_shift_dragging = False
        self.shift_drag_start_pos = None
        self.mouse_button_pressed_flag = None
        self.last_mouse_pos = QPoint(0, 0)
        self.mouse_timer = QTimer(); self.mouse_timer.timeout.connect(self._poll_mouse); self.mouse_timer.start(10)
        self.key_timer   = QTimer(); self.key_timer.timeout.connect(self._poll_keys);   self.key_timer.start(10)

    def _poll_mouse(self):
        pos = QCursor.pos()
        if pos != self.last_mouse_pos:
            self.last_mouse_pos = pos; self.handle_mouse_move(pos)

    def _poll_keys(self):
        if getattr(self.app_state, "is_restarting", False): return
        t = time.time()
        for k in [x for x, ts in self.app_state.keys_held.items() if t - ts > 0.5]:
            del self.app_state.keys_held[k]
        if self.app_state.is_setting_mode or self.app_state.input_active: return

    def handle_mouse_move(self, pos: QPoint):
        if not self.radial_menu.isVisible(): return
        lp = self.radial_menu.mapFromGlobal(pos)
        dx = lp.x() - self.radial_menu.center.x()
        dy = lp.y() - self.radial_menu.center.y()
        dist = math.hypot(dx, dy)
        is_ch = dist < Constants.CENTER_RADIUS
        if is_ch != self.app_state.is_center_hovered:
            self.app_state.is_center_hovered = is_ch
            if is_ch and hasattr(self.radial_menu, "reset_label_timer"):
                self.radial_menu.reset_label_timer()
        self.app_state.update_center_fade(is_ch)
        if is_ch: self.app_state.last_text_active_time = time.time()
        m_angle = (math.atan2(dy, dx) + math.pi / 2) % (2 * math.pi)
        self.app_state.hovered_sector_index = None
        for i, tri in enumerate(self.radial_menu.triangles):
            step = 2 * math.pi / len(self.radial_menu.triangles)
            hov  = (Constants.CENTER_RADIUS <= dist < Constants.RADIUS + 20) and \
                   (i * step <= m_angle < (i + 1) * step)
            tri.update_state(hov, is_ch, self.app_state.is_setting_mode)
            if hov: self.app_state.hovered_sector_index = i

    def handle_mouse_press(self, event) -> bool:
        if not self.radial_menu.isVisible(): return False
        # PySide6: event.position() trả về QPointF, dùng toPoint() để lấy QPoint
        pos    = event.position().toPoint(); button = event.button()
        mods   = QApplication.keyboardModifiers()
        if mods & Qt.ShiftModifier and button == Qt.LeftButton:
            self.is_shift_dragging = True; self.shift_drag_start_pos = pos; return True
        if self.app_state.is_setting_mode:
            self.handle_setting_mode_mouse_press(event); return True
        if button == Qt.BackButton:
            self.app_state.prev_page(); self.radial_menu.reload_page_data(); return True
        if button == Qt.ForwardButton:
            self.app_state.next_page(); self.radial_menu.reload_page_data(); return True
        if self.app_state.is_setting_mode and self.radial_menu.setting_ui.isVisible():
            if self.radial_menu.setting_ui.geometry().contains(pos): return False
        if self._on_center(pos):
            if self.app_state.is_setting_mode:
                if button in (Qt.LeftButton, Qt.MiddleButton):
                    self.app_state.is_setting_mode = False; self.radial_menu.update_overlay_logic()
            elif button == Qt.LeftButton:
                if mods & Qt.ShiftModifier: self.show_startup_dialog()
                return True
            if button == Qt.RightButton:
                self.delete_current_page() if mods & Qt.ShiftModifier else self.add_new_page()
            elif button == Qt.MiddleButton:
                self.toggle_settings()
            return True
        hi = self._sector_at(pos)
        if hi is not None:
            if button == Qt.LeftButton: self.handle_left_click_on_triangle(hi)
            elif button == Qt.RightButton: self.handle_right_click(hi)
            return True
        if button == Qt.LeftButton:
            if self.app_state.is_setting_mode:
                self.app_state.is_setting_mode = False; self.radial_menu.update_overlay_logic()
            else:
                self.app_state.editing_index = None; self.app_state.is_url_mode = False
                self.app_state.input_active  = False; self.radial_menu.update_overlay_logic()
        return False

    def handle_mouse_release(self, event):
        if self.is_shift_dragging:
            self.is_shift_dragging = False; self.shift_drag_start_pos = None

    def handle_wheel_event(self, event) -> bool:
        if not self.radial_menu.isVisible(): return False
        if self._on_center(event.position().toPoint()):
            if event.angleDelta().y() > 0: self.app_state.prev_page()
            else:                          self.app_state.next_page()
            self.radial_menu.reload_page_data(); return True
        return False

    def handle_key_press(self, event: QKeyEvent):
        k = event.key(); self.app_state.keys_held[k] = time.time()
        if self.app_state.is_setting_mode:
            self.handle_setting_mode_keypress(event); return
        if self.app_state.input_active and self.app_state.is_url_mode:
            self.handle_url_name_input(event); return
        mods = event.modifiers()
        if k == Qt.Key_Backspace:
            if self.app_state.editing_index is not None: self.delete_current_sector(); return
            if self.app_state.hovered_sector_index is not None: self.delete_hovered_sector(); return
        if mods & Qt.ControlModifier and k == Qt.Key_C:
            if self.app_state.editing_index is not None and self.app_state.is_url_mode:
                self.copy_url_to_clipboard()
        elif mods & Qt.ControlModifier and k == Qt.Key_V:
            if self.app_state.editing_index is not None and self.app_state.is_url_mode:
                self.paste_url_from_clipboard()

    def handle_key_release(self, event: QKeyEvent):
        self.app_state.keys_held.pop(event.key(), None)

    def handle_drag_enter(self, event) -> bool:
        if self.radial_menu.isVisible() and event.mimeData().hasUrls():
            if self.app_state.editing_index is None:
                for i in range(len(self.radial_menu.triangles)):
                    gi = self.app_state.get_global_sector_index(i)
                    if not self.data_manager.get_sector_data(gi).has_data():
                        self.app_state.editing_index = i; self.app_state.is_url_mode = False
                        self.radial_menu.drop_zone.update_info(i, self.app_state.current_page)
                        self.radial_menu.drop_zone.show(); self.radial_menu.drop_zone.raise_(); break
            event.acceptProposedAction(); return True
        return False

    def handle_drop(self, event):
        if not self.radial_menu.isVisible(): return
        urls = event.mimeData().urls()
        if not urls: return
        fp = urls[0].toLocalFile()
        if not fp: return
        if self.app_state.editing_index is None:
            for i in range(len(self.radial_menu.triangles)):
                gi = self.app_state.get_global_sector_index(i)
                if not self.data_manager.get_sector_data(gi).has_data():
                    self.app_state.editing_index = i; self.app_state.is_url_mode = False
                    self.radial_menu.drop_zone.update_info(i, self.app_state.current_page)
                    self.radial_menu.drop_zone.show(); self.radial_menu.drop_zone.raise_(); break
        if self.app_state.editing_index is not None:
            cname = self.radial_menu.drop_zone.name_input.text().strip()
            self.handle_dropped_file(fp, cname)
            self.radial_menu.drop_zone.name_input.clear()
            event.acceptProposedAction()

    def handle_dropped_file(self, file_path: str, custom_name: str = ""):
        if self.app_state.editing_index is None: return
        gi = self.app_state.get_global_sector_index(self.app_state.editing_index)
        sd = self.data_manager.get_sector_data(gi)
        if os.path.isfile(file_path):
            ext = os.path.splitext(file_path)[1].lower()
            if ext in (".png", ".jpg", ".jpeg", ".ico", ".bmp"):
                sd.icon_path = file_path
                self.data_manager.update_sector_data(gi, sd)
                self.radial_menu.reload_sector_data(self.app_state.editing_index)
                self.app_state.editing_index = None; self.app_state.is_url_mode = False
                self.radial_menu.update_overlay_logic(); return
        sd.exe_path = file_path
        if custom_name:
            sd.name = custom_name
        elif os.path.isdir(file_path):
            sd.name = os.path.basename(file_path) or os.path.splitdrive(file_path)[0] or "ROOT"
        elif os.path.isfile(file_path):
            sd.name = os.path.splitext(os.path.basename(file_path))[0]
        self.data_manager.update_sector_data(gi, sd)
        self.radial_menu.reload_sector_data(self.app_state.editing_index)
        # BUG FIX #5: call update_sectors_data() not the old load_sectors()
        if hasattr(self.radial_menu, "search_ui"):
            self.radial_menu.search_ui.update_sectors_data()
        self.app_state.editing_index = None; self.app_state.is_url_mode = False
        self.radial_menu.update_overlay_logic()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _on_center(self, pos: QPoint) -> bool:
        return math.hypot(pos.x() - self.radial_menu.center.x(),
                          pos.y() - self.radial_menu.center.y()) < Constants.CENTER_RADIUS

    def _sector_at(self, pos: QPoint) -> Optional[int]:
        dx = pos.x() - self.radial_menu.center.x()
        dy = pos.y() - self.radial_menu.center.y()
        dist = math.hypot(dx, dy)
        if not (Constants.CENTER_RADIUS <= dist < Constants.RADIUS + 20):
            return None
        a    = (math.atan2(dy, dx) + math.pi / 2) % (2 * math.pi)
        step = 2 * math.pi / len(self.radial_menu.triangles)
        idx  = int(a // step)
        return idx if 0 <= idx < len(self.radial_menu.triangles) else None

    def handle_left_click_on_triangle(self, index: int):
        tri = self.radial_menu.triangles[index]
        if tri.sector_data.url:
            ok = self.open_url(tri.sector_data.url, tri.sector_data.use_incognito)
            if ok and tri.sector_data.enable_tracking:
                if (hasattr(self.radial_menu, "tracker_thread")
                        and self.radial_menu.tracker_thread.cdp_tracker):
                    url = tri.sector_data.url
                    QTimer.singleShot(1000, lambda: self.radial_menu.tracker_thread.bind_via_cdp(index, url))
                else:
                    # BUG FIX #3: removed time.sleep(0.5) from bind; use async thread instead
                    threading.Thread(target=self._bind_async, args=(index,), daemon=True).start()
            self.toggle_launcher()
        elif tri.sector_data.exe_path:
            self.open_file_or_folder(tri.sector_data.exe_path); self.toggle_launcher()
        else:
            self.app_state.editing_index = index; self.app_state.is_url_mode = False
            self.radial_menu.update_overlay_logic()

    def _bind_async(self, sector_index: int):
        """BUG FIX #3: binding runs in daemon thread, never blocks main thread."""
        time.sleep(0.8)    # short wait for window to activate — in background thread
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd: return
        for idx, h in list(self.app_state.bound_windows.items()):
            if h == hwnd and idx != sector_index:
                del self.app_state.bound_windows[idx]
        self.app_state.bound_windows[sector_index] = hwnd
        print(f"[BIND] sector {sector_index} → HWND {hwnd}")

    def handle_right_click(self, index: int):
        mods = QApplication.keyboardModifiers()
        if mods & Qt.ShiftModifier:
            if self.app_state.editing_index == index and self.app_state.is_url_mode:
                self.app_state.editing_index = None; self.app_state.is_url_mode = False
            else:
                self.app_state.editing_index = index; self.app_state.is_url_mode = True
        else:
            if self.app_state.editing_index == index and not self.app_state.is_url_mode:
                self.app_state.editing_index = None
            else:
                self.app_state.editing_index = index; self.app_state.is_url_mode = False
        self.radial_menu.update_overlay_logic()

    def toggle_launcher(self):
        if self.app_state.can_toggle():
            self.app_state.visible = not self.app_state.visible
            self.radial_menu.setVisible(self.app_state.visible)
            if self.app_state.visible: self.move_window_to_mouse()

    def toggle_settings(self):
        self.app_state.is_setting_mode = not self.app_state.is_setting_mode
        self.radial_menu.update_overlay_logic()

    def show_startup_dialog(self):
        self.radial_menu.ask_startup_setting()

    def handle_setting_mode_keypress(self, event: QKeyEvent):
        k = event.key(); mods = event.modifiers()
        if k in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta): return
        if (mods & Qt.ShiftModifier) and k in (Qt.Key_Period, 46): return
        if k == Qt.Key_Escape:
            self.app_state.is_setting_mode = False
            self.app_state.key_combination_detected = False
            self.radial_menu.update_overlay_logic(); return
        if k in (Qt.Key_Return, Qt.Key_Enter):
            if self.app_state.detected_key:
                sui = self.radial_menu.setting_ui
                if sui.is_selecting_launcher:
                    self.radial_menu.hotkey_manager.set_launcher_hotkey(
                        self.app_state.detected_modifiers, self.app_state.detected_key)
                elif sui.is_selecting_search:
                    self.radial_menu.hotkey_manager.set_search_hotkey_from_set(
                        self.app_state.detected_modifiers, self.app_state.detected_key)
            sui = self.radial_menu.setting_ui
            sui.is_selecting_launcher = sui.is_selecting_search = False
            self.app_state.key_combination_detected = False
            self.radial_menu.update_overlay_logic(); return
        sui = self.radial_menu.setting_ui
        if sui and (sui.is_selecting_launcher or sui.is_selecting_search):
            nm: Set[int] = set()
            if mods & Qt.ShiftModifier:   nm.add(Constants.VK_SHIFT)
            if mods & Qt.ControlModifier: nm.add(Constants.VK_CONTROL)
            if mods & Qt.AltModifier:     nm.add(Constants.VK_MENU)
            if mods & Qt.MetaModifier:    nm.add(Constants.VK_LWIN)
            nk = sui._qt_to_vk(k)
            if Constants.VK_SHIFT in nm and nk == Constants.VK_PERIOD: return
            self.app_state.detected_modifiers = nm; self.app_state.detected_key = nk
            sui.update_display(nm, nk)

    def handle_setting_mode_mouse_press(self, event):
        button = event.button()
        if button == Qt.LeftButton:
            if self.app_state.key_combination_detected:
                self.radial_menu.hotkey_manager.set_launcher_hotkey(
                    self.app_state.detected_modifiers, self.app_state.detected_key)
            self.app_state.is_setting_mode = False
            self.app_state.key_combination_detected = False
            self.radial_menu.update_overlay_logic()
        elif button == Qt.RightButton:
            self.app_state.is_setting_mode = False
            self.app_state.key_combination_detected = False
            self.radial_menu.update_overlay_logic()

    def handle_url_name_input(self, event: QKeyEvent):
        k = event.key()
        if k in (Qt.Key_Return, Qt.Key_Enter):
            name = self.app_state.input_text.strip() or "LINK"
            if self.app_state.editing_index is not None:
                gi = self.app_state.get_global_sector_index(self.app_state.editing_index)
                sd = self.data_manager.get_sector_data(gi); sd.name = name
                self.data_manager.update_sector_data(gi, sd)
                self.radial_menu.reload_sector_data(self.app_state.editing_index)
            self.app_state.input_active = False; self.app_state.input_text = ""
            self.radial_menu.update_overlay_logic()
        elif k == Qt.Key_Backspace:
            self.app_state.input_text = self.app_state.input_text[:-1]
        elif k == Qt.Key_Escape:
            self.app_state.input_active = False; self.app_state.input_text = ""
            self.radial_menu.update_overlay_logic()
        else:
            ch = event.text()
            if ch: self.app_state.input_text += ch

    def reset_and_open_settings(self):
        if time.time() - self.app_start_time < 0.5: return
        if self.radial_menu.setting_ui and self.radial_menu.setting_ui.isVisible():
            self.radial_menu.setting_ui.handle_shift_period_hotkey()
        else:
            self.radial_menu.setVisible(True); self.app_state.visible = True
            self.move_window_to_mouse()
            for tri in self.radial_menu.triangles:
                tri._current_offset = 0.0; tri._fade_factor = 0.0
            self.app_state.is_setting_mode = True; self.radial_menu.update_overlay_logic()

    def move_window_to_mouse(self):
        sg = QApplication.primaryScreen().availableGeometry()
        cp = QCursor.pos()
        x  = max(sg.left(), min(cp.x() - Constants.WIDTH  // 2, sg.right()  - Constants.WIDTH))
        y  = max(sg.top(),  min(cp.y() - Constants.HEIGHT // 2, sg.bottom() - Constants.HEIGHT))
        self.radial_menu.move(x, y)
        self.radial_menu.center = QPoint(Constants.WIDTH // 2, Constants.HEIGHT // 2)

    def open_url(self, url: str, incognito: bool = False) -> bool:
        if not url: return False
        if "://" not in url: url = "https://" + url
        try:
            if incognito:
                for p, arg in [
                    (r"C:\Program Files\Google\Chrome\Application\chrome.exe", "--incognito"),
                    (r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe", "--incognito"),
                    (r"C:\Program Files\Microsoft\Edge\Application\msedge.exe", "-inprivate"),
                ]:
                    if os.path.exists(p):
                        subprocess.Popen([p, arg, url]); return True
                webbrowser.open(url)
            else:
                webbrowser.open(url)
            return True
        except Exception as e:
            print(f"[EventHandler] open_url: {e}"); return False

    def open_file_or_folder(self, path: str) -> bool:
        try:
            if os.path.exists(path): os.startfile(path); return True
            return False
        except Exception as e:
            print(f"[EventHandler] open_file: {e}"); return False

    def copy_url_to_clipboard(self):
        if pyperclip is None or self.app_state.editing_index is None: return
        gi = self.app_state.get_global_sector_index(self.app_state.editing_index)
        url = self.data_manager.get_sector_data(gi).url
        if url: pyperclip.copy(url)

    def paste_url_from_clipboard(self):
        if self.app_state.editing_index is None: return
        try:
            text = (pyperclip.paste().strip() if pyperclip else "") or \
                   self.data_manager.get_default_web_url()
            if not text: return
            if "://" not in text: text = "https://" + text
            gi = self.app_state.get_global_sector_index(self.app_state.editing_index)
            sd = self.data_manager.get_sector_data(gi)
            if not sd.name: sd.name = "LINK"
            sd.url = text
            self.data_manager.update_sector_data(gi, sd)
            self.radial_menu.reload_sector_data(self.app_state.editing_index)
        except Exception as e:
            print(f"[EventHandler] paste: {e}")

    def delete_hovered_sector(self):
        hi = self.app_state.hovered_sector_index
        if hi is None: return
        self.data_manager.delete_sector_data(self.app_state.get_global_sector_index(hi))
        self.radial_menu.reload_sector_data(hi)
        self.app_state.hovered_sector_index = None; self.radial_menu.update_overlay_logic()

    def delete_current_sector(self):
        ei = self.app_state.editing_index
        if ei is None: return
        self.data_manager.delete_sector_data(self.app_state.get_global_sector_index(ei))
        self.radial_menu.reload_sector_data(ei)
        self.app_state.editing_index = None; self.app_state.is_url_mode = False
        self.radial_menu.update_overlay_logic()

    def add_new_page(self):
        if self.app_state.add_new_page(): self.radial_menu.reload_page_data()

    def delete_current_page(self):
        if self.app_state.remove_current_page(): self.radial_menu.reload_page_data()


# ══════════════════════════════════════════════════════════════════════════════
#  RADIAL MENU BASE
# ══════════════════════════════════════════════════════════════════════════════

class RadialMenu(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(Constants.WIDTH, Constants.HEIGHT)
        # BUG FIX #2: use singleton DataManager
        self.app_state    = AppState()
        self.data_manager = DataManager.instance()
        sp = self.data_manager.get_max_page_needed()
        if sp > self.app_state.total_pages:
            self.app_state.total_pages = sp
        self.center = QPoint(Constants.WIDTH // 2, Constants.HEIGHT // 2)
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.update_animations)
        self.animation_timer.start(16)

    def update_animations(self): pass

    def paintEvent(self, _):
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.fillRect(self.rect(), Qt.transparent)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW  (BUG FIX #1 integrated)
# ══════════════════════════════════════════════════════════════════════════════

class MainWindow(RadialMenu):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "a.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.hotkey_manager = HotkeyManager()
        self.hotkey_manager.hotkey_triggered.connect(self.on_hotkey_triggered)
        app = QApplication.instance()
        if app:
            self.hotkey_manager.install_event_filter(app)
        self._setup_ui()
        self.search_ui = SearchUIWidget(parent=self)
        self.search_ui.set_data_manager(self.data_manager)
        self.data_manager.data_changed.connect(self.search_ui.update_sectors_data)
        self.search_ui.hide()
        self.event_handler = EventHandler(self)
        self.reload_page_data()
        self.setAcceptDrops(True)
        self.tracker_thread = BrowserTracker(self.data_manager, self.app_state)
        self.tracker_thread.url_found.connect(self.on_tracker_update)
        self.tracker_thread.start()
        # Text opacity
        self.text_timer = QTimer(self); self.text_timer.setSingleShot(True)
        self.text_timer.timeout.connect(self.fade_out_text)
        self.label_hide_timer = QTimer(self); self.label_hide_timer.setSingleShot(True)
        self.label_hide_timer.timeout.connect(self.start_fade_out_labels)
        self.text_fade_anim = QPropertyAnimation(self, b"text_opacity_prop")
        self.text_fade_anim.setDuration(500)
        self.text_fade_anim.setStartValue(1.0); self.text_fade_anim.setEndValue(0.0)
        self.trigger_text_reveal()
        self.check_first_run_startup_dialog()
        # ── Flask + Tailscale ──────────────────────────────────────────────
        self.flask_thread: Optional[FlaskServerThread] = None
        self.ts_manager = TailscaleManager(self.data_manager, self)
        self.ts_manager.status_changed.connect(self._on_ts_status)
        if self.data_manager.server_config.get("enabled", True):
            QTimer.singleShot(1500, self.start_remote_server)
        # ── System tray ────────────────────────────────────────────────────
        self._setup_tray()
        # ── Auto-hide khi click ngoài launcher ─────────────────────────────
        self._outside_click_hook = MouseButtonHook(
            callback=lambda btn: None,  # MB4/5/6 xử lý ở SearchUI hook riêng
            outside_hide_cb=self._auto_hide_on_outside_click,
            parent=self,
        )
        self._outside_click_hook.start()
        # QTimer cập nhật rect cho hook mỗi 50ms — hoàn toàn trên main thread
        self._rect_sync_timer = QTimer(self)
        self._rect_sync_timer.setInterval(50)
        self._rect_sync_timer.timeout.connect(self._sync_hook_rect)
        self._rect_sync_timer.start()

    def _setup_ui(self):
        self.triangles: List[TriangleWidget] = []
        for i in range(Constants.NUM_SIDES):
            t = TriangleWidget(i, self); t.resize(Constants.WIDTH, Constants.HEIGHT)
            t.show(); self.triangles.append(t)
        self.center_circle = CenterCircleWidget(self)
        self.center_circle.resize(Constants.WIDTH, Constants.HEIGHT); self.center_circle.show()
        self.drop_zone = DropZoneWidget(self)
        self.drop_zone.move((Constants.WIDTH - Constants.DROP_ZONE_WIDTH) // 2, Constants.DROP_ZONE_Y)
        self.drop_zone.hide()
        self.url_ui = UrlUIWidget(self)
        self.url_ui.move((Constants.WIDTH - Constants.URL_UI_WIDTH) // 2, Constants.URL_UI_Y)
        self.url_ui.hide()
        self.setting_ui = SettingUIWidget(self)
        self.setting_ui.move(
            (Constants.WIDTH - Constants.SETTING_UI_WIDTH) // 2,
            Constants.HEIGHT // 2 + Constants.RADIUS + 30,
        )
        self.setting_ui.hide()

    # ── Remote server helpers ─────────────────────────────────────────────────

    def start_remote_server(self):
        """Khởi động Flask + Tailscale."""
        if not _FLASK_OK:
            self._on_flask_status("error:Flask chưa cài (pip install flask)")
            return
        # Flask
        if self.flask_thread and self.flask_thread.isRunning():
            return
        self.flask_thread = FlaskServerThread(self.data_manager, self)
        self.flask_thread.status_changed.connect(self._on_flask_status)
        self.flask_thread.start()
        # Tailscale
        if self.data_manager.server_config.get("use_tailscale", True):
            self.ts_manager.start_tunnel()

    def stop_remote_server(self):
        """Dừng Flask + Tailscale."""
        if self.data_manager.server_config.get("use_tailscale", True):
            self.ts_manager.stop_tunnel()
        if self.flask_thread:
            self.flask_thread.stop_server()
            self.flask_thread.quit()
            self.flask_thread.wait(2000)
            self.flask_thread = None
        self._update_tray_status("stopped")

    @Slot(str)
    def _on_flask_status(self, status: str):
        print(f"[Flask] {status}")
        if hasattr(self, "setting_ui"):
            self.setting_ui.update_server_status(status)
        self._update_tray_status(status)

    @Slot(str)
    def _on_ts_status(self, status: str):
        print(f"[Tailscale] {status}")
        if hasattr(self, "setting_ui"):
            self.setting_ui.update_server_status(status)
        self._update_tray_status(status)

    # ── System tray ───────────────────────────────────────────────────────────

    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self)
        # Dùng icon app nếu có, fallback icon trắng
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "a.ico")
        if os.path.exists(icon_path):
            self.tray.setIcon(QIcon(icon_path))
        else:
            px = QPixmap(16, 16); px.fill(QColor(140, 80, 255))
            self.tray.setIcon(QIcon(px))
        self.tray.setToolTip("PentaKuRu — đang chạy")
        menu = QMenu()
        act_show   = QAction("Hiện launcher", self)
        act_server = QAction("Bật/Tắt server", self)
        act_quit   = QAction("Thoát", self)
        act_show.triggered.connect(lambda: (self.show(), self.raise_()))
        act_server.triggered.connect(
            lambda: self.stop_remote_server()
            if (self.flask_thread and self.flask_thread.isRunning())
            else self.start_remote_server()
        )
        act_quit.triggered.connect(self.close)
        menu.addAction(act_show)
        menu.addAction(act_server)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.event_handler.toggle_launcher()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None
        )
        self.tray.show()

    def _update_tray_status(self, status: str):
        if not hasattr(self, "tray"): return
        if status == "running" or status.startswith("running:"):
            ip = status.split(":", 1)[1] if ":" in status and status.startswith("running:") else ""
            tip = f"PentaKuRu ● Server đang chạy  [{ip}]" if ip else "PentaKuRu ● Server đang chạy"
            self.tray.setToolTip(tip)
        elif status in ("stopped", "not_connected"):
            self.tray.setToolTip("PentaKuRu ○ Server đã dừng")
        elif status == "no_exe":
            self.tray.setToolTip("PentaKuRu ⚠ Tailscale chưa cài")
        elif status.startswith("error:"):
            self.tray.setToolTip(f"PentaKuRu ✗ {status[6:]}")

    @Slot(int, str)
    def on_tracker_update(self, sector_idx: int, new_url: str):
        if not self.isVisible(): return
        if not (0 <= sector_idx < len(self.triangles)): return
        QTimer.singleShot(100, lambda: self._apply_tracker(sector_idx, new_url))

    def _apply_tracker(self, idx: int, url: str):
        try:
            self.reload_sector_data(idx)
            if self.url_ui.isVisible() and self.url_ui.sector_index == idx:
                self.url_ui.update_data(idx, self.data_manager.get_sector_data(
                    self.app_state.get_global_sector_index(idx)))
            self.triangles[idx].update()
        except Exception as e:
            print(f"[UI UPDATE] {e}")

    def update_animations(self):
        self.update_overlay_logic()
        self.center_circle.update_fade(self.app_state.center_fade)
        auto_hide = self.data_manager.app_config.get("text_auto_hide", True)
        if auto_hide:
            diff   = time.time() - self.app_state.last_text_active_time
            target = 1.0 if diff < Constants.TEXT_VISIBLE_DURATION else 0.0
            if abs(self.app_state.text_opacity - target) > 0.01:
                d = Constants.TEXT_FADE_SPEED
                self.app_state.text_opacity += d if self.app_state.text_opacity < target else -d
                self.app_state.text_opacity = max(0.0, min(1.0, self.app_state.text_opacity))
                for t in self.triangles: t.update()
        else:
            if abs(self.app_state.text_opacity - 1.0) > 0.01:
                self.app_state.text_opacity = 1.0
                for t in self.triangles: t.update()
        if self.app_state.show_page_indicator and \
                time.time() - self.app_state.page_indicator_time > 1.5:
            self.app_state.show_page_indicator = False; self.center_circle.update()

    def update_overlay_logic(self):
        if self.app_state.is_setting_mode:
            if not self.setting_ui.isVisible():
                if self.hotkey_manager.running: self.hotkey_manager.stop()
                self.setting_ui.adjustSize()
                sw, sh = self.setting_ui.width(), self.setting_ui.height()
                xp = (Constants.WIDTH  - sw) // 2
                yp = Constants.HEIGHT // 2 + Constants.RADIUS + 20
                if yp + sh > Constants.HEIGHT - 50: yp = Constants.HEIGHT - sh - 50
                self.setting_ui.move(xp, yp)
                self.setting_ui.show_animated(); self.setting_ui.raise_(); self.setting_ui.setFocus()
                self.drop_zone.hide(); self.url_ui.hide()
            self.setting_ui.update_display(self.app_state.detected_modifiers, self.app_state.detected_key)
            hm = self.hotkey_manager
            lk = hm.launcher_key
            l_text = "Default (Shift + /)" if not lk else self.setting_ui.format_keys(hm.launcher_modifiers, lk)
            sm = hm.search_hotkey.get("mods", 0); sk = hm.search_hotkey.get("key", 0)
            ss: Set[int] = set()
            if sm & 0x0001: ss.add(Constants.VK_MENU)
            if sm & 0x0002: ss.add(Constants.VK_CONTROL)
            if sm & 0x0004: ss.add(Constants.VK_SHIFT)
            if sm & 0x0008: ss.add(Constants.VK_LWIN)
            s_text = "Default (Alt + Space)" if (sk == Constants.SEARCH_DEFAULT_KEY and sm == Constants.SEARCH_DEFAULT_MODS) \
                else self.setting_ui.format_keys(ss, sk)
            self.setting_ui.update_current_hotkeys_display(l_text, s_text)
            return
        else:
            if self.setting_ui.isVisible():
                self.setting_ui.hide_animated()
                if not self.hotkey_manager.running: self.hotkey_manager.start()
        idx = self.app_state.editing_index
        if idx is not None:
            gi = self.app_state.get_global_sector_index(idx)
            sd = self.data_manager.get_sector_data(gi)
            if self.app_state.is_url_mode:
                if not self.url_ui.isVisible() or self.url_ui.sector_index != idx:
                    self.url_ui.update_data(idx, sd); self.url_ui.show()
                    self.url_ui.raise_(); self.url_ui.setFocus(); self.drop_zone.hide()
            else:
                if not self.drop_zone.isVisible():
                    self.drop_zone.update_info(idx, self.app_state.current_page)
                    self.drop_zone.show(); self.drop_zone.raise_(); self.drop_zone.setFocus(); self.url_ui.hide()
        else:
            self.drop_zone.hide(); self.url_ui.hide()

    def apply_new_hotkey(self, key: int, mods: Set[int]):
        if hasattr(self, "hotkey_manager"):
            self.hotkey_manager.update_trigger(key, mods)

    def reload_page_data(self):
        start = self.app_state.current_page * Constants.SECTORS_PER_PAGE
        for i, tri in enumerate(self.triangles):
            tri.load_data(self.data_manager.get_sector_data(start + i)); tri.update()

    def reload_sector_data(self, local_idx: int):
        if 0 <= local_idx < len(self.triangles):
            gi = self.app_state.get_global_sector_index(local_idx)
            sd = self.data_manager.get_sector_data(gi)
            self.triangles[local_idx].load_data(sd); self.triangles[local_idx].update()
            if self.url_ui.isVisible() and self.url_ui.sector_index == local_idx:
                self.url_ui.update_data(local_idx, sd)

    @Slot(int)
    def on_hotkey_triggered(self, hotkey_id: int):
        if hotkey_id == Constants.ID_LAUNCHER:
            if self.search_ui.isVisible():
                self.search_ui.hide(); self.search_ui.search_input.clear()
                self.search_ui.list_widget.hide()
            self.event_handler.toggle_launcher()

        elif hotkey_id == Constants.ID_SEARCH:
            if self.isVisible():
                # BUG FIX #1: was app_state.page = 1 (wrong attr), now current_page = 0
                self.app_state.editing_index  = None
                self.app_state.is_url_mode    = False
                self.app_state.input_active   = False
                self.app_state.is_setting_mode = False
                self.app_state.current_page   = 0    # ← BUG FIX #1
                self.hide(); self.app_state.visible = False
            if self.search_ui.isVisible():
                self.search_ui.hide(); self.search_ui.search_input.clear()
                self.app_state.text_opacity = 1.0; self.update()
            else:
                self.search_ui.show_search()

        elif hotkey_id == 3:
            # BUG FIX #6: don't reference search_ui.PH_GOOGLE directly (now property)
            if self.search_ui.isVisible():
                self.search_ui.hide(); self.search_ui.search_input.clear()
            if self.isVisible():
                self.app_state.editing_index = None; self.app_state.is_url_mode = False
                self.app_state.input_active  = False; self.app_state.is_setting_mode = False
                self.hide(); self.app_state.visible = False
            self.event_handler.reset_and_open_settings()

    # ── Text opacity property / animation ────────────────────────────────────

    def _get_top(self): return self.app_state.text_opacity
    def _set_top(self, v):
        self.app_state.text_opacity = v; self.update()
    text_opacity_prop = Property(float, _get_top, _set_top)

    def trigger_text_reveal(self):
        if not self.data_manager.app_config.get("text_auto_hide", True):
            self.app_state.text_opacity = 1.0; self.update(); return
        self.text_fade_anim.stop(); self.app_state.text_opacity = 1.0; self.update()
        self.text_timer.start(1800)

    def fade_out_text(self):
        self.text_fade_anim.start()

    def update_labels_visibility_mode(self):
        if self.app_state.auto_hide_labels:
            self.reset_label_timer()
        else:
            self.label_hide_timer.stop()
            for t in self.triangles:
                t.fade_animation.stop(); t._fade_factor = 1.0; t.update()

    def reset_label_timer(self):
        self.label_hide_timer.stop()
        for t in self.triangles:
            t.fade_animation.stop(); t._fade_factor = 1.0; t.update()
        if self.app_state.auto_hide_labels:
            self.label_hide_timer.start(1800)

    def start_fade_out_labels(self):
        if not self.app_state.auto_hide_labels:
            for t in self.triangles:
                if t._fade_factor < 1.0:
                    t.fade_animation.stop(); t._fade_factor = 1.0; t.update()
            return
        for t in self.triangles:
            t.fade_animation.setDuration(500)
            t.fade_animation.setStartValue(t._fade_factor)
            t.fade_animation.setEndValue(0.0); t.fade_animation.start()

    # ── Qt event forwarding ───────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and (event.modifiers() & Qt.ShiftModifier):
            self.ask_startup_setting(); event.accept()
        elif self.event_handler.handle_mouse_press(event):
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.event_handler.handle_mouse_release(event); super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if self.event_handler.handle_wheel_event(event): event.accept()
        else: super().wheelEvent(event)

    def keyPressEvent(self, event):
        self.event_handler.handle_key_press(event)

    def keyReleaseEvent(self, event):
        self.event_handler.handle_key_release(event)

    def dragEnterEvent(self, event):
        self.event_handler.handle_drag_enter(event)

    def dropEvent(self, event):
        self.event_handler.handle_drop(event)

    def closeEvent(self, event):
        print("[CLEANUP] Shutting down...")
        if hasattr(self, "tray"):           self.tray.hide()
        if hasattr(self, "_rect_sync_timer"): self._rect_sync_timer.stop()
        if hasattr(self, "_outside_click_hook"): self._outside_click_hook.stop()
        if hasattr(self, "ts_manager"):     self.ts_manager.stop_tunnel()
        if hasattr(self, "flask_thread") and self.flask_thread:
            self.flask_thread.stop_server()
            self.flask_thread.quit()
            self.flask_thread.wait(2000)
        if hasattr(self, "tracker_thread"): self.tracker_thread.stop()
        if hasattr(self, "hotkey_manager"): self.hotkey_manager.cleanup()
        if hasattr(self, "search_ui"):      self.search_ui.cleanup()
        if hasattr(self, "animation_timer"): self.animation_timer.stop()
        if hasattr(self, "event_handler"):
            self.event_handler.mouse_timer.stop()
            self.event_handler.key_timer.stop()
        if hasattr(self, "data_manager"):
            self.data_manager.save_all_data()
            self.data_manager.save_hotkey_data()
            self.data_manager.save_config()
        self.app_state.visible = False
        print("[CLEANUP] Done"); super().closeEvent(event)

    # ── Auto-hide on outside click ────────────────────────────────────────────

    def _sync_hook_rect(self):
        """Chạy trên main thread mỗi 50ms — cập nhật rect cache cho hook thread."""
        if self.isVisible() and not self.app_state.is_setting_mode \
                and not self.app_state.input_active \
                and not self.app_state.is_url_mode:
            g = self.geometry()
            self._outside_click_hook.update_rect((g.x(), g.y(), g.width(), g.height()))
        else:
            # Truyền None → hook không xử lý click khi launcher ẩn / đang nhập liệu
            self._outside_click_hook.update_rect(None)

    def _auto_hide_on_outside_click(self):
        """Gọi từ Qt signal (main thread) — ẩn launcher an toàn."""
        if not self.isVisible():
            return
        self.app_state.editing_index = None
        self.app_state.is_url_mode   = False
        self.app_state.input_active  = False
        self.hide()
        self.app_state.visible = False

    # ── Startup dialog ────────────────────────────────────────────────────────

    def ask_startup_setting(self):
        reply = QMessageBox.question(
            self, "Cấu hình hệ thống",
            "Bạn có muốn ứng dụng khởi động cùng Windows không?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        ok = SystemUtils.set_startup_with_windows(reply == QMessageBox.Yes)
        if ok:
            self.data_manager.save_startup_config(reply == QMessageBox.Yes)
            QMessageBox.information(self, "Thành công",
                f"Đã {'BẬT' if reply == QMessageBox.Yes else 'TẮT'} khởi động cùng Windows.")
        else:
            QMessageBox.warning(self, "Lỗi", "Không thể truy cập Registry. Hãy chạy Admin.")

    def check_first_run_startup_dialog(self):
        if self.data_manager.load_startup_config() is None:
            r = QMessageBox.question(
                self, "Startup Preference",
                "Do you want to start this application with Windows?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
            )
            en = r == QMessageBox.Yes
            SystemUtils.set_startup_with_windows(en)
            self.data_manager.save_startup_config(en)


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    # Init the singleton before any widget touches it
    DataManager._instance = None   # ensure fresh start
    DataManager()                  # creates singleton

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()