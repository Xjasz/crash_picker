import ctypes
import ctypes.wintypes as wintypes
import logging
import random
import time

import numpy as np
import pyautogui
import pytesseract
from PIL import Image, ImageFilter, ImageGrab, ImageOps

logger = logging.getLogger('crash_picker')
user32, gdi32, kernel32 = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.kernel32
RED_RGB = (202, 13, 61)
GREEN_RGB = (45, 224, 28)
WHITE_RGB = (255, 255, 255)
BET_LIVE_RGB = (20, 117, 225)
COLOR_TOLERANCE = 60
move_mouse_back = True
last_logged = {}

class RECT(ctypes.Structure):
    _fields_ = [('left', wintypes.LONG), ('top', wintypes.LONG), ('right', wintypes.LONG), ('bottom', wintypes.LONG)]

class MONITORINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', RECT), ('rcWork', RECT), ('dwFlags', wintypes.DWORD)]

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.UINT), ('dwTime', wintypes.DWORD)]

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD),
                ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD), ('biSizeImage', wintypes.DWORD),
                ('biXPelsPerMeter', wintypes.LONG), ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD),
                ('biClrImportant', wintypes.DWORD)]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [('bmiHeader', BITMAPINFOHEADER), ('bmiColors', wintypes.DWORD * 3)]

def wait_for_idle(seconds, cap):
    info = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
    deadline = time.monotonic() + cap
    while time.monotonic() < deadline:
        user32.GetLastInputInfo(ctypes.byref(info))
        idle = ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000
        if idle >= seconds:
            return
        time.sleep(min(seconds - idle, deadline - time.monotonic()))

def click_button(button, text='', triple_click=False):
    try:
        orig_x, orig_y = pyautogui.position()
        click_x = button['x'] + button['width'] // 4 + random.randint(0, button['width'] // 2)
        click_y = button['y'] + button['height'] // 4 + random.randint(0, button['height'] // 2)
        pyautogui.moveTo(click_x, click_y, duration=0.02)
        click_ts = time.monotonic()
        pyautogui.click()
        time.sleep(0.02)
        if triple_click:
            pyautogui.click()
            time.sleep(0.04)
            pyautogui.click()
            time.sleep(0.04)
        if text:
            pyautogui.write(text, interval=0.01)
        if move_mouse_back:
            pyautogui.moveTo(orig_x, orig_y)
        time.sleep(0.01)
        return click_ts
    except Exception:
        logger.exception('Input action failed for %s', button['name'])
        return None

def click_fast(button):
    try:
        orig_x, orig_y = pyautogui.position()
        click_ts = time.monotonic()
        pyautogui.click(button['x'] + button['width'] // 4 + random.randint(0, button['width'] // 2), button['y'] + button['height'] // 4 + random.randint(0, button['height'] // 2), _pause=False)
        if move_mouse_back:
            pyautogui.moveTo(orig_x, orig_y, _pause=False)
        return click_ts
    except Exception:
        logger.exception('Cashout click failed')
        return None

def capture_region(button):
    x, y, width, height = (button[key] for key in ('x', 'y', 'width', 'height'))
    return ImageGrab.grab(bbox=(x, y, x + width, y + height), all_screens=True)

def capture_rgb_fast(button):
    x, y, width, height = (button[key] for key in ('x', 'y', 'width', 'height'))
    screen_dc = user32.GetDC(0)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth, info.bmiHeader.biHeight = width, -height
    info.bmiHeader.biPlanes, info.bmiHeader.biBitCount = 1, 32
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(screen_dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
    try:
        previous = gdi32.SelectObject(memory_dc, bitmap)
        ok = gdi32.BitBlt(memory_dc, 0, 0, width, height, screen_dc, x, y, 0x00CC0020)
        buffer = ctypes.string_at(bits, width * height * 4)
        gdi32.SelectObject(memory_dc, previous)
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(0, screen_dc)
    if not ok:
        raise OSError('BitBlt failed')
    return np.frombuffer(buffer, np.uint8).reshape(-1, 4)[:, 2::-1].tobytes()

def has_color(rgb_bytes, rgb):
    return bool((np.abs(np.frombuffer(rgb_bytes, np.uint8).reshape(-1, 3).astype(np.int16) - rgb) <= COLOR_TOLERANCE).all(1).any())

def classify_colors(rgb_bytes):
    return has_color(rgb_bytes, GREEN_RGB), has_color(rgb_bytes, RED_RGB)

def ocr_text(name, img, budget, whitelist, white_floor=None):
    config = f'--psm 7 -c tessedit_char_whitelist={whitelist}'
    gray = ImageOps.grayscale(img)
    if white_floor:
        thinned = gray.point(lambda v: 0 if v >= white_floor else 255).filter(ImageFilter.MaxFilter(5))
        prepared = thinned.resize((img.width * 2, img.height * 2), Image.Resampling.LANCZOS)
    else:
        prepared = gray.resize((img.width * 3, img.height * 3), Image.Resampling.NEAREST)
    try:
        text = pytesseract.image_to_string(prepared, config=config, timeout=budget).strip()
    except Exception as exc:
        logger.warning('OCR %s failed: %s', name, exc)
        return None
    if last_logged.get(name) != text:
        last_logged[name] = text
        logger.debug('OCR %s %r', name, text)
    return text

def monitor_region(x, y):
    monitor = user32.MonitorFromPoint(wintypes.POINT(x, y), 2)
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(monitor, ctypes.byref(info))
    rect = info.rcMonitor
    return {'x': rect.left, 'y': rect.top, 'width': rect.right - rect.left, 'height': rect.bottom - rect.top}
