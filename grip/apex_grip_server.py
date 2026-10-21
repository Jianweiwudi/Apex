#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Apex 抓地力后端 —— 给 UI 上那张「抓地力」卡提供真正可用的实现

原理
----
ACC 的轮胎抓地力由一组"力-滑移曲线"决定，形状固定为

    [0, 0.9, 0.95, 0.96, 0.965, 0.972, 0.996, 1.0, (1.0, 0.99, 0.99 …)]

这是 ACC 轮胎模型的归一化曲线，**所有车型完全一致**（雷克萨斯 / 日产 GT-R /
奔驰 AMG 实测同一串数值）。乘倍率写回去，轮胎峰值摩擦直接变化，而且写进去
不会被游戏每帧重算覆盖（与车对象里那些派生值不同）。

定位（与车型无关，三层加速）
---------------------------
1. 并行枚举区域（8 线程，按 256 GB 切块抢任务）；
2. 分三层扫：**小分配区（≤1 MB）→ 中（≤64 MB）→ 大**。ACC 的曲线都放在几十 KB
   的堆块里，第一层通常几秒就命中，命中即停，不再扫剩下几个 GB；
3. 高地址段（≥0x1000_0000_0000）全落空才退回低地址兜底。

崩溃防护
--------
* **写前校验**：每次写某条曲线之前，先回读它，确认"当前值 == 原厂值 × 某个合理倍率"。
  地址若已被游戏释放/复用（会话重载后很常见），读出来就不是这个比例，直接跳过，
  绝不往无关内存里写 —— 这是之前偶发崩溃的主因。
* **渐变**：倍率不是一步从 1.00 跳到 5.00，而是在 ~0.3 秒内分 10 步过渡，
  避免瞬间改变轮胎力导致物理解算炸掉。
* 连续失效的曲线会被剔除；全部失效则自动重新定位。

接口
----
  GET /grip?x=1.50     设倍率（UI 范围 -0.5~5，物理上钳到 0.05~5）
  GET /status          当前状态（含扫描进度、剩余秒数）
  GET /restore         还原原厂（倍率回 1.00）
  GET /rescan          丢弃缓存重新扫描
  GET /damage?on=1|0   碰撞车损 0 / 原厂
  GET /damage          读取碰撞车损状态
  GET /movie           启动影片状态（是否已换成 Apex 开场、游戏是否在跑、进度）
  GET /movie/scan[?root=]  重新探测 ACC 安装目录 / 记录手动路径
  GET /movie/apply     备份原厂片头并换成 Apex 开场（后台任务，立即返回）
  GET /movie/restore   从备份还原原厂片头（后台任务）
  GET /quit            还原并退出
"""

import ctypes as C
import json
import os
import re
import shutil
import struct
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
CURVES_FILE = os.path.join(HERE, 'grip_curves.json')
FACTOR_FILE = os.path.join(HERE, 'grip_factor.txt')
DAMAGE_CACHE = os.path.join(HERE, 'damage_cache.json')
OVERLAY_CMD = os.path.join(os.path.dirname(HERE), 'ApexOverlay.cmd')
PORT = 7798
MIN_X, MAX_X = 0.05, 5.0
PROC = 'AC2-Win64-Shipping.exe'

# Auto-flash: when the car directly ahead is within one second of gap, tap ACC's
# headlight-flash binding (Shift+L) repeatedly. This only synthesises the same key
# the driver would press; it does not write game memory.
FLASH_ON = False
FLASH_GAP = None
FLASH_LAST = 0.0
FLASH_INTERVAL = 0.085
FLASH_ACTIVE = 0
GAME_PID = 0
GAME_PID_AT = 0.0

# Auto-flash trigger configuration:
#   gap    - car ahead within FLASH_GAP_LIMIT seconds
#   finish - after the lap counter increments, for FLASH_FINISH_HOLD seconds
#   both   - either condition
FLASH_MODE = 'gap'
FLASH_GAP_LIMIT = 1.0
FLASH_FINISH_HOLD = 2.0
FLASH_FINISH_UNTIL = 0.0
FLASH_LAST_LAP = None
FLASH_SOURCE = ''

# Rear-car annoyance: rain light immediately, hazards/flashers after a short delay.
ANNOY_ON = False
ANNOY_LIMIT = 2.0
ANNOY_RAIN = False
ANNOY_HAZARD = False
ANNOY_HAZARD_AT = 0.0
ANNOY_PENDING_OFF = False

# Collision-immunity defers repair for 0.7 s after the damage values stop changing.
# The crash report showed EXCEPTION_ACCESS_VIOLATION at the exact frame a front-damage
# event was written; delaying until the physics step has settled avoids that race while
# still repairing during normal driving (no stop required). The hit itself is still
# registered briefly.
DAMAGE_WRITE_ENABLED = True

# ACC realism struct: damageRate(float), penalties(int), tyreFuelWear(int),
# unlimitedTyreSet(int), brakeFading(int), fastRollingStart(int), teleport(int).
# The seven-word sequence is unique in the current ACC build, so it can be found
# without hard-coding a heap address that changes every launch.
DAMAGE_SIG = struct.pack('<7i', 0x3f800000, 0, 0, 1, 0, 1, 1)
DAMAGE_SIG_ON = struct.pack('<7i', 0, 0, 0, 1, 0, 1, 1)
DAMAGE_OFF = struct.pack('<f', 1.0)
DAMAGE_ON = struct.pack('<f', 0.0)

# ACC 轮胎力-滑移曲线的归一化形状：前 8 个点在所有车型上完全相同，
# 用它当字节签名，既不依赖车型，也不会误命中别的浮点数组。
SIG = struct.pack('<8f', 0.0, 0.9, 0.95, 0.96, 0.965, 0.972, 0.996, 1.0)
SIG_V1 = 0.9          # 签名第 2 个点，归一化基准

# 扫描分层（按内存块大小，单位字节）。实测 ACC 的轮胎曲线全在 64 KB 的堆块里，
# 所以第一层只扫 0.87 GB，约 1.1 秒就能命中；后面几层只是兜底。
TIER_BANDS = ((64 << 10, '小分配'),
              (1 << 20, '中分配'),
              (64 << 20, '大分配'),
              (None, '超大分配'))

HEAP_LO = 0x10000000000   # ACC 的车辆/轮胎数据都在这个地址以上
ADDR_HI = 0x7FFFFFFF0000

k32 = C.WinDLL('kernel32', use_last_error=True)
k32.OpenProcess.restype = C.c_void_p
k32.OpenProcess.argtypes = [C.c_ulong, C.c_int, C.c_ulong]
k32.ReadProcessMemory.restype = C.c_int
k32.ReadProcessMemory.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.restype = C.c_int
k32.WriteProcessMemory.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.VirtualQueryEx.restype = C.c_size_t
k32.VirtualQueryEx.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_size_t]
k32.CreateMutexW.restype = C.c_void_p
k32.CreateMutexW.argtypes = [C.c_void_p, C.c_int, C.c_wchar_p]
k32.OpenFileMappingW.restype = C.c_void_p
k32.OpenFileMappingW.argtypes = [C.c_ulong, C.c_int, C.c_wchar_p]
k32.MapViewOfFile.restype = C.c_void_p
k32.MapViewOfFile.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong, C.c_ulong, C.c_size_t]
k32.UnmapViewOfFile.restype = C.c_int
k32.UnmapViewOfFile.argtypes = [C.c_void_p]
k32.CloseHandle.restype = C.c_int
k32.CloseHandle.argtypes = [C.c_void_p]

user32 = C.WinDLL('user32', use_last_error=True)
user32.GetForegroundWindow.restype = C.c_void_p
user32.GetWindowThreadProcessId.argtypes = [C.c_void_p, C.POINTER(C.c_ulong)]
user32.keybd_event.argtypes = [C.c_ubyte, C.c_ubyte, C.c_ulong, C.c_size_t]


class MBI(C.Structure):
    _fields_ = [('Base', C.c_ulonglong), ('AllocBase', C.c_ulonglong),
                ('AllocProtect', C.c_ulong), ('_a1', C.c_ulong),
                ('Size', C.c_ulonglong), ('State', C.c_ulong),
                ('Protect', C.c_ulong), ('Type', C.c_ulong), ('_a2', C.c_ulong)]


PROT_OK = (0x02, 0x04, 0x06, 0x08, 0x20, 0x40, 0x80)


LOG_PATH = os.path.join(HERE, 'apex_grip.log')


def log(msg):
    """同时写控制台和日志文件。

    pythonw.exe（双击 ApexGrip.cmd 走的就是它）没有控制台，sys.stdout 是 None，
    直接 print 会抛 AttributeError 让进程秒退。所以两边都要 try。
    """
    line = '[%s] %s' % (time.strftime('%H:%M:%S'), msg)
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 2 << 20:
            os.replace(LOG_PATH, LOG_PATH + '.1')
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError:
        pass


class PROCESSENTRY32W(C.Structure):
    _fields_ = [('dwSize', C.c_ulong), ('cntUsage', C.c_ulong), ('th32ProcessID', C.c_ulong),
                ('th32DefaultHeapID', C.c_size_t), ('th32ModuleID', C.c_ulong),
                ('cntThreads', C.c_ulong), ('th32ParentProcessID', C.c_ulong),
                ('pcPriClassBase', C.c_long), ('dwFlags', C.c_ulong),
                ('szExeFile', C.c_wchar * 260)]


k32.CreateToolhelp32Snapshot.restype = C.c_void_p
k32.CreateToolhelp32Snapshot.argtypes = [C.c_ulong, C.c_ulong]
k32.Process32FirstW.argtypes = [C.c_void_p, C.POINTER(PROCESSENTRY32W)]
k32.Process32NextW.argtypes = [C.c_void_p, C.POINTER(PROCESSENTRY32W)]
k32.CloseHandle.argtypes = [C.c_void_p]
k32.GetExitCodeProcess.argtypes = [C.c_void_p, C.POINTER(C.c_ulong)]

STILL_ACTIVE = 259


def pid_of(name):
    """用 Toolhelp32 快照查进程 PID。

    原来用 subprocess 调 tasklist，游戏运行时单次要 20-40 秒（子进程创建+全表枚举），
    定位流程就卡在这里；快照 API 只要几毫秒。
    """
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)      # TH32CS_SNAPPROCESS
    if not snap or snap == C.c_void_p(-1).value:
        return None
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = C.sizeof(entry)
        if not k32.Process32FirstW(snap, C.byref(entry)):
            return None
        while True:
            if entry.szExeFile.lower() == name.lower():
                return int(entry.th32ProcessID)
            if not k32.Process32NextW(snap, C.byref(entry)):
                return None
    finally:
        k32.CloseHandle(snap)


def overlay_running():
    try:
        with urllib.request.urlopen('http://127.0.0.1:7799/apex/state', timeout=0.7) as r:
            return r.status == 200
    except Exception:
        return False


def overlay_show():
    try:
        with urllib.request.urlopen('http://127.0.0.1:7799/apex/cmd?show=1', timeout=0.8) as r:
            return r.status == 200
    except Exception:
        return False


def start_overlay():
    if overlay_running():
        return True
    if not os.path.isfile(OVERLAY_CMD):
        return False
    try:
        subprocess.Popen(
            ['cmd.exe', '/c', OVERLAY_CMD],
            cwd=os.path.dirname(OVERLAY_CMD),
            creationflags=0x08000000,   # CREATE_NO_WINDOW; the overlay has its own window
            close_fds=True,
        )
    except Exception:
        return False
    # The overlay boots hidden. "啟動疊加層" must leave something on screen, not
    # start a process that the user then has to reveal with a second click.
    for _ in range(20):
        if overlay_running():
            overlay_show()
            return True
        time.sleep(0.15)
    return overlay_running()


def shared(name, size=512):
    h = k32.OpenFileMappingW(4, False, name)
    if not h:
        return None
    p = k32.MapViewOfFile(h, 4, 0, 0, size)
    if not p:
        k32.CloseHandle(h)
        return None
    try:
        return C.string_at(p, size)
    finally:
        # The auto-flash loop polls at 25 Hz. The old version mapped a fresh view
        # every time and never released it, leaking handles/views for the whole
        # session. Copy the bytes, then release the view and the mapping handle.
        k32.UnmapViewOfFile(p)
        k32.CloseHandle(h)


def shared_damage():
    d = shared('Local\\acpmf_physics', 256)
    if not d:
        return None
    return struct.unpack_from('<5f', d, 224)


def shared_speed():
    d = shared('Local\\acpmf_physics', 64)
    if not d:
        return 0.0
    return struct.unpack_from('<f', d, 28)[0]


def car_name():
    d = shared('Local\\acpmf_static')
    return d[68:134].decode('utf-16-le', 'ignore').split('\x00')[0].strip() if d else ''


def track_name():
    d = shared('Local\\acpmf_static')
    return d[134:200].decode('utf-16-le', 'ignore').split('\x00')[0].strip() if d else ''


def game_pid():
    global GAME_PID, GAME_PID_AT
    now = time.time()
    if now - GAME_PID_AT > 1.0:
        GAME_PID_AT = now
        GAME_PID = pid_of(PROC) or 0
    return GAME_PID


def foreground_is_game():
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    pid = C.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
    return bool(pid.value) and pid.value == game_pid()


def send_flash_key():
    """Tap ACC's default EnableFlashingLights binding (Shift+L)."""
    KEYUP = 0x0002
    VK_SHIFT = 0x10
    VK_L = 0x4C
    user32.keybd_event(VK_SHIFT, 0, 0, 0)
    user32.keybd_event(VK_L, 0, 0, 0)
    time.sleep(0.015)
    user32.keybd_event(VK_L, 0, KEYUP, 0)
    user32.keybd_event(VK_SHIFT, 0, KEYUP, 0)


