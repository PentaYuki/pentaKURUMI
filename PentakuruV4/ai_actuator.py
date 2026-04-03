# ai_actuator.py
import time
import json
import os
import threading
from pynput import mouse, keyboard
import pyautogui
import numpy as np
from PIL import Image
from collections import deque
import cv2
from hashlib import sha1
import logging

logger = logging.getLogger(__name__)

# Thư mục lưu demo
DEMO_DIR = "demos"
os.makedirs(DEMO_DIR, exist_ok=True)

try:
    from skimage.metrics import structural_similarity as ssim
    SSIM_AVAILABLE = True
except ImportError:
    SSIM_AVAILABLE = False
    logger.warning("skimage không khả dụng, sử dụng pixel-based detection")

class ScreenChangeDetector:
    """Phát hiện thay đổi màn hình THÔNG MINH với SSIM"""
    
    def __init__(self, change_threshold=0.15, max_wait_time=5.0, check_interval=0.5):
        self.change_threshold = change_threshold
        self.max_wait_time = max_wait_time
        self.check_interval = check_interval
        self.screenshot_history = deque(maxlen=3)
        self.use_ssim = SSIM_AVAILABLE
        
        logger.info(f"🔍 ScreenChangeDetector - SSIM: {'BẬT' if self.use_ssim else 'TẮT'}")
    
    def capture_screen(self, region=None):
        try:
            screenshot = pyautogui.screenshot(region=region)
            screen_array = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
            self.screenshot_history.append(screen_array)
            return screen_array
        except Exception as e:
            logger.warning(f"Lỗi chụp màn hình: {e}")
            return None
    
    def _pixel_change_detection(self, img1, img2):
        if img1 is None or img2 is None:
            return 1.0
        if img1.shape != img2.shape:
            img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))
        diff = cv2.absdiff(img1, img2)
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        change_percentage = np.sum(thresh) / (255.0 * thresh.size)
        return change_percentage

    def _structural_similarity_detection(self, img1, img2):
        try:
            if img1.shape != img2.shape:
                img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))
            score = ssim(img1, img2, 
                        win_size=min(7, img1.shape[0]//10, img1.shape[1]//10),
                        channel_axis=None if len(img1.shape) == 2 else -1)
            change_percentage = 1.0 - score
            if logger.isEnabledFor(logging.DEBUG):
                pixel_change = self._pixel_change_detection(img1, img2)
                logger.debug(f"🔍 SSIM: {change_percentage:.3f}, Pixel: {pixel_change:.3f}")
            return change_percentage
        except Exception as e:
            logger.warning(f"Lỗi SSIM: {e}, chuyển sang pixel detection")
            return self._pixel_change_detection(img1, img2)
    
    def calculate_change_percentage(self, img1, img2):
        if img1 is None or img2 is None:
            return 1.0
        if self.use_ssim:
            return self._structural_similarity_detection(img1, img2)
        else:
            return self._pixel_change_detection(img1, img2)
    
    def wait_for_change(self, timeout=None, context=""):
        if timeout is None:
            timeout = self.max_wait_time
        start_time = time.time()
        initial_screen = self.capture_screen()
        if initial_screen is None:
            return True
        logger.debug(f"🔍 Đang chờ thay đổi màn hình {context}...")
        consecutive_changes = 0
        required_consecutive = 2
        while time.time() - start_time < timeout:
            current_screen = self.capture_screen()
            if current_screen is None:
                time.sleep(self.check_interval)
                continue
            change_pct = self.calculate_change_percentage(initial_screen, current_screen)
            if change_pct > self.change_threshold:
                consecutive_changes += 1
                if consecutive_changes >= required_consecutive:
                    logger.debug(f"✅ Đã phát hiện thay đổi {context}: {change_pct:.1%}")
                    return True
            else:
                consecutive_changes = 0
            time.sleep(self.check_interval)
        logger.debug(f"⏰ Timeout chờ thay đổi {context} sau {timeout}s")
        return False

class SmartScreenDetector:
    """Phát hiện thay đổi màn hình THÔNG MINH với multiple strategies"""
    
    def __init__(self, change_threshold=0.1, max_wait=8.0, check_interval=0.3):
        self.change_threshold = change_threshold
        self.max_wait = max_wait
        self.check_interval = check_interval
        self.screenshot_cache = deque(maxlen=3)
        self.detection_strategies = [
            self._pixel_change_detection,
            self._structural_similarity_detection,
            self._contour_based_detection
        ]
    
    def capture_screen(self, region=None, reduce_resolution=True):
        try:
            screenshot = pyautogui.screenshot(region=region)
            screen_array = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
            if reduce_resolution:
                screen_array = cv2.resize(screen_array, (0, 0), fx=0.5, fy=0.5)
            self.screenshot_cache.append(screen_array)
            return screen_array
        except Exception as e:
            logger.warning(f"Lỗi chụp màn hình: {e}")
            return None
    
    def _pixel_change_detection(self, img1, img2):
        if img1 is None or img2 is None: return 1.0
        if img1.shape != img2.shape:
            img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))
        diff = cv2.absdiff(img1, img2)
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        return np.sum(thresh) / (255.0 * thresh.size)
    
    def _structural_similarity_detection(self, img1, img2):
        try:
            from skimage.metrics import structural_similarity as ssim
            score = ssim(img1, img2)
            return 1.0 - score
        except Exception:
            return self._pixel_change_detection(img1, img2)
    
    def _contour_based_detection(self, img1, img2):
        if img1 is None or img2 is None: return 1.0
        diff = cv2.absdiff(img1, img2)
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        total_contour_area = sum(cv2.contourArea(contour) for contour in contours)
        total_area = img1.shape[0] * img1.shape[1]
        return total_contour_area / total_area if total_area > 0 else 0
    
    def detect_change(self, img1, img2):
        if img1 is None or img2 is None: return True
        strategies_weights = [0.5, 0.3, 0.2]
        total_change = 0
        for strategy, weight in zip(self.detection_strategies, strategies_weights):
            try:
                change = strategy(img1, img2)
                total_change += change * weight
            except Exception:
                continue
        return total_change > self.change_threshold
    
    def wait_for_stability(self, stability_duration=1.0):
        start_time = time.time()
        last_change_time = start_time
        initial_screen = self.capture_screen()
        if initial_screen is None: return True
        while time.time() - start_time < self.max_wait:
            current_screen = self.capture_screen()
            if current_screen is None:
                time.sleep(self.check_interval)
                continue
            if self.detect_change(initial_screen, current_screen):
                last_change_time = time.time()
                initial_screen = current_screen
            else:
                if time.time() - last_change_time >= stability_duration:
                    logger.debug("✅ Màn hình đã ổn định")
                    return True
            time.sleep(self.check_interval)
        logger.debug("⏰ Timeout chờ ổn định màn hình")
        return False

