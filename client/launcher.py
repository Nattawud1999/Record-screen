"""
ScreenMonitor Launcher
- รันเป็น SYSTEM ผ่าน Task Scheduler ทุก 60 วินาที
- ตรวจสอบทุก Windows session ที่ active
- Launch recorder.exe เข้าไปใน session ของแต่ละ User โดยตรง
- recorder.exe มี mutex → ไม่รันซ้ำถ้ามีอยู่แล้ว
"""

import ctypes
import ctypes.wintypes as wt
import os
from datetime import datetime

# ──────────────────────────────────────────
RECORDER_PATH = r"C:\ProgramData\ScreenMonitor\recorder.exe"
LOG_PATH      = r"C:\ProgramData\ScreenMonitor\launcher.log"
# ──────────────────────────────────────────

# Constants
WTS_CURRENT_SERVER         = None
WTSActive                  = 0
MAXIMUM_ALLOWED            = 0x02000000
SecurityImpersonation      = 2
TokenPrimary               = 1
CREATE_NO_WINDOW           = 0x08000000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
STARTF_USESHOWWINDOW       = 0x00000001
SW_HIDE                    = 0


# ──── Structures ────
class WTS_SESSION_INFOW(ctypes.Structure):
    _fields_ = [
        ("SessionId",       wt.DWORD),
        ("pWinStationName", wt.LPWSTR),
        ("State",           ctypes.c_int),
    ]

class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb",              wt.DWORD),
        ("lpReserved",      wt.LPWSTR),
        ("lpDesktop",       wt.LPWSTR),
        ("lpTitle",         wt.LPWSTR),
        ("dwX",             wt.DWORD),  ("dwY",           wt.DWORD),
        ("dwXSize",         wt.DWORD),  ("dwYSize",        wt.DWORD),
        ("dwXCountChars",   wt.DWORD),  ("dwYCountChars",  wt.DWORD),
        ("dwFillAttribute", wt.DWORD),
        ("dwFlags",         wt.DWORD),
        ("wShowWindow",     wt.WORD),
        ("cbReserved2",     wt.WORD),
        ("lpReserved2",     ctypes.c_char_p),
        ("hStdInput",       wt.HANDLE),
        ("hStdOutput",      wt.HANDLE),
        ("hStdError",       wt.HANDLE),
    ]

class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess",    wt.HANDLE),
        ("hThread",     wt.HANDLE),
        ("dwProcessId", wt.DWORD),
        ("dwThreadId",  wt.DWORD),
    ]


# ──── DLLs ────
wtsapi32 = ctypes.WinDLL("wtsapi32.dll")
advapi32 = ctypes.WinDLL("advapi32.dll")
kernel32 = ctypes.WinDLL("kernel32.dll")
userenv  = ctypes.WinDLL("userenv.dll")


# ──── Logging ────
def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:
        pass


# ──── Get all active session IDs ────
def get_active_session_ids():
    ids = []
    pInfo  = ctypes.POINTER(WTS_SESSION_INFOW)()
    count  = wt.DWORD(0)

    ok = wtsapi32.WTSEnumerateSessionsW(
        WTS_CURRENT_SERVER, 0, 1,
        ctypes.byref(pInfo), ctypes.byref(count)
    )
    if not ok:
        log(f"WTSEnumerateSessions FAILED: err={kernel32.GetLastError()}")
        return ids

    for i in range(count.value):
        s = pInfo[i]
        # WTSActive=0, skip session 0 (SYSTEM session)
        if s.State == WTSActive and s.SessionId != 0:
            ids.append(s.SessionId)

    wtsapi32.WTSFreeMemory(pInfo)
    return ids


# ──── Launch recorder.exe inside a specific user session ────
def launch_in_session(session_id):
    user_token = wt.HANDLE(0)
    dup_token  = wt.HANDLE(0)
    env_block  = ctypes.c_void_p(0)

    try:
        # 1. Get the user token for this session (requires SYSTEM privilege)
        if not wtsapi32.WTSQueryUserToken(session_id, ctypes.byref(user_token)):
            log(f"  session {session_id}: WTSQueryUserToken FAILED err={kernel32.GetLastError()}")
            return

        # 2. Duplicate as primary token so we can CreateProcessAsUser
        if not advapi32.DuplicateTokenEx(
            user_token, MAXIMUM_ALLOWED, None,
            SecurityImpersonation, TokenPrimary,
            ctypes.byref(dup_token)
        ):
            log(f"  session {session_id}: DuplicateTokenEx FAILED err={kernel32.GetLastError()}")
            return

        # 3. Build correct environment block for this user (%TEMP%, %APPDATA% etc.)
        userenv.CreateEnvironmentBlock(ctypes.byref(env_block), dup_token, False)

        # 4. STARTUPINFO — run hidden on the user's interactive desktop
        si = STARTUPINFOW()
        si.cb          = ctypes.sizeof(STARTUPINFOW)
        si.lpDesktop   = "winsta0\\default"
        si.dwFlags     = STARTF_USESHOWWINDOW
        si.wShowWindow = SW_HIDE
        pi = PROCESS_INFORMATION()

        # 5. Create the process in the user's session
        ok = advapi32.CreateProcessAsUserW(
            dup_token,
            RECORDER_PATH,
            None,           # command line
            None, None,     # process / thread security attrs
            False,          # inherit handles
            CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT,
            env_block,
            None,           # current dir (inherit)
            ctypes.byref(si),
            ctypes.byref(pi),
        )

        if ok:
            log(f"  session {session_id}: recorder.exe launched (pid={pi.dwProcessId})")
            kernel32.CloseHandle(pi.hProcess)
            kernel32.CloseHandle(pi.hThread)
        else:
            err = kernel32.GetLastError()
            # ERROR_SHARING_VIOLATION(32) or similar → usually means already running
            if err == 5:
                log(f"  session {session_id}: access denied (recorder may already be running)")
            else:
                log(f"  session {session_id}: CreateProcessAsUser FAILED err={err}")

    finally:
        if env_block:  userenv.DestroyEnvironmentBlock(env_block)
        if dup_token:  kernel32.CloseHandle(dup_token)
        if user_token: kernel32.CloseHandle(user_token)


# ──── Main ────
def main():
    log("=== Launcher started ===")

    if not os.path.exists(RECORDER_PATH):
        log(f"ERROR: recorder.exe not found at {RECORDER_PATH}")
        return

    session_ids = get_active_session_ids()
    log(f"Active sessions: {session_ids}")

    for sid in session_ids:
        launch_in_session(sid)

    log("=== Launcher done ===")


if __name__ == "__main__":
    main()