def completed_laps():
    g = shared('Local\\acpmf_graphics', 256)
    if not g or len(g) < 136:
        return None
    return struct.unpack_from('<i', g, 132)[0]


def send_rain_key():
    """Tap ACC's default rain-light binding (Ctrl+L)."""
    KEYUP = 0x0002
    VK_CONTROL = 0x11
    VK_L = 0x4C
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_L, 0, 0, 0)
    time.sleep(0.015)
    user32.keybd_event(VK_L, 0, KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYUP, 0)


def car_ahead_gap():
    """Return the time gap (seconds) to the nearest car in the forward cone.

    Uses the graphics page's 60 car coordinates plus the player's velocity vector
    from the physics page. It deliberately ignores cars beside/behind: the forward
    component must be positive and the lateral offset inside a narrow cone.
    """
    phys = shared('Local\\acpmf_physics', 64)
    graf = shared('Local\\acpmf_graphics', 1600)
    if not phys or not graf:
        return None
    speed = struct.unpack_from('<f', phys, 28)[0] / 3.6
    if speed < 2.0:
        return None
    vx, _, vz = struct.unpack_from('<3f', phys, 32)
    norm = (vx * vx + vz * vz) ** 0.5
    if norm < 0.2:
        return None
    fx, fz = vx / norm, vz / norm
    player_id = struct.unpack_from('<i', graf, 1216)[0]
    if not player_id:
        return None
    pidx = None
    for i in range(60):
        if struct.unpack_from('<i', graf, 976 + i * 4)[0] == player_id:
            pidx = i
            break
    if pidx is None:
        return None
    px, _, pz = struct.unpack_from('<3f', graf, 256 + pidx * 12)
    best = None
    for i in range(60):
        if i == pidx:
            continue
        cid = struct.unpack_from('<i', graf, 976 + i * 4)[0]
        if not cid:
            continue
        x, _, z = struct.unpack_from('<3f', graf, 256 + i * 12)
        if abs(x) < 1e-3 and abs(z) < 1e-3:
            continue
        dx, dz = x - px, z - pz
        along = dx * fx + dz * fz
        if along <= 1.0 or along > 300.0:
            continue
        lateral = abs(dx * fz - dz * fx)
        if lateral > max(3.0, along * 0.32):
            continue
        gap = along / speed
        if gap < 0.05:
            continue
        if best is None or gap < best:
            best = gap
    return best


def car_behind_gap():
    """Return the time gap (seconds) to the nearest car behind the player."""
    phys = shared('Local\\acpmf_physics', 64)
    graf = shared('Local\\acpmf_graphics', 1600)
    if not phys or not graf:
        return None
    speed = struct.unpack_from('<f', phys, 28)[0] / 3.6
    if speed < 2.0:
        return None
    vx, _, vz = struct.unpack_from('<3f', phys, 32)
    norm = (vx * vx + vz * vz) ** 0.5
    if norm < 0.2:
        return None
    fx, fz = vx / norm, vz / norm
    player_id = struct.unpack_from('<i', graf, 1216)[0]
    if not player_id:
        return None
    pidx = None
    for i in range(60):
        if struct.unpack_from('<i', graf, 976 + i * 4)[0] == player_id:
            pidx = i
            break
    if pidx is None:
        return None
    px, _, pz = struct.unpack_from('<3f', graf, 256 + pidx * 12)
    best = None
    for i in range(60):
        if i == pidx:
            continue
        cid = struct.unpack_from('<i', graf, 976 + i * 4)[0]
        if not cid:
            continue
        x, _, z = struct.unpack_from('<3f', graf, 256 + i * 12)
        if abs(x) < 1e-3 and abs(z) < 1e-3:
            continue
        dx, dz = x - px, z - pz
        along = dx * fx + dz * fz
        if along >= -1.0 or along < -300.0:
            continue
        lateral = abs(dx * fz - dz * fx)
        if lateral > max(3.0, abs(along) * 0.32):
            continue
        gap = abs(along) / speed
        if gap < 0.05:
            continue
        if best is None or gap < best:
            best = gap
    return best


def annoy_off():
    global ANNOY_RAIN, ANNOY_HAZARD, ANNOY_PENDING_OFF
    if not ANNOY_RAIN and not ANNOY_HAZARD:
        ANNOY_PENDING_OFF = False
        return
    if game_pid() and foreground_is_game():
        try:
            if ANNOY_HAZARD:
                send_flash_key()
            if ANNOY_RAIN:
                send_rain_key()
        except Exception:
            pass
        ANNOY_RAIN = False
        ANNOY_HAZARD = False
        ANNOY_PENDING_OFF = False
    else:
        # Cannot synthesise a key while the game is in the background. Remember to
        # switch both lights off as soon as it comes back to the foreground.
        ANNOY_PENDING_OFF = True


def annoy_loop():
    global ANNOY_ON, ANNOY_RAIN, ANNOY_HAZARD, ANNOY_HAZARD_AT, ANNOY_PENDING_OFF
    last_app = 0.0
    app_alive = True
    while True:
        time.sleep(0.04)
        now = time.time()
        if now - last_app > 1.0:
            last_app = now
            app_alive = bool(pid_of('Apex.exe'))
        if not app_alive:
            ANNOY_ON = False
            ANNOY_RAIN = False
            ANNOY_HAZARD = False
            continue
        if not ANNOY_ON:
            if ANNOY_RAIN or ANNOY_HAZARD or ANNOY_PENDING_OFF:
                annoy_off()
            continue
        if not game_pid() or not foreground_is_game():
            continue
        if ANNOY_PENDING_OFF:
            annoy_off()
            continue
        gap = car_behind_gap()
        if gap is not None and gap <= ANNOY_LIMIT:
            if not ANNOY_RAIN:
                try:
                    send_rain_key()
                except Exception:
                    pass
                ANNOY_RAIN = True
                ANNOY_HAZARD_AT = now + 0.35
            if not ANNOY_HAZARD and now >= ANNOY_HAZARD_AT:
                try:
                    send_flash_key()
                except Exception:
                    pass
                ANNOY_HAZARD = True
        else:
            if ANNOY_HAZARD:
                try:
                    send_flash_key()
                except Exception:
                    pass
                ANNOY_HAZARD = False
            if ANNOY_RAIN:
                try:
                    send_rain_key()
                except Exception:
                    pass
                ANNOY_RAIN = False


def flash_loop():
    global FLASH_GAP, FLASH_LAST, FLASH_ACTIVE, FLASH_ON
    global FLASH_FINISH_UNTIL, FLASH_LAST_LAP, FLASH_SOURCE
    last_app = 0.0
    app_alive = True
    while True:
        time.sleep(0.04)
        if not FLASH_ON:
            FLASH_ACTIVE = 0
            FLASH_GAP = None
            FLASH_SOURCE = ''
            continue
        now = time.time()
        if now - last_app > 1.0:
            last_app = now
            app_alive = bool(pid_of('Apex.exe'))
        if not app_alive:
            FLASH_ON = False
            FLASH_ACTIVE = 0
            FLASH_GAP = None
            FLASH_SOURCE = ''
            continue
        if not game_pid() or not foreground_is_game():
            FLASH_ACTIVE = 0
            continue
        # Both features use Shift+L for the flashers; rear-car annoyance owns that
        # binding while it is enabled, otherwise the two would toggle each other.
        if ANNOY_ON:
            FLASH_ACTIVE = 0
            continue

        laps = completed_laps()
        if laps is not None:
            if FLASH_LAST_LAP is None or laps < FLASH_LAST_LAP:
                FLASH_LAST_LAP = laps
            elif laps > FLASH_LAST_LAP:
                FLASH_LAST_LAP = laps
                FLASH_FINISH_UNTIL = now + FLASH_FINISH_HOLD

        gap = None
        if FLASH_MODE in ('gap', 'both'):
            gap = car_ahead_gap()
            FLASH_GAP = gap
        else:
            FLASH_GAP = None

        gap_hit = gap is not None and gap <= FLASH_GAP_LIMIT
        finish_hit = FLASH_MODE in ('finish', 'both') and now < FLASH_FINISH_UNTIL
        if not gap_hit and not finish_hit:
            FLASH_ACTIVE = 0
            FLASH_SOURCE = ''
            continue
        FLASH_SOURCE = 'finish' if finish_hit and not gap_hit else 'gap'
        if now - FLASH_LAST >= FLASH_INTERVAL:
            FLASH_LAST = now
            FLASH_ACTIVE = 1
            try:
                send_flash_key()
            except Exception:
                pass


def flash_status():
    return {
        'on': bool(FLASH_ON),
        'gap': round(FLASH_GAP, 3) if FLASH_GAP is not None else None,
        'active': bool(FLASH_ACTIVE),
        'source': FLASH_SOURCE,
        'mode': FLASH_MODE,
        'limit': round(FLASH_GAP_LIMIT, 2),
        'finishHold': round(FLASH_FINISH_HOLD, 2),
        'annoy': bool(ANNOY_ON),
        'annoyRain': bool(ANNOY_RAIN),
        'annoyHazard': bool(ANNOY_HAZARD),
        'key': 'Shift+L',
    }