class IntelligentDemoRecorder:
    """Ghi demo THÔNG MINH với context awareness và double click detection"""
    
    def __init__(self, max_events=5000):
        self.events = []
        self.start_time = None
        self.recording = False
        self.max_events = max_events
        self._keyboard_listener = None
        self._mouse_listener = None
        self.context_stack = []
        self.current_context = "unknown"
        self.last_mouse_pos = None
        self.mouse_move_threshold = 3
        self.record_movements = True  # Mặc định là ghi cả di chuyển
        
        # Double click detection
        self.last_click_time = None
        self.last_click_pos = None
        self.double_click_threshold = 0.7  # 0.7 giây cho double click
        self.position_threshold = 5  # 5 pixel cho vị trí double click
        
    def start(self, initial_context="user_demo", record_movements=True):
        """
        Bắt đầu ghi.
        :param record_movements: Nếu False, sẽ bỏ qua sự kiện di chuyển chuột (chỉ ghi click + phím)
        """
        self.events = []
        self.start_time = time.time()
        self.recording = True
        self.record_movements = record_movements  # Cập nhật cài đặt
        self.current_context = initial_context
        self.last_click_time = None
        self.last_click_pos = None
        
        self._keyboard_listener = keyboard.Listener(on_press=self._on_key_press, on_release=self._on_key_release)
        self._mouse_listener = mouse.Listener(on_move=self._on_move, on_click=self._on_click, on_scroll=self._on_scroll)
        
        self._keyboard_listener.start()
        self._mouse_listener.start()
        
        mode_str = "FULL (Move + Click + Key)" if record_movements else "LITE (Click + Key only)"
        self._record_context_event("start_recording", {"mode": mode_str})
        logger.info(f"🎥 Bắt đầu ghi demo - Context: {initial_context} | Mode: {mode_str}")
    
    def stop(self):
        if not self.recording: return {"events": 0, "duration": 0}
        self.recording = False
        if self._keyboard_listener: self._keyboard_listener.stop()
        if self._mouse_listener: self._mouse_listener.stop()
        duration = time.time() - self.start_time
        self._record_context_event("stop_recording")
        stats = {
            "total_events": len(self.events),
            "duration": duration,
            "context_changes": len([e for e in self.events if e.get("type") == "context"]),
            "clicks": len([e for e in self.events if e.get("type") == "click"]),
            "keys": len([e for e in self.events if e.get("type") == "key_press"])
        }
        logger.info(f"⏹️ Dừng ghi - {stats['total_events']} events trong {duration:.1f}s")
        return stats
    
    def change_context(self, new_context):
        if not self.recording: return
        self.context_stack.append(self.current_context)
        self.current_context = new_context
        self._record_context_event("context_change", {"new_context": new_context})
        logger.debug(f"🔄 Context changed to: {new_context}")
    
    def _record_context_event(self, event_type, extra_data=None):
        event = {"t": self._timestamp(), "type": "context", "context_event": event_type, "current_context": self.current_context}
        if extra_data: event.update(extra_data)
        self.events.append(event)
    
    def _timestamp(self): return time.time() - self.start_time
    
    def _is_double_click(self, x, y, button):
        """Kiểm tra xem có phải double click không"""
        current_time = time.time()
        if self.last_click_time and self.last_click_pos:
            time_diff = current_time - self.last_click_time
            last_x, last_y = self.last_click_pos
            distance = ((x - last_x) ** 2 + (y - last_y) ** 2) ** 0.5
            
            # Nếu thời gian < 0.7s và khoảng cách < 5 pixel và cùng nút chuột
            if (time_diff < self.double_click_threshold and 
                distance < self.position_threshold):
                logger.debug(f"🖱️ Phát hiện double click: {time_diff:.3f}s, khoảng cách: {distance:.1f}px")
                return True
        
        # Cập nhật thông tin click cuối cùng
        self.last_click_time = current_time
        self.last_click_pos = (x, y)
        return False
    
    def _on_move(self, x, y):
        if not self.recording: return
        if not self.record_movements:
            return
        if self.last_mouse_pos:
            last_x, last_y = self.last_mouse_pos
            distance = ((x - last_x) ** 2 + (y - last_y) ** 2) ** 0.5
            if distance < self.mouse_move_threshold: return
        self.last_mouse_pos = (x, y)
        self.events.append({"t": self._timestamp(), "type": "move", "x": x, "y": y})
    
    def _on_click(self, x, y, button, pressed):
        if not self.recording or not pressed: return
        
        button_str = str(button)
        
        # Kiểm tra double click
        if self._is_double_click(x, y, button_str):
            # Tìm sự kiện click trước đó để đánh dấu là double click
            for i in range(len(self.events)-1, -1, -1):
                event = self.events[i]
                if (event.get("type") == "click" and 
                    event.get("button") == button_str and
                    abs(event.get("x", 0) - x) < self.position_threshold and
                    abs(event.get("y", 0) - y) < self.position_threshold):
                    # Đánh dấu sự kiện trước đó là phần đầu của double click
                    event["is_double_click"] = True
                    logger.debug(f"🖱️ Đánh dấu double click tại event {i}")
                    break
            
            # Thêm sự kiện double click
            self.events.append({
                "t": self._timestamp(), 
                "type": "click", 
                "x": x, 
                "y": y, 
                "button": button_str, 
                "context": self.current_context,
                "is_double_click": True
            })
        else:
            # Thêm sự kiện click bình thường
            self.events.append({
                "t": self._timestamp(), 
                "type": "click", 
                "x": x, 
                "y": y, 
                "button": button_str, 
                "context": self.current_context,
                "is_double_click": False
            })
    
    def _on_scroll(self, x, y, dx, dy):
        if not self.recording: return
        self.events.append({"t": self._timestamp(), "type": "scroll", "x": x, "y": y, "dx": dx, "dy": dy})
    
    def _on_key_press(self, key):
        if not self.recording: return
        key_data = self._parse_key(key)
        self.events.append({"t": self._timestamp(), "type": "key_press", "key": key_data, "context": self.current_context})
    
    def _on_key_release(self, key): pass
    
    def _parse_key(self, key):
        try: return key.char
        except AttributeError:
            key_str = str(key)
            special_keys = {"Key.enter": "enter", "Key.tab": "tab", "Key.space": "space", "Key.esc": "esc", "Key.backspace": "backspace", "Key.delete": "delete", "Key.up": "up", "Key.down": "down", "Key.left": "left", "Key.right": "right"}
            return special_keys.get(key_str, key_str.replace("Key.", ""))
    
    def save(self, demo_name, metadata=None):
        if not self.events:
            logger.warning("Không có events để lưu")
            return None
        demo_data = {
            "name": demo_name,
            "events": self.events,
            "metadata": {
                "created_at": time.time(),
                "total_events": len(self.events),
                "duration": self.events[-1]["t"] if self.events else 0,
                "context": self.current_context,
                "screen_size": pyautogui.size(),
                "double_click_threshold": self.double_click_threshold,
                **({"user_metadata": metadata} if metadata else {})
            }
        }
        filename = f"{demo_name}_{int(time.time())}.json"
        filepath = os.path.join(DEMO_DIR, filename)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(demo_data, f, ensure_ascii=False, indent=2)
            logger.info(f"💾 Đã lưu demo: {filename}")
            return filepath
        except Exception as e:
            logger.error(f"Lỗi lưu demo: {e}")
            return None

