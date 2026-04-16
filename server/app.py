import os
import json
import time
import shutil
import threading
import traceback
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

import sys

app = Flask(__name__)
CORS(app)

# In-memory heartbeat store: { "hostname/username": { hostname, username, last_seen, ip } }
client_heartbeats = {}
# Pending commands: { "hostname/username": "uninstall" }
pending_commands = {}

if getattr(sys, 'frozen', False):
    base_dir = os.path.dirname(sys.executable)   # config.json lives next to exe
    STATIC_DIR = os.path.join(sys._MEIPASS, 'static')  # static embedded in exe
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    STATIC_DIR = os.path.join(base_dir, 'static')

CONFIG_FILE = os.path.join(base_dir, 'config.json')

def load_config():
    default = {
        "storage_path": "C:\\ScreenData",
        "auto_delete_enabled": False,
        "auto_delete_days": 30,
        "client_config": {
            "recording_active": True,
            "screenshot_interval_seconds": 5,
            "quality": 80
        }
    }
    if not os.path.exists(CONFIG_FILE):
        return default
    with open(CONFIG_FILE, 'r') as f:
        data = json.load(f)
    # Ensure client_config key always exists
    if 'client_config' not in data:
        data['client_config'] = default['client_config']
        # migrate old flat keys if present
        if 'active' in data:
            data['client_config']['recording_active'] = data.pop('active')
        if 'interval' in data:
            data['client_config']['screenshot_interval_seconds'] = data.pop('interval')
    return data

# ===== Auto-delete state =====
last_cleanup_result = {"deleted": 0, "freed_mb": 0, "at": None}

def run_cleanup():
    """ลบไฟล์ที่เก่ากว่า auto_delete_days วัน"""
    global last_cleanup_result
    config = load_config()
    if not config.get("auto_delete_enabled", False):
        return {"deleted": 0, "freed_mb": 0}

    days = int(config.get("auto_delete_days", 30))
    storage_base = config.get("storage_path", "uploads")
    if not os.path.exists(storage_base):
        storage_base = "uploads"
    if not os.path.exists(storage_base):
        return {"deleted": 0, "freed_mb": 0}

    cutoff = time.time() - (days * 86400)
    deleted = 0
    freed = 0
    for root, dirs, files in os.walk(storage_base):
        for file in files:
            if file.lower().endswith(('.jpg', '.jpeg', '.png')):
                fp = os.path.join(root, file)
                if os.path.getmtime(fp) < cutoff:
                    freed += os.path.getsize(fp)
                    os.remove(fp)
                    deleted += 1

    freed_mb = round(freed / 1024 / 1024, 1)
    last_cleanup_result = {
        "deleted": deleted,
        "freed_mb": freed_mb,
        "at": datetime.now().strftime("%d/%m/%Y %H:%M")
    }
    return last_cleanup_result

def auto_cleanup_loop():
    """Background thread: รัน cleanup ทุก 1 ชั่วโมง"""
    while True:
        time.sleep(3600)
        run_cleanup()

# เริ่ม background thread
_cleanup_thread = threading.Thread(target=auto_cleanup_loop, daemon=True)
_cleanup_thread.start()

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

@app.route('/api/config', methods=['GET'])
def get_config():
    config = load_config()
    client_config = config.get('client_config', {})
    client_config['storage_path']       = config.get('storage_path', '')
    client_config['auto_delete_enabled'] = config.get('auto_delete_enabled', False)
    client_config['auto_delete_days']    = config.get('auto_delete_days', 30)
    return jsonify(client_config)

@app.route('/api/config', methods=['POST'])
def update_config():
    data = request.json
    config = load_config()

    if 'storage_path' in data:
        config['storage_path'] = data.pop('storage_path')
    if 'auto_delete_enabled' in data:
        config['auto_delete_enabled'] = data.pop('auto_delete_enabled')
    if 'auto_delete_days' in data:
        config['auto_delete_days'] = int(data.pop('auto_delete_days'))

    config['client_config'].update(data)
    save_config(config)

    response_data = config['client_config'].copy()
    response_data['storage_path']       = config['storage_path']
    response_data['auto_delete_enabled'] = config.get('auto_delete_enabled', False)
    response_data['auto_delete_days']    = config.get('auto_delete_days', 30)
    return jsonify({"status": "success", "config": response_data})