def shape_ok(v):
    """归一化后的抓地曲线形状校验（与具体车型无关）。"""
    if len(v) < 8:
        return False
    if abs(v[0]) > 1e-4:
        return False
    if not (0.85 <= v[1] <= 1.0):
        return False
    if min(v) < -0.05 or max(v) > 1.15:
        return False
    head = v[1:min(10, len(v))]
    return (sum(head) / len(head) >= 0.88) and all(0.85 <= x <= 1.10 for x in head)


UI_INFO = {'v': '', 'x': '', 'hist': []}


class Grip:
    def __init__(self):
        self.lock = threading.Lock()
        self.h = None
        self.pid = None
        self.name = ''
        self.curves = []          # [(addr, [原厂值...])]
        self.factor = 1.0          # 当前已写入内存的倍率（渐变过程中是中间值）
        self.target = 1.0          # 界面要求的倍率
        self.last_locate = 0.0
        self.last_attempt = 0.0
        self.locating = False
        self.note = ''
        # 扫描进度（给界面显示"大约还要多久"）
        self.scan_total = 0
        self.scan_done = 0
        self.scan_start = 0.0
        self.scan_stage = ''
        # collision damage (independent of the grip curves)
        self.damage_on = False
        self.damage_addr = None
        self.damage_applied = False
        self.damage_note = ''
        self.damage_last_log = None
        self.crash_addr = None
        self.crash_ptr = None
        self.crash_off = None
        self.crash_track = ''
        self.crash_car = ''
        self.crash_not_live = 0
        self.crash_fail = 0
        self.discovering = False
        self.dmg_last_vals = None
        self.dmg_since = 0.0
        self.damage_lock = threading.RLock()

    # ---------- 进程 / 内存 ----------
    def attach(self):
        # 句柄还有效就直接用：稳态下这里是微秒级，不再每次枚举进程
        if self.h and self.pid:
            code = C.c_ulong(0)
            if k32.GetExitCodeProcess(self.h, C.byref(code)) and code.value == STILL_ACTIVE:
                return True
            self.h = None
            self.pid = None
        pid = pid_of(PROC)
        if not pid:
            self.pid = None
            self.h = None
            return False
        if pid != self.pid:
            self.h = None
            self.pid = pid
        if not self.h:
            self.h = (k32.OpenProcess(0x1F0FFF, False, pid)
                      or k32.OpenProcess(0x0410, False, pid))
        return bool(self.h)

    def rd(self, addr, n):
        if not self.h:
            return None
        buf = C.create_string_buffer(n)
        got = C.c_size_t(0)
        if k32.ReadProcessMemory(self.h, C.c_void_p(addr), buf, n, C.byref(got)):
            return buf.raw[:got.value]
        return None

    def wr(self, addr, data):
        if not self.h:
            return False
        buf = C.create_string_buffer(data, len(data))
        got = C.c_size_t(0)
        return bool(k32.WriteProcessMemory(self.h, C.c_void_p(addr), buf, len(data), C.byref(got)))

    def live(self):
        """车是否已经载入（车库/维修区/赛道都算）。

        原来还要求转速 > 200，导致在车库里（引擎没着车）永远不扫描、界面一直
        "等待进入赛道"。其实只要油量有值，车模型和轮胎数据就已经在内存里了。
        """
        d = shared('Local\\acpmf_physics', 256)
        if not d:
            return False
        return struct.unpack_from('<f', d, 12)[0] > 0.05

    def enum_regions(self, lo, hi, nthreads=8):
        """并行枚举可读的私有区域。

        单线程遍历 64 位地址空间要 15-20 秒（几万次 VirtualQueryEx），这里按
        256 GB 切块、8 个线程抢任务，同样的调用分摊到 8 个核上。
        """
        CHUNK = 0x4000000000
        chunks = []
        a = lo
        while a < hi:
            chunks.append((a, min(hi, a + CHUNK)))
            a += CHUNK
        idx = [0]
        glk = threading.Lock()
        out = []
        olk = threading.Lock()

        def work():
            local = []
            while True:
                with glk:
                    i = idx[0]
                    idx[0] += 1
                if i >= len(chunks):
                    break
                ca, cb = chunks[i]
                base = ca
                mbi = MBI()
                while base < cb and k32.VirtualQueryEx(self.h, C.c_void_p(base), C.byref(mbi), C.sizeof(mbi)):
                    rlo = max(mbi.Base, ca)
                    rhi = min(mbi.Base + mbi.Size, cb)
                    if (rhi > rlo and mbi.State == 0x1000
                            and (mbi.Protect & 0xFF) in PROT_OK and mbi.Type == 0x20000):
                        local.append((rlo, rhi - rlo))
                    base = mbi.Base + mbi.Size
            if local:
                with olk:
                    out.extend(local)

        threads = [threading.Thread(target=work, daemon=True) for _ in range(nthreads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        uniq = {}
        for b, s in out:
            uniq[b] = max(uniq.get(b, 0), s)
        return sorted(uniq.items())

    # ---------- 曲线识别 ----------
    def read_curve(self, addr):
        """把 addr 处的曲线读出来，返回归一化后的原厂值（长度按"回落到 0 就结束"）。"""
        d = self.rd(addr, 26 * 4)
        if not d or len(d) < 8 * 4:
            return None
        vals = list(struct.unpack('<%df' % (len(d) // 4), d))
        n = 1
        while n < len(vals) and vals[n] >= 0.05:
            n += 1
        v = vals[:n]
        if len(v) < 8 or not shape_ok(v):
            return None
        # 归一化：第 2 个点固定为 0.9。这样即使当前内存里是"已放大"的值，
        # 也能还原出真正的原厂值，不会越乘越大。
        k = SIG_V1 / v[1] if v[1] else 1.0
        return [x * k for x in v]

    def scan_curves(self):
        """分层扫描，命中即停。"""
        self.scan_start = time.time()
        self.scan_total = 0
        self.scan_done = 0
        for lo, hi, tag in ((HEAP_LO, ADDR_HI, '高地址'), (0x10000, HEAP_LO, '低地址')):
            regions = self.enum_regions(lo, hi)
            if not regions:
                continue
            prev = 0
            for limit, label in TIER_BANDS:
                group = [(b, s) for b, s in regions
                         if prev < s and (limit is None or s <= limit)]
                prev = limit if limit is not None else prev
                if not group:
                    continue
                self.scan_stage = '%s/%s' % (tag, label)
                hits = self._scan_regions(group)
                if hits:
                    log('%s 命中 %d 处签名（耗时 %.1fs）'
                        % (self.scan_stage, len(hits), time.time() - self.scan_start))
                    return self._collect(hits)
        return []

    def _scan_regions(self, regions, nthreads=6):
        total = sum(sz for _, sz in regions) or 1
        self.scan_total = total
        self.scan_done = 0
        nthreads = min(nthreads, max(1, len(regions)))
        buckets = [[] for _ in range(nthreads)]
        acc = 0
        for base, size in regions:
            buckets[min(nthreads - 1, int(acc * nthreads / total))].append((base, size))
            acc += size
        results = [[] for _ in range(nthreads)]
        lk = threading.Lock()

        def work(idx, regs):
            hits = []
            try:
                for base, size in regs:
                    off = 0
                    while off < size:
                        n = min(1 << 22, size - off)
                        d = self.rd(base + off, n)
                        if d:
                            i = d.find(SIG)
                            while i != -1:
                                hits.append(base + off + i)
                                i = d.find(SIG, i + 1)
                        off += n
                        with lk:
                            self.scan_done += n
            except Exception:
                pass
            results[idx] = hits

        threads = [threading.Thread(target=work, args=(i, buckets[i]), daemon=True)
                   for i in range(nthreads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return [a for part in results for a in part]

    def _collect(self, hits):
        self.scan_done = max(self.scan_total, 1)
        out, seen = [], set()
        for addr in hits:
            if addr in seen:
                continue
            seen.add(addr)
            v = self.read_curve(addr)
            if v:
                out.append((addr, v))
        return out

    def cached_curves(self):
        try:
            d = json.load(open(CURVES_FILE))
        except Exception:
            return []
        out = []
        for item in d.get('curves', []):
            try:
                addr = int(item[0])
                stock = [float(x) for x in item[1]]
            except (TypeError, ValueError):
                continue
            if len(stock) >= 8:
                out.append((addr, stock))
        return out

    def save_curves(self, curves):
        try:
            json.dump({'curves': [[a, v] for a, v in curves],
                       'car': self.name, 'time': time.time()},
                      open(CURVES_FILE, 'w'), ensure_ascii=False)
        except OSError:
            pass

    def alive_at(self, addr, stock):
        """地址上还是不是这条曲线。

        不能用 read_curve 的归一化判据：倍率拖到 1 以下时曲线整体变小
        （例如 0.9 × 0.5 = 0.45），会被形状判据当成"不是曲线"，进而误判地址失效、
        触发无休止重扫。这里只做"是 stock × 某个统一倍率"的线性校验。
        """
        d = self.rd(addr, len(stock) * 4)
        if not d or len(d) < len(stock) * 4:
            return False
        vals = struct.unpack('<%df' % len(stock), d)
        if abs(stock[1]) < 1e-9:
            return False
        ratio = vals[1] / stock[1]
        if not (0.02 <= ratio <= 6.5):
            return False
        return all(abs(a - b * ratio) <= max(2e-3, abs(b * ratio) * 0.05)
                   for a, b in zip(vals, stock))

    def curves_alive(self, curves):
        if not curves:
            return False
        checked = sum(1 for addr, stock in curves if self.alive_at(addr, stock))
        return checked >= max(1, len(curves) // 2)

    # ---------- 定位 ----------
    def locate(self, force=False):
        """耗时（常见 5-15 秒，最坏 60 秒），调用方不要持锁。"""
        if self.locating:
            return bool(self.curves)
        self.locating = True
        t0 = time.time()
        try:
            if not self.attach():
                return False
            t_att = time.time()
            self.name = car_name()
            if not force:
                cached = self.cached_curves()
                if self.curves_alive(cached):
                    with self.lock:
                        self.curves = cached
                    log('沿用缓存：%d 条曲线（%s，%.2fs）' % (len(cached), self.name, time.time() - t0))
                    return True
            t_cache = time.time()
            # 重扫前先把手上的曲线还原，否则已放大的曲线匹配不上签名
            if self.curves:
                with self.lock:
                    self.restore_locked()
            t_res = time.time()
            found = self.scan_curves()
            log('locate 分段：attach %.2fs / 缓存 %.2fs / 还原 %.2fs / 扫描 %.2fs'
                % (t_att - t0, t_cache - t_att, t_res - t_cache, time.time() - t_res))
            if not found:
                self.note = '没找到轮胎曲线（请确认已进入赛道）'
                log(self.note)
                return False
            with self.lock:
                self.curves = found
                self.factor = 1.0          # 刚扫到的就是原厂值
            self.save_curves(found)
            self.note = ''
            log('定位成功：%d 条抓地曲线（%s）' % (len(found), self.name))
            return True
        finally:
            self.locating = False
            self.last_locate = time.time()

    # ---------- 写入 ----------
    def write_curve(self, addr, stock, target):
        """带校验的写入：地址上必须仍然是 stock × 某个合理倍率的这条曲线。

        会话重载后旧地址常被释放或复用，直接写会把别的对象写坏 -> 游戏崩溃。
        """
        need = len(stock) * 4
        d = self.rd(addr, need)
        if not d or len(d) < need:
            return False, 'unreadable'
        vals = struct.unpack('<%df' % len(stock), d)
        if abs(stock[1]) < 1e-9:
            return False, 'bad-stock'
        ratio = vals[1] / stock[1]
        if not (0.02 <= ratio <= 6.5):
            return False, 'repurposed'
        if not all(abs(a - b * ratio) <= max(2e-3, abs(b * ratio) * 0.05)
                   for a, b in zip(vals, stock)):
            return False, 'repurposed'
        want = [v * target for v in stock]
        if not self.wr(addr, struct.pack('<%df' % len(stock), *want)):
            return False, 'write-fail'
        return True, ''

    def apply_locked(self, x=None):
        if x is not None:
            self.factor = x
        target = max(MIN_X, min(MAX_X, self.factor))
        ok, dead = 0, []
        for addr, stock in self.curves:
            good, why = self.write_curve(addr, stock, target)
            if good:
                ok += 1
            elif why == 'repurposed':
                dead.append(addr)
        if dead:
            drop = set(dead)
            self.curves = [(a, v) for a, v in self.curves if a not in drop]
            log('剔除 %d 条已被复用的曲线地址（剩 %d 条）' % (len(dead), len(self.curves)))
        return ok

    def verify_locked(self):
        if not self.curves:
            return False
        want = max(MIN_X, min(MAX_X, self.factor))
        ok = 0
        for addr, stock in self.curves[:4]:
            d = self.rd(addr, 8)
            if not d or len(d) < 8:
                continue
            now = struct.unpack_from('<f', d, 4)[0]
            if abs(now - stock[1] * want) <= max(2e-3, abs(stock[1] * want) * 3e-3):
                ok += 1
        return ok >= 1

    def restore_locked(self):
        n = 0
        for addr, stock in self.curves:
            good, _ = self.write_curve(addr, stock, 1.0)
            if good:
                n += 1
        return n

    def set_factor(self, x):
        """设目标倍率。真正的写入由 pump() 分步完成，这里立即返回，不阻塞请求。"""
        x = max(MIN_X, min(MAX_X, float(x)))
        with self.lock:
            self.target = x
            self.save_factor()

    def pump(self):
        """把已写入的倍率一步一步推向目标值。

        一步到位会让轮胎力瞬间跳变，物理解算偶发崩溃；每 30 ms 走一小步就平滑得多。
        滑块连续拖动时只有最新的目标值生效，不会堆积请求。
        """
        with self.lock:
            if not self.curves:
                self.factor = self.target
                return False
            gap = self.target - self.factor
            if abs(gap) < 1e-6:
                return False
            step = 0.15 if abs(gap) > 0.5 else 0.05
            self.factor += max(-step, min(step, gap))
            self.apply_locked()
            return True

    def save_factor(self):
        try:
            open(FACTOR_FILE, 'w').write('%.3f' % self.target)
        except OSError:
            pass

    def load_factor(self):
        try:
            return float(open(FACTOR_FILE).read().strip())
        except Exception:
            return 1.0

    def scan_progress(self):
        if not self.locating:
            return 100 if self.curves else 0
        if not self.scan_total:
            return 0
        return max(0, min(99, int(self.scan_done * 100 / self.scan_total)))

    def scan_eta(self):
        """剩余秒数：按"已用时间 ÷ 已完成比例"反推，比瞬时速率稳。

        还没开始读（枚举区域、开线程那段）返回 0，界面显示"准备中"。
        """
        if not self.locating or not self.scan_total or self.scan_done <= 0:
            return 0
        elapsed = time.time() - self.scan_start
        frac = self.scan_done / self.scan_total
        if frac < 0.01 or elapsed < 0.8:
            return 0
        return max(1, min(180, int(round(elapsed * (1 - frac) / frac))))

    def status_locked(self):
        return {
            'ui': UI_INFO.get('v', ''),
            'ui_x': UI_INFO.get('x', ''),
            'ui_hist': UI_INFO.get('hist', [])[-8:],
            'ok': bool(self.curves),
            'x': round(self.target, 3),
            'applied': round(max(MIN_X, min(MAX_X, self.factor)), 3),
            'curves': len(self.curves),
            'car': self.name,
            'live': self.live(),
            'locating': self.locating,
            'note': self.note,
            'stage': self.scan_stage,
            'progress': self.scan_progress(),
            'eta': self.scan_eta(),
            'damage': self.damage_status(),
        }

    # ---------- collision damage ----------
    def _damage_ok(self, addr):
        d = self.rd(addr, 28)
        if not d or len(d) < 28:
            return False
        w = struct.unpack('<7i', d)
        return w[0] in (0, 0x3f800000) and w[1:] == (0, 0, 1, 0, 1, 1)

    def find_damage(self):
        """Locate the realism settings block by its seven-word signature."""
        if not self.attach():
            return None
        regions = self.enum_regions(0, ADDR_HI)
        # The settings block lives in a small heap allocation; scan those first so
        # the first toggle is quick instead of walking 11 GB of game memory.
        regions.sort(key=lambda r: r[1])
        for lo, size in regions:
            if size > (4 << 20):
                continue
            d = self.rd(lo, size)
            if not d:
                continue
            for sig in (DAMAGE_SIG, DAMAGE_SIG_ON):
                j = d.find(sig)
                if j >= 0 and self._damage_ok(lo + j):
                    return lo + j
        for lo, size in regions:
            if size <= (4 << 20):
                continue
            off = 0
            while off < size:
                n = min(4 << 20, size - off)
                d = self.rd(lo + off, n)
                if d:
                    for sig in (DAMAGE_SIG, DAMAGE_SIG_ON):
                        j = d.find(sig)
                        if j >= 0 and self._damage_ok(lo + off + j):
                            return lo + off + j
                off += n - 32 if n == (4 << 20) else n
        return None

    def _crash_ok(self, addr):
        d = self.rd(addr, 20)
        if not d or len(d) != 20:
            return False
        try:
            vals = struct.unpack('<5f', d)
        except Exception:
            return False
        # Severe crashes can push a corner or the summed centre well above 250;
        # rejecting those values made the tool stop repairing exactly when the car
        # was badly damaged. Keep a loose sanity bound against unrelated memory.
        if not all(v == v and -0.01 <= v <= 100000.0 for v in vals):
            return False
        # If this address came from a pointer chain, prove the chain still points
        # here before every write. A stale cached address is what turns a harmless
        # freeze into a 20-byte write into unrelated game memory.
        if self.crash_ptr and self.crash_off is not None:
            p = self.rd(self.crash_ptr, 8)
            if not p or len(p) != 8:
                return False
            base = struct.unpack('<Q', p)[0]
            if base + self.crash_off != addr:
                return False
        return True

    def load_crash_addr(self):
        """Load the cached 5-float carDamage array for this game/heap layout."""
        cur_track, cur_car = track_name(), car_name()
        if (self.crash_addr and self._crash_ok(self.crash_addr)
                and (not self.crash_track or not cur_track or cur_track == self.crash_track)
                and (not self.crash_car or not cur_car or cur_car == self.crash_car)):
            return self.crash_addr
        self.crash_addr = None
        try:
            with open(DAMAGE_CACHE, 'r', encoding='utf-8') as f:
                j = json.load(f)
            if not self.pid or int(j.get('pid', 0)) != int(self.pid):
                return None
            c_track = str(j.get('track', ''))
            c_car = str(j.get('car', ''))
            if c_track and cur_track and c_track != cur_track:
                return None
            if c_car and cur_car and c_car != cur_car:
                return None
            addr = int(str(j.get('addr', '0')), 0)
            if addr and self._crash_ok(addr):
                self.crash_addr = addr
                self.crash_track = c_track or cur_track
                self.crash_car = c_car or cur_car
                return addr
            ptr = int(str(j.get('ptr', '0')), 0)
            off = int(str(j.get('off', '0')), 0)
            d = self.rd(ptr, 8) if ptr else None
            if d and len(d) == 8:
                base = struct.unpack('<Q', d)[0]
                if base and self._crash_ok(base + off):
                    self.crash_addr = base + off
                    self.crash_track = c_track or cur_track
                    self.crash_car = c_car or cur_car
                    return self.crash_addr
        except Exception:
            pass
        return None

    def save_crash_addr(self, addr):
        self.crash_addr = addr
        self.crash_track = track_name()
        self.crash_car = car_name()
        self.dmg_last_vals = None
        try:
            with open(DAMAGE_CACHE, 'w', encoding='utf-8') as f:
                json.dump({
                    'pid': self.pid,
                    'addr': '0x%X' % addr,
                    'track': self.crash_track,
                    'car': self.crash_car,
                }, f)
        except OSError:
            pass

    def discover_crash(self):
        """Find the authoritative carDamage array after the first collision.

        The array is not present with a useful value at session start (it is all
        zero), so it cannot be identified by content then. Once the HUD reports
        damage, every 5-float copy is tested; the one whose zeroing makes the HUD
        read zero is the live array. """
        vals = shared_damage()
        if not vals or max(vals) <= 0.1:
            return None
        pattern = struct.pack('<5f', *vals)
        self.discovering = True
        zero = b'\x00' * 20
        tested = set()
        try:
            regions = self.enum_regions(0, ADDR_HI)
            # Small heaps first, and test each hit immediately instead of gathering
            # every copy first. This is what removes the "stop the car and wait"
            # requirement: the first live candidate ends the scan.
            regions.sort(key=lambda r: r[1])

            def test(addr):
                if addr in tested or not self.damage_on:
                    return False
                tested.add(addr)
                before = self.rd(addr, 20)
                if before != pattern or not self.wr(addr, zero):
                    return False
                time.sleep(0.03)
                now = shared_damage()
                if now is not None and max(now) < 0.1:
                    self.save_crash_addr(addr)
                    log('damage array found @ 0x%X (%d tested)' % (addr, len(tested)))
                    return True
                self.wr(addr, before)
                return False

            for lo, size in regions:
                if not self.damage_on:
                    return None
                off = 0
                win = 8 << 20
                while off < size:
                    n = min(win, size - off)
                    d = self.rd(lo + off, n)
                    if d:
                        j = d.find(pattern)
                        while j >= 0:
                            if test(lo + off + j):
                                return self.crash_addr
                            if not self.damage_on:
                                return None
                            j = d.find(pattern, j + 1)
                    off += n - 32 if n == win else n
            log('damage discovery failed after %d candidates' % len(tested))
            return None
        finally:
            self.discovering = False

    def apply_damage(self):
        with self.damage_lock:
            return self._apply_damage()

    def _apply_damage(self):
        if not self.damage_on:
            self.damage_applied = False
            return
        if not self.attach():
            self.damage_note = 'game-not-running'
            self.damage_applied = False
            return
        if self.damage_addr is None or not self._damage_ok(self.damage_addr):
            # A session reload can briefly replace the block. Re-read once before
            # throwing the cached address away; losing a still-valid address forced
            # a full rescan on every heartbeat.
            if self.damage_addr is not None:
                time.sleep(0.05)
            if self.damage_addr is None or not self._damage_ok(self.damage_addr):
                self.damage_note = 'locating'
                self.damage_addr = self.find_damage()
        if not self.damage_addr:
            self.damage_note = 'not-found'
            self.damage_applied = False
            return
        if not self.wr(self.damage_addr, DAMAGE_ON):
            self.damage_note = 'write-failed'
            self.damage_applied = False
            return
        d = self.rd(self.damage_addr, 4)
        self.damage_applied = bool(d and struct.unpack('<f', d)[0] == 0.0)
        self.damage_note = '' if self.damage_applied else 'read-back-failed'
        if self.damage_applied and self.damage_last_log != self.damage_addr:
            self.damage_last_log = self.damage_addr
            log('collision damage rate -> 0.000 @ 0x%X' % self.damage_addr)

    def restore_damage(self):
        with self.damage_lock:
            return self._restore_damage()

    def _restore_damage(self):
        if self.damage_addr and self.attach():
            try:
                self.wr(self.damage_addr, DAMAGE_OFF)
            except Exception:
                pass
            log('collision damage rate -> 1.000')
        self.damage_applied = False
        self.damage_note = ''
        self.damage_last_log = None

    def set_damage(self, on):
        if not DAMAGE_WRITE_ENABLED:
            with self.damage_lock:
                self.damage_on = False
                self.damage_applied = False
                self.damage_note = 'disabled'
            return self.damage_status()
        with self.damage_lock:
            self.damage_on = bool(on)
            if self.damage_on:
                self._apply_damage()
                self.load_crash_addr()
            else:
                self._restore_damage()
        return self.damage_status()

    def damage_status(self):
        return {
            'on': bool(self.damage_on),
            'found': bool(self.damage_addr),
            'applied': bool(self.damage_applied),
            'crash': bool(self.crash_addr),
            'discovering': bool(self.discovering),
            'disabled': not DAMAGE_WRITE_ENABLED,
            'note': self.damage_note,
        }


GRIP = Grip()


def boot():
    """启动就试着连一次：有缓存就毫秒级恢复，没有就立刻开扫，不用等 watcher 的 2 秒节拍。"""
    time.sleep(0.2)
    try:
        if GRIP.locate():
            log('启动即就绪：%d 条曲线，目标 %.2fx' % (len(GRIP.curves), GRIP.target))
    except Exception as e:
        log('boot: %s' % e)


def pump_loop():
    """把倍率平滑推向目标值（30 ms 一步）。"""
    while True:
        time.sleep(0.03)
        try:
            GRIP.pump()
        except Exception as e:
            log('pump: %s' % e)


def crash_loop():
    """Safely repair the five-float carDamage array after a hit.

    The old version wrote every 20 ms to a cached address and auto-scanned/wrote
    hundreds of candidate copies. If the game restarted, the cached address could
    belong to unrelated memory - that is what crashed ACC. This version never
    auto-scans, never writes continuously, and writes only when all of these hold:
      * a cached address exists for the current game PID,
      * its pointer chain still resolves to the same address,
      * the shared physics page currently reports damage.
    """
    zero = b'\x00' * 20
    while True:
        time.sleep(0.15)
        if not GRIP.damage_on:
            continue
        try:
            if not GRIP.attach():
                continue
            cur_track, cur_car = track_name(), car_name()
            if (GRIP.crash_track and cur_track and cur_track != GRIP.crash_track) or \
               (GRIP.crash_car and cur_car and cur_car != GRIP.crash_car):
                # New track or car: the old address belongs to another loaded scene.
                GRIP.crash_addr = None
                GRIP.crash_track = ''
                GRIP.crash_car = ''
            if not GRIP.live():
                GRIP.crash_not_live += 1
                if GRIP.crash_not_live > 10:
                    GRIP.crash_addr = None
                    GRIP.crash_track = ''
                    GRIP.crash_car = ''
                continue
            GRIP.crash_not_live = 0
            if not GRIP.crash_addr:
                GRIP.load_crash_addr()
            vals = shared_damage()
            if not GRIP.crash_addr:
                if not vals or max(vals) <= 0.1:
                    GRIP.dmg_last_vals = None
                    continue
                # The car is already stopped (guard above). Wait until the damage
                # values are stable for a moment before locating the live array.
                if vals != GRIP.dmg_last_vals:
                    GRIP.dmg_last_vals = vals
                    GRIP.dmg_since = time.time()
                    continue
                if time.time() - GRIP.dmg_since < 0.7:
                    continue
                if not GRIP.discovering:
                    GRIP.discovering = True
                    threading.Thread(target=GRIP.discover_crash, daemon=True).start()
                continue
            if not vals or max(vals) <= 0.1:
                GRIP.dmg_last_vals = None
                continue
            # Wait until the impact has settled. The crash happened when carDamage was
            # written in the same frame as the damage event; 0.7 s later the physics
            # step that owned the array has finished, even if the car is still moving.
            if vals != GRIP.dmg_last_vals:
                GRIP.dmg_last_vals = vals
                GRIP.dmg_since = time.time()
                continue
            if time.time() - GRIP.dmg_since < 0.7:
                continue
            if not GRIP._crash_ok(GRIP.crash_addr):
                GRIP.crash_addr = None
                continue
            cleared = False
            for _ in range(3):
                if not GRIP.wr(GRIP.crash_addr, zero):
                    break
                time.sleep(0.03)
                now = shared_damage()
                if now is not None and max(now) < 0.1:
                    cleared = True
                    break
            if cleared:
                GRIP.crash_fail = 0
                GRIP.dmg_last_vals = None
            else:
                # A severe hit can move the live array or the game can rewrite the
                # values faster than one pass. Three failures means the cached address
                # is no longer the live one; drop it and locate again.
                GRIP.crash_fail += 1
                if GRIP.crash_fail >= 3:
                    GRIP.crash_fail = 0
                    GRIP.crash_addr = None
        except Exception:
            pass


def damage_loop():
    """Re-assert the damage rate while enabled, and recover after a session reload."""
    while True:
        time.sleep(1.5)
        if not GRIP.damage_on:
            continue
        # Do not use the browser heartbeat here: WebView2 timers are throttled or
        # suspended while ACC is in the foreground, which was silently turning the
        # feature off after ten seconds. The Apex process itself is the reliable
        # signal that the app is still open.
        if not pid_of('Apex.exe'):
            log('Apex process gone - restoring collision damage')
            GRIP.set_damage(False)
            continue
        try:
            GRIP.apply_damage()
        except Exception as e:
            log('damage: %s' % e)


def watcher():
    while True:
        time.sleep(2.0)
        try:
            if not GRIP.attach():
                continue
            if not GRIP.curves:
                if (GRIP.live() and not GRIP.locating
                        and (time.time() - GRIP.last_attempt) > 15):
                    GRIP.last_attempt = time.time()
                    if GRIP.locate():
                        log('定位完成，目标倍率 %.2fx（分步写入）' % GRIP.target)
                continue

            # 换车 -> 新车型的曲线是另一批内存，必须重扫
            name = car_name()
            if name and GRIP.name and name != GRIP.name and GRIP.live():
                log('检测到换车：%s -> %s，重新扫描' % (GRIP.name, name))
                GRIP.locate(force=True)
                continue

            with GRIP.lock:
                alive = GRIP.curves_alive(GRIP.curves)
            if not alive:
                if GRIP.live() and (time.time() - GRIP.last_attempt) > 6:
                    GRIP.last_attempt = time.time()
                    log('缓存地址已失效，重新扫描')
                    GRIP.locate(force=True)
                continue

            with GRIP.lock:
                if abs(GRIP.factor - 1.0) < 1e-6:
                    continue
                stale = not GRIP.verify_locked()
            if not stale:
                continue
            with GRIP.lock:
                GRIP.apply_locked()
                ok = GRIP.verify_locked()
            if ok:
                continue
            if (time.time() - GRIP.last_attempt) > 5:
                GRIP.last_attempt = time.time()
                GRIP.locate(force=True)
                log('会话重建，已重扫（目标 %.2fx）' % GRIP.target)
        except Exception as e:
            log('watcher: %s' % e)


# ---------------------------------------------------------------- 启动影片（ACC 片头）
# ACC 的片头是 NonUFS 松散文件（Manifest_NonUFSFiles_Win64.txt 里能查到），所以可以整体
# 替换，不必碰 16.5 GB 的 pak，也不动它的签名。反过来，文件名是被 cook 进资产里的，所以
# 必须同名同扩展名覆盖，新增一个别名文件不会生效。
# 播放链是 UMG 的 UGameIntroPage + FileMediaSource + WmfMedia，载荷必须是 WMF 能解的
# 容器/编码（这是 wmv2/wmav2 封装成 ASF 的原因，见 tools/make_intro.py）。
MOVIE_NAME = 'ACC_GameIntro_1.1_16-9.wmv'
MOVIE_REL = os.path.join('AC2', 'Content', 'Movies', MOVIE_NAME)
MOVIE_CFG = os.path.join(HERE, 'movie.json')
MOVIE_PAYLOAD = os.path.join(os.path.dirname(HERE), 'ui', 'media', 'apex_intro.wmv')
MOVIE_APPID = '805550'
MOVIE_CHUNK = 4 << 20
MOVIE_BAK = '.apex.bak'
MOVIE_TMP = '.apex.tmp'
MOVIE_STOCK_SIZE = 90993156        # 只用来在没有备份时给个「原厂」标签，不作判据

# 用户自备片头：任何编码都能进来，出去时统一成 ACC 能播的形状
MOVIE_TARGET_SECONDS = 72.22        # 原厂片头长度，导入的影片会被裁/补齐到这个长度
MOVIE_HOLD_TAIL = 0.08              # ASF 会在最后一帧后再写约 80 ms 尾包，先扣掉
MOVIE_IMPORT_EXT = ('.mp4', '.mkv', '.mov', '.avi', '.m4v', '.webm', '.wmv', '.mpg',
                    '.mpeg', '.ts', '.m2ts', '.flv')
CARD_LOOP = os.path.join(os.path.dirname(HERE), 'ui', 'media', 'card_loop.mp4')
MOVIE_VOL_MIN, MOVIE_VOL_MAX = 0.0, 2.0      # 0 % - 200 %

_VDF_PATH = re.compile(r'"path"\s+"([^"]+)"')
_VDF_LEGACY = re.compile(r'"\d+"\s+"([A-Za-z]:[^"]+)"')
_ACF_DIR = re.compile(r'"installdir"\s+"([^"]+)"')

MOVIE = {
    'lock': threading.Lock(),
    'job': {'active': False, 'op': '', 'phase': '', 'done': 0, 'total': 0, 'pct': 0,
            'error': '', 'started': 0.0, 'ended': 0.0},
    'cache': None,
    'cache_at': 0.0,
}


def _movie_cfg():
    try:
        with open(MOVIE_CFG, 'r', encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _movie_cfg_save(d):
    tmp = MOVIE_CFG + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, MOVIE_CFG)
    except OSError:
        pass                        # 只读目录 / 同步冲突时不影响使用，状态每次都实测


def _size(p):
    try:
        return os.path.getsize(p) if os.path.isfile(p) else 0
    except OSError:
        return 0


def _steam_path():
    try:
        import winreg
    except ImportError:
        return ''
    for hive, key, val in (
            (winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath'),
            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Valve\Steam', 'InstallPath')):
        try:
            with winreg.OpenKey(hive, key) as k:
                p = str(winreg.QueryValueEx(k, val)[0])
        except OSError:
            continue
        p = os.path.normpath(p)     # SteamPath 可能写成 u:/steam（正斜杠、小写盘符）
        if os.path.isdir(p):
            return p
    return ''


def _libraries(steam):
    libs, seen = [], set()

    def add(p):
        p = os.path.normpath(p or '')
        if p and p.lower() not in seen and os.path.isdir(p):
            seen.add(p.lower())
            libs.append(p)

    add(steam)
    try:
        with open(os.path.join(steam, 'steamapps', 'libraryfolders.vdf'), 'r',
                  encoding='utf-8', errors='replace') as f:
            txt = f.read()
    except OSError:
        return libs
    for m in _VDF_PATH.findall(txt) + _VDF_LEGACY.findall(txt):
        add(m.replace('\\\\', '\\'))
    return libs


def _valid_root(root):
    return bool(root) \
        and os.path.isdir(os.path.join(root, 'AC2', 'Content', 'Movies')) \
        and os.path.isdir(os.path.join(root, 'AC2', 'Binaries', 'Win64'))


def find_acc_root(force=False, manual=None):
    """返回 (安装根, 来源)。不 os.walk 全盘，只查注册表 → Steam 库 → 有限候选路径。"""
    cfg = _movie_cfg()
    if manual:
        manual = os.path.normpath(manual)
        if _valid_root(manual):
            cfg['root'] = manual
            cfg['source'] = 'manual'
            _movie_cfg_save(cfg)
            MOVIE['cache_at'] = 0.0
            return manual, 'manual'
        return '', ''

    if not force and MOVIE['cache'] and (time.time() - MOVIE['cache_at']) < 60:
        return MOVIE['cache']

    root, src = '', ''
    saved = cfg.get('root')
    if saved and _valid_root(saved):
        root, src = saved, cfg.get('source') or 'manual'

    if not root:
        steam = _steam_path()
        if steam:
            for lib in _libraries(steam):
                inst = ''
                try:
                    with open(os.path.join(lib, 'steamapps',
                                           'appmanifest_%s.acf' % MOVIE_APPID),
                              'r', encoding='utf-8', errors='replace') as f:
                        m = _ACF_DIR.search(f.read())
                    inst = m.group(1) if m else ''
                except OSError:
                    pass
                cand = os.path.join(lib, 'steamapps', 'common',
                                    inst or 'Assetto Corsa Competizione')
                if _valid_root(cand):
                    root, src = cand, 'steam'
                    break

    if not root:
        for drv in 'CDEFGHIJKLMNOPQRSTUVWXYZ':
            for rel in ('Steam\\steamapps\\common', 'SteamLibrary\\steamapps\\common',
                        'Games\\Steam\\steamapps\\common',
                        'Program Files (x86)\\Steam\\steamapps\\common'):
                cand = os.path.join('%s:\\' % drv, rel, 'Assetto Corsa Competizione')
                if _valid_root(cand):
                    root, src = cand, 'scan'
                    break
            if root:
                break

    if root and root != saved:
        cfg['root'] = root
        cfg['source'] = src
        _movie_cfg_save(cfg)
    MOVIE['cache'] = (root, src)
    MOVIE['cache_at'] = time.time()
    return root, src


def movie_locate(force=False):
    root, src = find_acc_root(force)
    info = {'found': bool(root), 'root': root, 'source': src, 'movie': '', 'tmp': '',
            'current_size': 0, 'backup_size': 0, 'backup_path': '',
            'payload_size': _size(MOVIE_PAYLOAD)}
    if root:
        path = os.path.join(root, MOVIE_REL)
        info['movie'] = path
        info['current_size'] = _size(path)
        info['backup_path'] = path + MOVIE_BAK
        info['backup_size'] = _size(path + MOVIE_BAK)
        info['tmp'] = path + MOVIE_TMP
    return info


def movie_state(info):
    """体积就足够判定：原片 87 MB vs 载荷 ~20 MB，差四倍以上，不用每次去哈希。

    'outdated' 是给「Apex 自己更新过」准备的：上一次装进去的载荷体积记在 movie.json 里，
    新版本换了片头之后，游戏目录里那个旧载荷既不是原厂也不是当前载荷，不能当成
    “文件被外部改动”来吓人，应当提示可以更新。
    """
    if not info['found']:
        return 'noacc'
    if not info['current_size']:
        return 'missing'
    if info['payload_size'] and info['current_size'] == info['payload_size']:
        return 'apex'
    cfg = _movie_cfg()
    old = int(cfg.get('payload_size') or 0)
    if old and info['current_size'] == old:
        # 用户自己匯入的片頭体积记在这里；那不是「过期」，是「目前生效的是你的影片」
        return 'apex' if cfg.get('imported') else 'outdated'
    if info['backup_size'] and info['current_size'] == info['backup_size']:
        return 'stock'
    if not info['backup_size'] and info['current_size'] == MOVIE_STOCK_SIZE:
        return 'stock'
    return 'foreign'


def _movie_fail(code):
    with MOVIE['lock']:
        MOVIE['job']['error'] = code
        MOVIE['job']['phase'] = 'error'


def _movie_copy(src, dst, phase, total):
    done = 0
    last = 0.0
    with open(src, 'rb') as fi, open(dst, 'wb') as fo:
        while True:
            buf = fi.read(MOVIE_CHUNK)
            if not buf:
                break
            fo.write(buf)
            done += len(buf)
            now = time.time()
            if now - last > 0.08:
                last = now
                with MOVIE['lock']:
                    MOVIE['job']['phase'] = phase
                    MOVIE['job']['done'] = done
                    MOVIE['job']['total'] = total
    return done


def _movie_replace(src, dst):
    # 游戏以 FILE_SHARE_READ 打开着影片时，读和写都能成功，只有 replace 会抛
    # OSError(32)；所以进程守卫之外，这一步还要自己重试几次。
    for i in range(6):
        try:
            os.replace(src, dst)
            return
        except OSError:
            if i == 5:
                raise
            time.sleep(0.2)


def _movie_worker(op, info):
    tgt = info['movie']
    bak = tgt + MOVIE_BAK
    tmp = tgt + MOVIE_TMP
    try:
        if op == 'apply':
            bsz = info['current_size']
            if not os.path.isfile(bak) and bsz > 0:
                _movie_copy(tgt, bak + MOVIE_TMP, 'backup', bsz)
                if _size(bak + MOVIE_TMP) != bsz:
                    raise RuntimeError('verify-failed')
                os.replace(bak + MOVIE_TMP, bak)
                log('开场影片已备份：%d B -> %s' % (bsz, bak))
            elif os.path.isfile(bak) and _size(bak) < (1 << 20):
                # 只可能是上次中途被打断留下的半个文件，绝不拿当前文件去覆盖它
                raise RuntimeError('backup-corrupt')
            elif bsz <= 0:
                log('原厂开场文件缺失，本次不做备份（可用 Steam 校验完整性恢复）')

            psz = info['payload_size']
            _movie_copy(MOVIE_PAYLOAD, tmp, 'copy', psz)
            if _size(tmp) != psz:
                raise RuntimeError('verify-failed')
            with MOVIE['lock']:
                MOVIE['job']['phase'] = 'commit'
            _movie_replace(tmp, tgt)
            if _size(tgt) != psz:
                raise RuntimeError('verify-failed')

            cfg = _movie_cfg()
            cfg.update(root=info['root'], source=info['source'], state='apex',
                       applied_at=round(time.time(), 1), payload_size=psz)
            _movie_cfg_save(cfg)
            log('已启用 Apex 开场动画（%d B）' % psz)
        else:
            bsz = info['backup_size']
            if not bsz:
                raise RuntimeError('no-backup')
            if info['current_size'] != bsz:
                _movie_copy(bak, tmp, 'restore', bsz)
                if _size(tmp) != bsz:
                    raise RuntimeError('verify-failed')
                with MOVIE['lock']:
                    MOVIE['job']['phase'] = 'commit'
                _movie_replace(tmp, tgt)
                if _size(tgt) != bsz:
                    raise RuntimeError('verify-failed')
                log('已还原原厂开场动画（%d B）' % bsz)
            cfg = _movie_cfg()
            cfg.update(state='stock', applied_at=0)
            _movie_cfg_save(cfg)

        with MOVIE['lock']:
            MOVIE['job'].update(phase='done', done=1, total=1)
    except RuntimeError as e:
        _movie_fail(str(e))
        log('开场影片未完成：%s' % e)
    except OSError as e:
        _movie_fail('file-locked' if getattr(e, 'errno', 0) in (13, 32) else 'io-error')
        log('开场影片 I/O 失败：%s' % e)
    finally:
        for p in (tmp, bak + MOVIE_TMP):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
        with MOVIE['lock']:
            MOVIE['job']['active'] = False
            MOVIE['job']['ended'] = time.time()
        MOVIE['cache_at'] = 0.0


# ---------------------------------------------------------------- 导入自备片头
# 用户手里的影片几乎不可能是 ACC 要的形状（1080p60 的 WMV2/WMAV2/ASF，长度还要跟原厂
# 一样）。所以导入时一律重编码：等比缩放到 1920x1080 加黑边、补/裁到 72.22 秒、短的用
# 最后一帧延展（不能留黑场），再走跟「启用」同一套备份与替换流程。

def _ffmpeg():
    """ffmpeg 的三种来源：随附、PATH、imageio_ffmpeg。找不到就返回空字符串。"""
    here = os.path.dirname(HERE)
    for p in (os.path.join(here, 'tools', 'ffmpeg', 'ffmpeg.exe'),
              os.path.join(HERE, 'ffmpeg', 'ffmpeg.exe')):
        if os.path.isfile(p):
            return p
    p = shutil.which('ffmpeg')
    if p:
        return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return ''


CREATE_NO_WINDOW = 0x08000000     # 后端跑在 pythonw 下，子进程不设这个就会闪黑窗


def _run_quiet(args, **kw):
    """跑一个外部程序，绝不弹控制台窗口。

    encoding/errors 一定要写死成 UTF-8 + replace：ffmpeg 的 stderr 里带着容器里的元数据
    （文件名可能是日文、中文），默认使用系统 ANSI（cp950）解码会在线程里抛
    UnicodeDecodeError，stderr 直接变空 —— 探测音轨就会「误判为没有音频」。"""
    kw.setdefault('creationflags', CREATE_NO_WINDOW)
    kw.setdefault('encoding', 'utf-8')
    kw.setdefault('errors', 'replace')
    return subprocess.run(args, **kw)


def _has_audio(exe, path):
    try:
        r = _run_quiet([exe, '-hide_banner', '-i', path], capture_output=True, text=True)
        return 'Audio:' in (r.stderr or '')
    except Exception:
        return False


PICK_SCRIPT = os.path.join(HERE, '_pick_video.ps1')
PICK_TIMEOUT = 300          # 5 分钟没选就自动放弃，别把 busy 卡死
PICK = {'proc': None}

PICK_PS = '''Add-Type -AssemblyName System.Windows.Forms
# 先宣告 per-monitor v2，再建立任何視窗：否則 125%/150% 縮放時整個對話框會被系統
# 點陣放大，文字發糊。舊系統沒有這個 API 就退回 SetProcessDPIAware()。
try {
  Add-Type -Namespace ApexDpi -Name Ctx -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr v);'
  if (-not [ApexDpi.Ctx]::SetProcessDpiAwarenessContext([IntPtr](-4))) { throw 'fallback' }
} catch {
  try {
    Add-Type -Namespace ApexDpi -Name Old -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
    [void][ApexDpi.Old]::SetProcessDPIAware()
  } catch { }
}
[System.Windows.Forms.Application]::EnableVisualStyles()
$top = New-Object System.Windows.Forms.Form
$top.TopMost = $true
$top.ShowInTaskbar = $false
$top.FormBorderStyle = 'None'
$top.StartPosition = 'Manual'
$top.Location = New-Object System.Drawing.Point(-3000, -3000)
$top.Size = New-Object System.Drawing.Size(1, 1)
$top.Show()
$d = New-Object System.Windows.Forms.OpenFileDialog
$d.Title = '選擇要當作開場的影片'
$d.Filter = '影片|*.mp4;*.mkv;*.mov;*.avi;*.m4v;*.webm;*.wmv;*.mpg;*.mpeg;*.ts;*.m2ts;*.flv|所有檔案|*.*'
$d.Multiselect = $false
if ($d.ShowDialog($top) -eq 'OK') { Write-Output $d.FileName }
$top.Close()
'''


def _pick_video():
    """原生选档对话框，跑在独立的 PowerShell 行程里。

    之前是在后端线程里直接调用 comdlg32.GetOpenFileNameW：没有 owner、没有 message pump，
    对话框会被 Apex 窗口盖住（用户看到的就是「按了没反应」），而且卡住之后 busy 永远不解除。
    独立行程 + TopMost 的隐形表单当 owner，对话框一定在最上层，而且随时可以砍掉。
    """
    try:
        if not os.path.isfile(PICK_SCRIPT):
            with open(PICK_SCRIPT, 'w', encoding='utf-8-sig') as f:
                f.write(PICK_PS)
        proc = subprocess.Popen(
            ['powershell.exe', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass',
             '-WindowStyle', 'Hidden', '-File', PICK_SCRIPT],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            creationflags=0x08000000)      # CREATE_NO_WINDOW：不闪黑窗
        PICK['proc'] = proc
        try:
            out, _ = proc.communicate(timeout=PICK_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            out = ''
        PICK['proc'] = None
        lines = [x.strip() for x in (out or '').splitlines() if x.strip()]
        return lines[0] if lines else ''
    except Exception as e:
        PICK['proc'] = None
        log('选档对话框失败：%s' % e)
        return ''


def _pick_cancel():
    p = PICK.get('proc')
    if p is not None:
        try:
            p.kill()
        except Exception:
            pass


def _probe_duration(exe, path):
    """秒数；读不出来就返回 0。"""
    try:
        r = _run_quiet([exe, '-hide_banner', '-i', path], capture_output=True, text=True)
        for line in (r.stderr or '').splitlines():
            if 'Duration:' in line:
                hms = line.split('Duration:')[1].split(',')[0].strip()
                h, m, s = hms.split(':')
                return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        pass
    return 0.0


CAPTION_TEXT = u'按任意鍵  ·  PRESS ANY KEY TO CONTINUE'


def _filter_path(path):
    """filtergraph 里 Windows 路径的 ':' 会被当成选项分隔符，必须转义。"""
    return path.replace(os.sep, '/').replace(':', chr(92) + ':')


def _caption_font():
    root = os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts')
    for f in ('msjh.ttc', 'msyh.ttc', 'seguisb.ttf'):
        p = os.path.join(root, f)
        if os.path.isfile(p):
            return _filter_path(p)
    return ''


def _convert(src, dst, seconds, on_progress, volume=1.0):
    """任何影片 -> WMV2/WMAV2/ASF, 1920x1080 60fps, 刚好 seconds 秒。

    比 seconds 长的裁掉。短的不会把最后一帧冻住：画面渐暗成卡片，上方浮出
    「按任意鍵 · PRESS ANY KEY TO CONTINUE」，带一点模糊地缓慢明暗，一直持续到影片结束。"""
    exe = _ffmpeg()
    if not exe:
        raise RuntimeError('no-ffmpeg')
    has_a = _has_audio(exe, src)
    dur = _probe_duration(exe, src)
    out_t = max(1.0, seconds - MOVIE_HOLD_TAIL)
    span = max(1.0, seconds) * 1e6
    base_vf = ('scale=1920:1080:force_original_aspect_ratio=decrease,'
               'pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,fps=60,setsar=1')
    cmd = [exe, '-y', '-hide_banner', '-loglevel', 'error', '-nostats', '-progress', 'pipe:1']
    short = 0.5 < dur < (seconds - 0.8)
    log('导入转换：来源 %.2f 秒，音频=%s，模式=%s' % (dur, '有' if has_a else '无',
                                              '卡片' if short else '裁切'))

    if short:
        # 用户影片比原厂短：正片结束后交叉溶接到一张设计好的卡片（深色底 + 薄荷光晕 +
        # 会呼吸的「按任意鍵 · PRESS ANY KEY TO CONTINUE」），一直循环到影片结束。
        # 卡片是预先渲染好的 2.6 秒循环（ui/media/card_loop.mp4），所以不需要在用户机器上
        # 用 drawtext 拼光晕 —— 那条路只能做出「四份副本」那种廉价的假发光。
        off = max(0.2, dur - 0.8)
        fc = ("[0:v]%s,fps=60,setsar=1[uv];"
              "[1:v]fps=60,scale=1920:1080,setsar=1[cv];"
              "[uv][cv]xfade=transition=fade:duration=0.8:offset=%.3f,format=yuv420p[v]"
              % (base_vf, off))
        cmd += ['-t', '%.3f' % dur, '-i', src, '-stream_loop', '-1', '-i', CARD_LOOP]
        if has_a:
            cmd += ['-map', '0:a:0', '-af', 'apad,volume=%.3f,alimiter=limit=0.95:level=false' % volume]
        else:
            cmd += ['-f', 'lavfi', '-t', '%.3f' % seconds, '-i', 'anullsrc=r=48000:cl=stereo',
                    '-map', '2:a:0']
        cmd += ['-filter_complex', fc, '-map', '[v]']
    else:
        # 比原厂长：裁掉多余部分，并在最后一秒把画面和声音一起淡出，不会硬切
        fade_st = max(0.2, out_t - 1.0)
        cmd += ['-t', '%.3f' % seconds, '-i', src]
        if has_a:
            cmd += ['-map', '0:v:0', '-map', '0:a:0',
                    '-af', 'apad,afade=t=out:st=%.3f:d=1.0,volume=%.3f,alimiter=limit=0.95:level=false'
                    % (fade_st, volume)]
        else:
            cmd += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
                    '-map', '0:v:0', '-map', '1:a:0']
        cmd += ['-vf', base_vf + ',tpad=stop_mode=clone:stop_duration=%.1f,'
                'fade=t=out:st=%.3f:d=1.0' % (seconds + 2.0, fade_st)]

    cmd += ['-c:v', 'wmv2', '-b:v', '9500k', '-g', '60', '-qmin', '1', '-qmax', '4',
            '-c:a', 'wmav2', '-b:a', '192k', '-ar', '48000', '-ac', '2',
            '-t', '%.3f' % out_t, '-f', 'asf', dst]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            creationflags=CREATE_NO_WINDOW)
    for line in proc.stdout:
        line = line.strip()
        if line.startswith('out_time_ms='):
            try:
                on_progress(min(0.98, float(line.split('=', 1)[1]) / span))
            except ValueError:
                pass
    err = (proc.stderr.read() or '')[-400:]
    if proc.wait() != 0:
        log('ffmpeg 转换失败：%s' % (err.strip().splitlines()[-1] if err.strip() else '?'))
        raise RuntimeError('convert-failed')
    if _size(dst) < (1 << 20):
        raise RuntimeError('convert-empty')


def _movie_import_worker(info, src):
    tgt = info['movie']
    bak = tgt + MOVIE_BAK
    tmp = tgt + MOVIE_TMP
    conv = tgt + '.apex.import'
    try:
        with MOVIE['lock']:
            MOVIE['job'].update(phase='convert', done=0, total=1, pct=0)
        _convert(src, conv, MOVIE_TARGET_SECONDS, _movie_progress,
                 volume=float(_movie_cfg().get('volume') or 1.0))
        with MOVIE['lock']:
            MOVIE['job']['phase'] = 'backup'
            MOVIE['job']['pct'] = 98

        bsz = info['current_size']
        if not os.path.isfile(bak) and bsz > 0:
            _movie_copy(tgt, bak + MOVIE_TMP, 'backup', bsz)
            if _size(bak + MOVIE_TMP) != bsz:
                raise RuntimeError('verify-failed')
            os.replace(bak + MOVIE_TMP, bak)
            log('已備份目前片頭：%d B' % bsz)

        psz = _size(conv)
        with MOVIE['lock']:
            MOVIE['job']['phase'] = 'commit'
            MOVIE['job']['pct'] = 99
        os.replace(conv, tmp)
        _movie_replace(tmp, tgt)
        if _size(tgt) != psz:
            raise RuntimeError('verify-failed')

        cfg = _movie_cfg()
        cfg.update(root=info['root'], source=info['source'], state='apex',
                   applied_at=round(time.time(), 1), payload_size=psz,
                   imported=os.path.basename(src))
        _movie_cfg_save(cfg)
        log('已匯入自訂開場：%s -> %d B' % (os.path.basename(src), psz))
        with MOVIE['lock']:
            MOVIE['job'].update(phase='done', done=1, total=1, pct=100)
    except RuntimeError as e:
        _movie_fail(str(e))
        log('匯入失敗：%s' % e)
    except OSError as e:
        _movie_fail('file-locked' if getattr(e, 'errno', 0) in (13, 32) else 'io-error')
        log('匯入 I/O 失敗：%s' % e)
    finally:
        for p in (tmp, conv, bak + MOVIE_TMP):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
        with MOVIE['lock']:
            MOVIE['job']['active'] = False
            MOVIE['job']['ended'] = time.time()
        MOVIE['cache_at'] = 0.0


def _movie_progress(p):
    with MOVIE['lock']:
        MOVIE['job']['pct'] = int(max(0, min(98, p * 98)))
        MOVIE['job']['done'] = MOVIE['job']['pct']
        MOVIE['job']['total'] = 100


def movie_volume(x):
    """改目前生效片頭的音量：影像直接 copy、只重編音軌，幾秒鐘的事。"""
    if not (MOVIE_VOL_MIN <= x <= MOVIE_VOL_MAX):
        return {'ok': False, 'error': 'bad-volume'}, 400
    with MOVIE['lock']:
        if MOVIE['job']['active']:
            return {'ok': False, 'error': 'busy'}, 409
    if game_pid():
        return {'ok': False, 'error': 'game-running'}, 409
    info = movie_locate(force=True)
    if not info['found'] or not info['current_size']:
        return {'ok': False, 'error': 'no-acc'}, 404
    tgt = info['movie']
    tmp = tgt + MOVIE_TMP
    exe = _ffmpeg()
    if not exe:
        return {'ok': False, 'error': 'no-ffmpeg'}, 400
    # 目前檔案裡已經烘進了上一次的音量，所以這次只套「相對增益」，否則每調一次就複利一次
    old = float(_movie_cfg().get('volume') or 1.0)
    gain = max(0.05, min(8.0, (x / old) if old > 0.05 else 1.0))
    cmd = [exe, '-y', '-hide_banner', '-loglevel', 'error',
           '-i', tgt, '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy',
           '-af', 'volume=%.3f,alimiter=limit=0.95:level=false' % gain,
           '-c:a', 'wmav2', '-b:a', '192k', '-ar', '48000', '-ac', '2',
           '-f', 'asf', tmp]
    r = _run_quiet(cmd, capture_output=True, text=True)
    if r.returncode != 0 or _size(tmp) < (1 << 20):
        try:
            os.remove(tmp)
        except OSError:
            pass
        return {'ok': False, 'error': 'convert-failed'}, 500
    try:
        _movie_replace(tmp, tgt)
    except OSError:
        return {'ok': False, 'error': 'file-locked'}, 409
    cfg = _movie_cfg()
    cfg.update(volume=x, payload_size=_size(tgt))
    _movie_cfg_save(cfg)
    log('片頭音量設為 %.0f%%（已重寫音軌）' % (x * 100))
    MOVIE['cache_at'] = 0.0
    return movie_status(), 200


def movie_import_begin():
    with MOVIE['lock']:
        if MOVIE['job']['active']:
            return {'ok': False, 'error': 'busy'}, 409
    if game_pid():
        return {'ok': False, 'error': 'game-running'}, 409
    if not _ffmpeg():
        return {'ok': False, 'error': 'no-ffmpeg'}, 400
    info = movie_locate(force=True)
    if not info['found']:
        return {'ok': False, 'error': 'no-acc'}, 404

    with MOVIE['lock']:
        MOVIE['job'].update(active=True, op='import', phase='pick', done=0, total=1,
                            pct=0, error='', started=time.time(), ended=0.0)

    def run():
        try:
            src = _pick_video()
            if not src:
                with MOVIE['lock']:
                    MOVIE['job'].update(active=False, phase='done', error='cancelled',
                                        pct=100, ended=time.time())
                return
            _movie_import_worker(info, src)
        except Exception as e:
            log('匯入執行緒異常：%s' % e)
            _movie_fail('io-error')
            with MOVIE['lock']:
                MOVIE['job']['active'] = False
                MOVIE['job']['ended'] = time.time()

    threading.Thread(target=run, daemon=True).start()
    return movie_status(), 200


def movie_import_cancel():
    with MOVIE['lock']:
        busy = MOVIE['job']['active'] and MOVIE['job']['op'] == 'import'
    if not busy:
        return {'ok': True, 'cancelled': False}
    _pick_cancel()
    return {'ok': True, 'cancelled': True}


def movie_begin(op):
    with MOVIE['lock']:
        if MOVIE['job']['active']:
            return {'ok': False, 'error': 'busy'}, 409
    if game_pid():
        return {'ok': False, 'error': 'game-running'}, 409

    info = movie_locate(force=True)
    if not info['found']:
        return {'ok': False, 'error': 'no-acc'}, 404
    if op == 'apply':
        if not info['payload_size']:
            return {'ok': False, 'error': 'no-payload'}, 404
        try:
            free = shutil.disk_usage(os.path.dirname(info['movie'])).free
        except OSError:
            free = 1 << 40
        if free < (info['payload_size'] + (32 << 20)):
            return {'ok': False, 'error': 'disk-full'}, 507
    elif not info['backup_size']:
        return {'ok': False, 'error': 'no-backup'}, 404

    with MOVIE['lock']:
        MOVIE['job'].update(active=True, op=op,
                            phase='backup' if op == 'apply' else 'restore',
                            done=0, total=0, pct=0, error='',
                            started=time.time(), ended=0.0)
    threading.Thread(target=_movie_worker, args=(op, info), daemon=True).start()
    return movie_status(), 200


def movie_status():
    info = movie_locate()
    with MOVIE['lock']:
        job = dict(MOVIE['job'])
    if job['total']:
        job['pct'] = max(0, min(100, int(job['done'] * 100 / job['total'])))
    else:
        job['pct'] = 100 if job['phase'] == 'done' else (0 if job['active'] else 100)

    # 上次进程被强杀留下的半截临时文件：没有任务在跑时顺手清掉
    if not job['active'] and info['found'] and info['tmp'] and os.path.exists(info['tmp']):
        try:
            os.remove(info['tmp'])
        except OSError:
            pass

    cfg = _movie_cfg()
    return {
        'ok': True,
        'acc': {'found': info['found'], 'root': info['root'], 'source': info['source'],
                'movie': info['movie']},
        'state': movie_state(info),
        'current': {'exists': bool(info['current_size']), 'size': info['current_size']},
        'backup': {'exists': bool(info['backup_size']), 'size': info['backup_size']},
        'payload': {'exists': bool(info['payload_size']), 'size': info['payload_size']},
        'running': bool(game_pid()),
        'applied_at': float(cfg.get('applied_at') or 0),
        'imported': str(cfg.get('imported') or ''),
        'volume': float(cfg.get('volume') or 1.0),
        'job': job,
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == '/hi':
                UI_INFO['v'] = q.get('v', [''])[0]
                UI_INFO['x'] = q.get('x', [''])[0]
                UI_INFO['at'] = time.time()
                UI_INFO.setdefault('hist', []).append('%s=%s' % (time.strftime('%H:%M:%S'), UI_INFO['x']))
                del UI_INFO['hist'][:-40]
                return self._send({'ok': True})
            if u.path == '/grip':
                x = float(q.get('x', ['1'])[0])
                GRIP.set_factor(x)          # 内部自己加锁，分步过渡
                with GRIP.lock:
                    return self._send(GRIP.status_locked())
            if u.path == '/damage':
                # A GET without ?on= is a read-only status poll. Defaulting the missing
                # parameter to "off" made the UI's 3-second poll disable the feature it
                # had just switched on.
                if 'on' in q:
                    on = q.get('on', ['0'])[0] in ('1', 'true', 'on')
                    if on:
                        UI_INFO['at'] = time.time()
                    return self._send({'ok': True, 'damage': GRIP.set_damage(on)})
                return self._send({'ok': True, 'damage': GRIP.damage_status()})
            if u.path == '/flash':
                global FLASH_ON, FLASH_LAST, FLASH_GAP, FLASH_ACTIVE
                global FLASH_MODE, FLASH_GAP_LIMIT, FLASH_FINISH_HOLD
                global FLASH_FINISH_UNTIL, FLASH_LAST_LAP, ANNOY_ON, ANNOY_PENDING_OFF
                if 'on' in q:
                    FLASH_ON = q.get('on', ['0'])[0] in ('1', 'true', 'on')
                    FLASH_LAST = 0.0
                    FLASH_GAP = None
                    FLASH_ACTIVE = 0
                    log('auto-flash %s' % ('on' if FLASH_ON else 'off'))
                if 'mode' in q:
                    mode = q.get('mode', ['gap'])[0]
                    if mode in ('gap', 'finish', 'both'):
                        FLASH_MODE = mode
                    FLASH_LAST_LAP = None
                    FLASH_FINISH_UNTIL = 0.0
                if 'gap' in q:
                    try:
                        FLASH_GAP_LIMIT = max(0.1, min(5.0, float(q.get('gap', ['1'])[0])))
                    except ValueError:
                        pass
                if 'finish' in q:
                    try:
                        FLASH_FINISH_HOLD = max(0.5, min(10.0, float(q.get('finish', ['2'])[0])))
                    except ValueError:
                        pass
                if 'annoy' in q:
                    was = ANNOY_ON
                    ANNOY_ON = q.get('annoy', ['0'])[0] in ('1', 'true', 'on')
                    ANNOY_PENDING_OFF = False
                    if was and not ANNOY_ON:
                        annoy_off()
                    log('rear-car annoy %s' % ('on' if ANNOY_ON else 'off'))
                return self._send({'ok': True, 'flash': flash_status()})
            if u.path == '/overlay/start':
                ok = start_overlay()
                return self._send({'ok': bool(ok), 'running': overlay_running()})
            if u.path == '/status':
                with GRIP.lock:
                    return self._send(GRIP.status_locked())
            if u.path == '/restore':
                GRIP.set_factor(1.0)
                with GRIP.lock:
                    n = GRIP.restore_locked()
                    GRIP.factor = 1.0
                    GRIP.target = 1.0
                    GRIP.save_factor()
                    log('恢复原厂：%d 条曲线' % n)
                    return self._send(dict(GRIP.status_locked(), restored=n))
            if u.path == '/rescan':
                threading.Thread(target=lambda: GRIP.locate(force=True), daemon=True).start()
                return self._send({'ok': True, 'locating': True})
            if u.path == '/movie':
                return self._send(movie_status())
            if u.path == '/movie/scan':
                root = q.get('root', [''])[0]
                find_acc_root(force=True, manual=root or None)
                return self._send(movie_status())
            if u.path == '/movie/apply':
                obj, code = movie_begin('apply')
                return self._send(obj, code)
            if u.path == '/movie/restore':
                obj, code = movie_begin('restore')
                return self._send(obj, code)
            if u.path == '/movie/import':
                obj, code = movie_import_begin()
                return self._send(obj, code)
            if u.path == '/movie/volume':
                try:
                    xv = float(q.get('x', ['1'])[0])
                except ValueError:
                    xv = 1.0
                obj, code = movie_volume(xv)
                return self._send(obj, code)
            if u.path == '/movie/import/cancel':
                return self._send(movie_import_cancel())
            if u.path == '/quit':
                FLASH_ON = False
                GRIP.set_factor(1.0)
                GRIP.restore_damage()
                with GRIP.lock:
                    GRIP.restore_locked()
                    GRIP.factor = 1.0
                    GRIP.target = 1.0
                    GRIP.save_factor()
                threading.Thread(target=lambda: (time.sleep(0.4), os._exit(0)), daemon=True).start()
                return self._send({'ok': True})
        except Exception as e:
            return self._send({'ok': False, 'error': str(e)}, 500)
        self._send({'ok': False, 'error': 'not-found'}, 404)

    def log_message(self, *a):
        pass

    def log_error(self, *a):
        # pythonw 下 sys.stderr 是 None，标准库默认的 log_error 会抛异常
        pass


def main():
    # 单实例：多个后端同时写同一批内存会互相打架，也是游戏卡死/崩溃的来源之一。
    # 互斥体随进程退出自动释放，不会有残留。
    k32.CreateMutexW(None, False, 'Local\\ApexGripBackend')
    if C.get_last_error() == 183:          # ERROR_ALREADY_EXISTS
        log('已有抓地力后端在运行，本实例退出')
        return
    try:
        srv = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    except OSError as e:
        log('端口 %d 被占用（多半是旧实例），本实例退出：%s' % (PORT, e))
        return
    GRIP.target = GRIP.load_factor()
    GRIP.factor = 1.0
    log('Apex 抓地力后端  http://127.0.0.1:%d  (记忆倍率 %.2fx)' % (PORT, GRIP.target))
    threading.Thread(target=boot, daemon=True).start()
    threading.Thread(target=pump_loop, daemon=True).start()
    threading.Thread(target=watcher, daemon=True).start()
    threading.Thread(target=damage_loop, daemon=True).start()
    threading.Thread(target=crash_loop, daemon=True).start()
    threading.Thread(target=flash_loop, daemon=True).start()
    threading.Thread(target=annoy_loop, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        with GRIP.lock:
            GRIP.restore_locked()
        log('已还原')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        log('fatal: %s' % traceback.format_exc())
        raise