class AdaptiveDemoPlayer:
    """Phát demo THÍCH ỨNG với smart waiting và error recovery"""
    
    def __init__(self, base_speed=1.0, adaptive_wait=True, verbose=True):
        self.base_speed = base_speed
        self.adaptive_wait = adaptive_wait
        self.verbose = verbose
        
        self.screen_detector = SmartScreenDetector()
        self.execution_stats = {
            'total_played': 0,
            'successful_plays': 0,
            'total_events_processed': 0,
            'total_wait_time': 0,
            'adaptive_waits_used': 0
        }
    
    def play(self, demo_path, speed_multiplier=1.0, context_aware=True):
        """Phát demo với adaptive execution"""
        if not os.path.exists(demo_path):
            logger.error(f"❌ File demo không tồn tại: {demo_path}")
            return False
        
        try:
            with open(demo_path, 'r', encoding='utf-8') as f:
                demo_data = json.load(f)
        except Exception as e:
            logger.error(f"❌ Lỗi đọc file demo: {e}")
            return False
            
        events = demo_data.get('events', [])
        
        if not events:
            logger.warning("⚠️ Demo không có events")
            return False
            
        self.execution_stats['total_played'] += 1
        
        # Tính toán tốc độ chung
        actual_speed = self.base_speed * speed_multiplier
        
        if self.verbose:
            logger.info(f"🎬 Bắt đầu phát demo: {os.path.basename(demo_path)}")
            logger.info(f"   • Tốc độ chung: x{actual_speed:.1f}")
            logger.info(f"   • Tốc độ chuột: x{actual_speed * 7.0:.1f} (đã tăng cường 7x)")
            logger.info(f"   • Adaptive wait: {'BẬT' if self.adaptive_wait else 'TẮT'}")
        
        success = self._execute_events_adaptive(events, actual_speed, context_aware)
        
        if success:
            self.execution_stats['successful_plays'] += 1
            logger.info("✅ Phát demo thành công")
        else:
            logger.error("❌ Phát demo thất bại")
            
        return success
    
    def _execute_events_adaptive(self, events, speed, context_aware):
        """Thực thi events với adaptive timing và xử lý double click"""
        if not events:
            return True
            
        last_timestamp = events[0]["t"]
        current_context = "unknown"
        skip_indices = set()  # Các event cần bỏ qua (phần thứ 2 của double click)
        
        for i, event in enumerate(events):
            if i in skip_indices:
                continue
                
            event_type = event.get("type")
            
            # Tính delay thích ứng
            delay = self._calculate_adaptive_delay(event, last_timestamp, speed, current_context)
            if delay > 0:
                time.sleep(delay)
            
            # Xử lý context
            if context_aware and event_type == "context":
                context_change = event.get("context_event")
                if context_change == "context_change":
                    new_context = event.get("new_context", "unknown")
                    current_context = new_context
                    logger.debug(f"🔄 Chuyển context: {new_context}")
                continue
            
            # Xử lý double click
            if event_type == "click" and event.get("is_double_click"):
                # Tìm phần thứ 2 của double click để bỏ qua
                for j in range(i+1, min(i+3, len(events))):
                    if (events[j].get("type") == "click" and 
                        events[j].get("is_double_click") and
                        abs(events[j].get("x", 0) - event.get("x", 0)) < 5 and
                        abs(events[j].get("y", 0) - event.get("y", 0)) < 5):
                        skip_indices.add(j)
                        break
                
                # Thực hiện double click
                try:
                    if self.verbose: 
                        logger.info(f"🖱️🖱️ [{i+1}/{len(events)}] DOUBLE CLICK tại ({event['x']}, {event['y']})")
                    pyautogui.doubleClick(event["x"], event["y"])
                    success = True
                except Exception as e:
                    logger.error(f"❌ Lỗi double click: {e}")
                    success = False
            else:
                # Thực thi event bình thường
                try:
                    success = self._execute_single_event(event, i, len(events))
                    if not success:
                        logger.warning(f"⚠️ Event {i} thất bại, tiếp tục...")
                except Exception as e:
                    logger.error(f"❌ Lỗi event {i}: {e}")
                    continue
            
            if success:
                last_timestamp = event["t"]
                self.execution_stats['total_events_processed'] += 1
                
                # --- LOGIC XỬ LÝ SMART WAIT ---
                perform_smart_wait = False
                
                # Chỉ xem xét smart wait cho click và key press
                if self.adaptive_wait and event_type in ["click", "key_press"]:
                    perform_smart_wait = True
                    
                    # NÂNG CẤP: Kiểm tra Rapid Click (Double click/Sequence)
                    if event_type == "click" and not event.get("is_double_click"):
                        
                        next_click_event = None
                        next_click_index = -1
                        
                        # 1. Kiểm tra i+1
                        if i + 1 < len(events) and events[i+1].get("type") == "click":
                            next_click_event = events[i+1]
                            next_click_index = i + 1
                        # 2. Kiểm tra i+2 (chỉ khi i+1 là move/scroll/context)
                        elif i + 2 < len(events):
                            event_i_plus_1 = events[i+1]
                            event_i_plus_2 = events[i+2]
                            
                            # Chỉ cho phép move, scroll, hoặc context event ở giữa
                            if event_i_plus_1.get("type") in ["move", "scroll", "context"] and event_i_plus_2.get("type") == "click":
                                next_click_event = event_i_plus_2
                                next_click_index = i + 2

                        if next_click_event:
                            # Tính khoảng cách thời gian giữa 2 click dựa trên dữ liệu ghi (recording time)
                            time_diff = next_click_event["t"] - event["t"]
                            RAPID_CLICK_THRESHOLD = 0.7
                            if time_diff < RAPID_CLICK_THRESHOLD:
                                perform_smart_wait = False
                                logger.debug(f"⚡ Phát hiện Rapid Click (Event {next_click_index}) ({time_diff:.3f}s) - Bỏ qua Smart Wait")
                                
                if perform_smart_wait:
                    wait_start = time.time()
                    self.screen_detector.wait_for_stability()
                    wait_time = time.time() - wait_start
                    self.execution_stats['total_wait_time'] += wait_time
                    self.execution_stats['adaptive_waits_used'] += 1
        
        return True
    
    def _calculate_adaptive_delay(self, event, last_timestamp, speed, context):
        """Tính delay thích ứng"""
        base_delay = (event["t"] - last_timestamp) / speed
        
        event_type = event.get("type")
        
        # NÂNG CẤP: Tăng tốc độ chuột move lên 7 lần
        if event_type == "move":
            base_delay = base_delay / 7.0  # Chia delay cho 7 để di chuyển nhanh gấp 7 lần
        
        # Giảm delay cho rapid sequences khác (scroll)
        elif event_type == "scroll":
            base_delay = max(0.01, base_delay * 0.5)
            
        # Tăng delay cho context changes
        if event.get("context") != context and event_type in ["click", "key_press"]:
            base_delay = max(base_delay, 0.5)
            
        return base_delay
    
    def _execute_single_event(self, event, index, total_events):
        event_type = event.get("type")
        try:
            if event_type == "move":
                pyautogui.moveTo(event["x"], event["y"])
            elif event_type == "click":
                if self.verbose: 
                    if event.get("is_double_click"):
                        logger.info(f"🖱️🖱️ [{index+1}/{total_events}] DOUBLE CLICK tại ({event['x']}, {event['y']})")
                    else:
                        logger.info(f"👆 [{index+1}/{total_events}] CLICK tại ({event['x']}, {event['y']})")
                pyautogui.click(event["x"], event["y"])
            elif event_type == "scroll":
                pyautogui.scroll(event["dy"] * 10)
            elif event_type == "key_press":
                key = event["key"]
                if self.verbose and len(key) == 1: logger.info(f"⌨️ [{index+1}/{total_events}] KEY: '{key}'")
                special_keys = {"enter": lambda: pyautogui.press("enter"), "tab": lambda: pyautogui.press("tab"), "space": lambda: pyautogui.press("space"), "esc": lambda: pyautogui.press("esc"), "backspace": lambda: pyautogui.press("backspace"), "delete": lambda: pyautogui.press("delete")}
                if key in special_keys: special_keys[key]()
                else: pyautogui.write(key, interval=0.02)
            return True
        except Exception as e:
            logger.error(f"❌ Lỗi thực thi event {event_type}: {e}")
            return False
    
    def get_stats(self):
        success_rate = (self.execution_stats['successful_plays'] / self.execution_stats['total_played'] * 100) if self.execution_stats['total_played'] > 0 else 0
        return {**self.execution_stats, 'success_rate': success_rate, 'average_wait_time': (self.execution_stats['total_wait_time'] / self.execution_stats['adaptive_waits_used'] if self.execution_stats['adaptive_waits_used'] > 0 else 0)}