@app.route('/api/cleanup', methods=['POST'])
def manual_cleanup():
    result = run_cleanup()
    return jsonify(result)

@app.route('/api/cleanup/status', methods=['GET'])
def cleanup_status():
    return jsonify(last_cleanup_result)

@app.route('/api/upload', methods=['POST'])
def upload_image():
    if 'image' not in request.files:
        return jsonify({"error": "No image file provided"}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({"error": "Empty filename"}), 400

    username = request.form.get("username", "unknown")
    hostname = request.form.get("hostname", "unknown")

    config = load_config()
    storage_base = config.get("storage_path", "uploads")
    
    target_dir = os.path.join(storage_base, hostname, username)
    try:
        os.makedirs(target_dir, exist_ok=True)
    except Exception as e:
        print(f"Failed to create directory {target_dir}: {e}")
        target_dir = os.path.join("uploads", hostname, username)
        os.makedirs(target_dir, exist_ok=True)

    filename = secure_filename(file.filename)
    if not filename:
        filename = f"capture_{int(time.time())}.jpg"
        
    save_path = os.path.join(target_dir, filename)
    file.save(save_path)
    
    return jsonify({"status": "success", "path": save_path})

@app.route('/api/images', methods=['GET'])
def list_images():
    config = load_config()
    storage_base = config.get("storage_path", "uploads")

    if not os.path.exists(storage_base):
        storage_base = "uploads"
        if not os.path.exists(storage_base):
            return jsonify([])

    # Query params
    hostname_filter = request.args.get('hostname', '')
    username_filter = request.args.get('username', '')
    date_from_str   = request.args.get('date_from', '')  # YYYY-MM-DD
    date_to_str     = request.args.get('date_to', '')    # YYYY-MM-DD
    time_from_str   = request.args.get('time_from', '')  # HH:MM
    time_to_str     = request.args.get('time_to', '')    # HH:MM

    # ถ้าระบุ hostname/username → scan เฉพาะโฟลเดอร์นั้น ไม่จำกัดจำนวน
    # ถ้าไม่ระบุ → scan ทั้งหมด จำกัดแค่ 500 (สำหรับหน้า dashboard)
    if hostname_filter and username_filter:
        scan_base   = os.path.join(storage_base, hostname_filter, username_filter)
        max_scanned = None
    else:
        scan_base   = storage_base
        max_scanned = 500

    # แปลงวันที่เป็น timestamp
    ts_from = ts_to = None
    if date_from_str:
        try:
            ts_from = datetime.strptime(date_from_str, '%Y-%m-%d').timestamp()
        except:
            pass
    if date_to_str:
        try:
            dt_to = datetime.strptime(date_to_str, '%Y-%m-%d')
            ts_to = datetime(dt_to.year, dt_to.month, dt_to.day, 23, 59, 59).timestamp()
        except:
            pass

    # แปลงเวลาเป็น นาที (HH:MM → int)
    t_from_min = t_to_min = None
    if time_from_str:
        try:
            h, m = time_from_str.split(':')
            t_from_min = int(h) * 60 + int(m)
        except:
            pass
    if time_to_str:
        try:
            h, m = time_to_str.split(':')
            t_to_min = int(h) * 60 + int(m)
        except:
            pass

    all_files = []
    if os.path.exists(scan_base):
        for root, dirs, files in os.walk(scan_base):
            for file in files:
                if file.lower().endswith(('.jpg', '.jpeg', '.png')):
                    all_files.append(os.path.join(root, file))

    all_files.sort(key=os.path.getmtime, reverse=True)
    if max_scanned:
        all_files = all_files[:max_scanned]

    images = []
    for full_path in all_files:
        mtime = os.path.getmtime(full_path)
        if ts_from and mtime < ts_from:
            continue
        if ts_to and mtime > ts_to:
            continue
        if t_from_min is not None or t_to_min is not None:
            dt = datetime.fromtimestamp(mtime)
            file_min = dt.hour * 60 + dt.minute
            if t_from_min is not None and file_min < t_from_min:
                continue
            if t_to_min is not None and file_min > t_to_min:
                continue

        rel_path = os.path.relpath(full_path, storage_base)
        parts    = rel_path.split(os.sep)
        hostname = parts[0] if len(parts) >= 3 else "unknown"
        username = parts[1] if len(parts) >= 3 else "unknown"

        images.append({
            "filename": os.path.basename(full_path),
            "hostname": hostname,
            "username": username,
            "size":     os.path.getsize(full_path),
            "modified": mtime,
            "path":     rel_path.replace(os.sep, '/')
        })

    return jsonify(images)

@app.route('/api/images/view/<path:filepath>')
def serve_image(filepath):
    config = load_config()
    storage_base = config.get("storage_path", "uploads")
    filepath = filepath.replace('/', os.sep)
    
    full_path = os.path.join(storage_base, filepath)
    if not os.path.exists(full_path):
        storage_base = "uploads"
        
    directory = os.path.dirname(os.path.join(storage_base, filepath))
    filename = os.path.basename(filepath)
    return send_from_directory(directory, filename)

@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    data = request.json or {}
    hostname = data.get('hostname', 'unknown')
    username = data.get('username', 'unknown')
    key = f"{hostname}/{username}"
    client_heartbeats[key] = {
        'hostname': hostname,
        'username': username,
        'last_seen': time.time(),
        'ip': request.remote_addr
    }
    # Return pending command if any, then clear it
    command = pending_commands.pop(key, None)
    return jsonify({"status": "ok", "command": command})

@app.route('/api/clients', methods=['GET'])
def get_clients():
    now = time.time()
    offline_threshold = 120  # 2 minutes
    clients = []
    for key, info in client_heartbeats.items():
        is_online = (now - info['last_seen']) < offline_threshold
        clients.append({
            'hostname': info['hostname'],
            'username': info['username'],
            'ip': info['ip'],
            'last_seen': info['last_seen'],
            'online': is_online
        })
    clients.sort(key=lambda c: (not c['online'], c['hostname']))
    return jsonify(clients)

@app.route('/api/clients/<path:key>', methods=['DELETE'])
def delete_client(key):
    client_heartbeats.pop(key, None)
    pending_commands.pop(key, None)
    return jsonify({"status": "ok"})

@app.route('/api/clients/<path:key>/uninstall', methods=['POST'])
def uninstall_client(key):
    if key not in client_heartbeats:
        return jsonify({"error": "client not found"}), 404
    pending_commands[key] = "uninstall"
    return jsonify({"status": "ok", "message": f"Uninstall command queued for {key}"})

@app.route('/api/computers', methods=['GET'])
def get_computers():
    """Return all hostname/username combos with their latest image — no limit"""
    config = load_config()
    storage_path = config.get('storage_path', 'uploads')
    result = []
    try:
        if not os.path.exists(storage_path):
            return jsonify([])
        for hostname in sorted(os.listdir(storage_path)):
            host_dir = os.path.join(storage_path, hostname)
            if not os.path.isdir(host_dir):
                continue
            try:
                username_list = sorted(os.listdir(host_dir))
            except PermissionError:
                continue
            for username in username_list:
                user_dir = os.path.join(host_dir, username)
                if not os.path.isdir(user_dir):
                    continue
                try:
                    images = sorted(
                        e.name for e in os.scandir(user_dir)
                        if e.name.lower().endswith(('.png', '.jpg', '.jpeg'))
                    )
                except Exception:
                    images = []
                total = len(images)
                if images:
                    latest_file = images[-1]
                    latest_time = os.path.getmtime(os.path.join(user_dir, latest_file))
                    result.append({
                        'hostname': hostname,
                        'username': username,
                        'latest_url': f'/api/images/view/{hostname}/{username}/{latest_file}',
                        'latest_time': latest_time,
                        'total': total
                    })
        result.sort(key=lambda x: x['latest_time'], reverse=True)
    except Exception as e:
        print(f"[ERROR] /api/computers: {e}\n{traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500
    return jsonify(result)

@app.route('/api/latest', methods=['GET'])
def get_latest():
    """Return the most recent image for each hostname/username (for Live View)"""
    try:
        config = load_config()
    except Exception as e:
        print(f"[ERROR] get_latest load_config: {e}\n{traceback.format_exc()}")
        return jsonify({'error': 'load_config failed: ' + str(e)}), 500
    storage_path = config.get('storage_path', 'uploads')
    result = []
    try:
        if not os.path.exists(storage_path):
            print(f"[WARN] /api/latest: storage_path does not exist: {storage_path}")
            return jsonify([])
        for hostname in os.listdir(storage_path):
            host_dir = os.path.join(storage_path, hostname)
            if not os.path.isdir(host_dir):
                continue
            try:
                usernames = os.listdir(host_dir)
            except PermissionError:
                continue  # skip protected folders e.g. "System Volume Information"
            for username in usernames:
                user_dir = os.path.join(host_dir, username)
                if not os.path.isdir(user_dir):
                    continue
                try:
                    images = sorted(
                        e.name for e in os.scandir(user_dir)
                        if e.name.lower().endswith(('.png', '.jpg', '.jpeg'))
                    )
                except Exception:
                    images = []
                if not images:
                    continue
                latest_file = images[-1]
                mtime = os.path.getmtime(os.path.join(user_dir, latest_file))
                # No cutoff — return latest image regardless of age
                # Online/offline status is determined by heartbeat in /api/clients
                result.append({
                    'hostname': hostname,
                    'username': username,
                    'url': f'/api/images/view/{hostname}/{username}/{latest_file}',
                    'time': mtime
                })
        result.sort(key=lambda x: x['hostname'])
    except Exception as e:
        print(f"[ERROR] /api/latest: {e}\n{traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500
    return jsonify(result)

def _resolve_disk_path(storage_path):
    # แปลง path ให้เป็น root drive เช่น C:\DATA -> C:\
    if not storage_path:
        return 'C:\\'
    if storage_path.startswith('\\\\') or storage_path.startswith('//'):
        return storage_path
    drive = os.path.splitdrive(storage_path)[0]
    if drive:
        return drive + '\\'
    return storage_path

# Cache disk space ไว้ใน memory อัปเดตทุก 60 วินาที
_disk_cache = {'data': None, 'ts': 0}

def _refresh_disk_cache():
    while True:
        time.sleep(60)
        _update_disk_cache()

def _update_disk_cache():
    config = load_config()
    storage_path = config.get('storage_path', 'C:\\')
    check_path = _resolve_disk_path(storage_path)
    result = [None]
    t = threading.Thread(target=lambda: result.__setitem__(0, shutil.disk_usage(check_path)))
    t.daemon = True
    t.start()
    t.join(timeout=3)
    usage = result[0]
    if usage is None:
        try:
            usage = shutil.disk_usage('C:\\')
            check_path = 'C:\\'
        except:
            return
    _disk_cache['data'] = {
        'total': usage.total,
        'used': usage.used,
        'free': usage.free,
        'percent_used': round((usage.used / usage.total) * 100, 1),
        'path': check_path
    }
    _disk_cache['ts'] = time.time()

# อัปเดต cache ตอนเริ่มต้น (background)
threading.Thread(target=_update_disk_cache, daemon=True).start()
# อัปเดตซ้ำทุก 60 วินาที
threading.Thread(target=_refresh_disk_cache, daemon=True).start()

@app.route('/api/disk-space', methods=['GET'])
def disk_space():
    if _disk_cache['data']:
        return jsonify(_disk_cache['data'])
    # ยังไม่มีข้อมูล (กำลังโหลดครั้งแรก) — ตอบทันทีด้วย C: drive
    try:
        usage = shutil.disk_usage('C:\\')
        return jsonify({
            'total': usage.total, 'used': usage.used, 'free': usage.free,
            'percent_used': round((usage.used / usage.total) * 100, 1),
            'path': 'C:\\'
        })
    except:
        return jsonify({'error': 'loading'}), 503

@app.route('/')
def index():
    return send_from_directory(STATIC_DIR, 'index.html')

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory(STATIC_DIR, filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
