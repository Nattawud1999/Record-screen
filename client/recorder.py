import os
import time
import socket
import getpass
import threading
import requests
import cv2
import numpy as np
import mss
import sys
import ctypes

def self_register():
    """ลงทะเบียนตัวเองใน Registry ของ User ปัจจุบัน (HKCU) เพื่อรันอัตโนมัติทุกครั้งที่ Login"""
    try:
        import winreg
        recorder_path = r"C:\ProgramData\ScreenMonitor\recorder.exe"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "ScreenMonitor", 0, winreg.REG_SZ, f'"{recorder_path}"')
        winreg.CloseKey(key)
    except Exception as e:
        print(f"Self-register failed: {e}")

def ensure_single_instance():
    """ถ้ามี instance ของ User นี้รันอยู่แล้ว ให้ออกทันที"""
    mutex_name = f"Global\\ScreenMonitor_{getpass.getuser()}"
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        sys.exit(0)  # มีตัวเองรันอยู่แล้ว ออกเลย

def load_local_config():
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
    local_config_path = os.path.join(base_dir, 'config.json')
    try:
        with open(local_config_path, 'r') as f:
            import json
            return json.load(f)
    except:
        return {"backend_url": "http://localhost:5000"}

def get_config(backend_url):
    try:
        res = requests.get(f"{backend_url}/api/config", timeout=5)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"Failed to fetch config: {e}")
    
    return {
        "recording_active": True,
        "screenshot_interval_seconds": 20
    }

def is_black_screen(frame, threshold=8):
    """ตรวจว่าภาพเป็นหน้าจอดำ (ล็อกหน้าจอ / Switch User)
    threshold: ค่าเฉลี่ย brightness 0-255 ถ้าต่ำกว่านี้ถือว่าดำ"""
    return np.mean(frame) < threshold

def capture_screenshot(quality=80):
    timestamp = int(time.time())
    filename = f"capture_{timestamp}.jpg"
    filepath = os.path.join(os.environ.get("TEMP", "."), filename)

    with mss.mss() as sct:
        monitor = sct.monitors[0] # All monitors combined (virtual screen)
        img = sct.grab(monitor)

        # Convert to numpy array (mss provides BGRA format natively)
        frame = np.array(img)
        # Drop alpha channel (keep BGR, which cv2 natively expects!)
        frame = frame[:, :, :3]

        # ถ้าภาพดำ (ล็อกหน้าจอ/Switch User) → ไม่บันทึก
        if is_black_screen(frame):
            return None

        # Save as JPEG with specific quality
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        cv2.imwrite(filepath, frame, encode_param)

        return filepath

def upload_image(filepath, backend_url):
    try:
        hostname = socket.gethostname()
        username = getpass.getuser()
        with open(filepath, 'rb') as f:
            files = {'image': f}
            data = {'hostname': hostname, 'username': username}
            res = requests.post(f"{backend_url}/api/upload", files=files, data=data)
            if res.status_code == 200:
                 print(f"Upload successful: {filepath}")
                 os.remove(filepath)
            else:
                 print(f"Upload failed: {res.text}")
    except Exception as e:
        print(f"Error uploading image: {e}")
        # Delete if failed so temp directory doesn't fill up permanently
        if os.path.exists(filepath):
             try:
                 os.remove(filepath)
             except:
                 pass

def self_uninstall():
    import subprocess
    bin_dir = r'C:\ProgramData\ScreenMonitor'

    bat_content = f"""@echo off
timeout /t 2 /nobreak >nul
taskkill /F /IM recorder.exe >nul 2>&1
reg delete "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run" /v "ScreenMonitor" /f >nul 2>&1
if exist "{bin_dir}" rmdir /s /q "{bin_dir}"
del "%~f0"
"""
    bat_path = os.path.join(os.environ.get('TEMP', '.'), 'uninstall_recorder.bat')
    with open(bat_path, 'w') as f:
        f.write(bat_content)

    subprocess.Popen(['cmd', '/c', bat_path], creationflags=subprocess.CREATE_NO_WINDOW)
    sys.exit(0)

def send_heartbeat(backend_url):
    try:
        hostname = socket.gethostname()
        username = getpass.getuser()
        res = requests.post(f"{backend_url}/api/heartbeat",
                            json={"hostname": hostname, "username": username},
                            timeout=5)
        if res.status_code == 200:
            command = res.json().get("command")
            if command == "uninstall":
                print("Received uninstall command. Uninstalling...")
                self_uninstall()
    except Exception as e:
        print(f"Heartbeat failed: {e}")

def main():
    ensure_single_instance()  # ออกถ้ามี instance รันอยู่แล้ว
    self_register()           # ลงทะเบียนใน HKCU ของ User นี้
    local_conf = load_local_config()
    backend_url = local_conf.get("backend_url", "http://localhost:5000")

    # Cache config — fetch only every 60 seconds to reduce server load
    cached_config = {}
    last_config_fetch = 0
    CONFIG_CACHE_TTL = 60  # seconds

    while True:
        # Send heartbeat every cycle
        threading.Thread(target=send_heartbeat, args=(backend_url,), daemon=True).start()

        # Refresh config only when cache expires
        now = time.time()
        if now - last_config_fetch >= CONFIG_CACHE_TTL:
            fetched = get_config(backend_url)
            if fetched:
                cached_config = fetched
                last_config_fetch = now

        config = cached_config
        if not config.get('recording_active', True):
            print("Recording is paused by backend configuration. Sleeping...")
            time.sleep(10)
            continue

        interval = config.get('screenshot_interval_seconds', 20)
        quality = config.get('quality', 80)

        filepath = capture_screenshot(quality)

        # ถ้า capture_screenshot คืน None = หน้าจอดำ (ล็อก/Switch User) → ข้ามไป
        if filepath is None:
            print("Black screen detected (locked/switched user), skipping upload.")
            time.sleep(interval)
            continue

        # Upload in background thread so sleep timing is consistent
        threading.Thread(target=upload_image, args=(filepath, backend_url), daemon=True).start()

        time.sleep(interval)

if __name__ == "__main__":
    main()