# ... (Utility functions, aliases, main) ...
def list_demos(): return [f for f in os.listdir(DEMO_DIR) if f.endswith('.json')]

def load_demo(demo_name):
    if not demo_name.endswith('.json'): demo_name += '.json'
    filepath = os.path.join(DEMO_DIR, demo_name)
    if not os.path.exists(filepath): return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f: return json.load(f)
    except Exception: return None

def get_demo_info(demo_path):
    demo_data = load_demo(demo_path)
    if not demo_data: return None
    events = demo_data.get('events', [])
    metadata = demo_data.get('metadata', {})
    double_clicks = len([e for e in events if e.get('is_double_click')])
    return {'name': demo_data.get('name', 'unknown'), 'total_events': len(events), 'duration': metadata.get('duration', 0), 'created_at': metadata.get('created_at', 0), 'clicks': len([e for e in events if e.get('type') == 'click']), 'key_presses': len([e for e in events if e.get('type') == 'key_press']), 'double_clicks': double_clicks}

DemoRecorder = IntelligentDemoRecorder
DemoPlayer = AdaptiveDemoPlayer
ScreenChangeDetector = SmartScreenDetector

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("🧪 Testing Enhanced AI Actuator...")
    detector = SmartScreenDetector()
    print("📸 Testing screen capture...")
    screen = detector.capture_screen()
    if screen is not None: print(f"   Screen captured: {screen.shape}")
    demos = list_demos()
    print(f"📁 Found {len(demos)} demos")
    if demos:
        demo_info = get_demo_info(demos[0])
        print(f"📊 Demo info: {demo_info}")
    logger.info("✅ Enhanced AI Actuator test completed!")