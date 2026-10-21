#!/usr/bin/env python3
"""Build the public (read-only) edition of Apex.

The published build must not contain anything that scans or writes another process's memory,
so this script copies the tree and replaces the whole Grip class - scanner, curve writer,
damage repair, crash address discovery - with a stub that answers the panel's existing routes
without touching a single byte of the game.

    python tools/make_public.py [dest]

Default destination is ../Apex-lite next to this repository.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKIP_DIRS = {'.git', 'ffmpeg', '__pycache__'}
SKIP_FILES = {'movie.json', 'grip_curves.json', 'damage_cache.json', 'grip_factor.txt',
              'perf.json', 'apex_grip.log', '_pick_video.ps1', '_grip_start.log',
              '_doctor.log', 'make_public.py'}
SKIP_EXT = {'.log', '.pyc'}

STUB = '''class Grip:
    """Apex Lite: no process memory is read or written by this build.

    Every method below is a stub so the panel's existing routes still answer and the UI
    degrades to "not connected" instead of throwing. The scanner, the curve writer, the damage
    repair and the crash address discovery are not part of this edition.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.name = ''
        self.curves = []
        self.target = 1.0
        self.factor = 1.0
        self.locating = False
        self.note = ''
        self.stage = ''
        self.damage_on = False
        self.damage_note = ''

    def attach(self):
        return False

    def live(self):
        return False

    def locate(self, force=False):
        return False

    def set_factor(self, x):
        self.target = float(x)
        self.factor = float(x)
        return self.status_locked()

    def load_factor(self):
        return 1.0

    def save_factor(self):
        pass

    def pump(self):
        pass

    def restore_locked(self):
        return 0

    def set_damage(self, on):
        self.damage_on = bool(on)
        return False

    def restore_damage(self):
        return False

    def damage_status(self):
        return {'on': False, 'found': False, 'applied': False, 'refused': True}

    def scan_progress(self):
        return 0

    def scan_eta(self):
        return 0

    def status_locked(self):
        return {'ui': UI_INFO.get('v', ''), 'ui_x': UI_INFO.get('x', ''),
                'ui_hist': UI_INFO.get('hist', [])[-8:],
                'ok': False, 'x': 1.0, 'applied': 1.0, 'curves': 0, 'car': '',
                'live': False, 'locating': False, 'note': 'lite', 'stage': '',
                'progress': 0, 'eta': 0, 'damage': self.damage_status(), 'edition': 'lite'}


GRIP = Grip()


'''

LITE_CSS = """<style>
/* ---- Apex Lite ----
   The write cards (grip, engine power, fuel lock, tyre lock) and the collision-damage assist
   are not part of this edition. They are taken out of the grid flow rather than merely hidden,
   so the remaining cards fill the row instead of leaving two empty slots. Two columns, because
   only three cards are left, and the stint planner spans the full width. */
html.lite .card[data-risk]{display:none}
html.lite .grid{grid-template-columns:repeat(2,minmax(0,1fr))!important}
html.lite .card.plan{grid-column:span 2!important}
/* the collision-damage assist and the safety lock exist only to gate memory writes */
html.lite #damageBtn,html.lite #safeBtn,html.lite #safeSetBtn{display:none!important}
html.lite .grp:has(#setSafeH){display:none!important}
/* the 168 px action column held only the damage assist and the safety lock: with both gone it
   is dead space between the car card and the two toolbar icons, so drop the column itself */
html.lite .actCol{display:none!important}
/* "restore stock" only existed to put the grip curves back */
html.lite #restore{display:none!important}
/* the switcher only ever had AC-specific cards behind it, and the Lite host does not
   implement the game command at all */
html.lite #segGame,html.lite .sideLbl{display:none!important}
/* the permanent offline banner belongs to the memory-writing build; the legal text is still
   reachable from Settings -> About */
html.lite .warnStrip{display:none!important}
html.lite .topbar{gap:10px}
/* two cards per row, same height, note pinned to the bottom */
html.lite .lapCard,html.lite .tyreCard{display:flex;flex-direction:column}
html.lite .lapCard .legalNote,html.lite .tyreCard .legalNote{margin-top:auto}
</style>
</head>"""


LITE_LICENSE = """# Apex Lite — 使用授權條款

版本 2.0 · 2026-10-22 · 正體中文與英文並列，如有歧異以正體中文為準。

Copyright (c) 2026 Apex contributors.

**本版本不寫入、不注入、不修改遊戲進程的任何記憶體。**

## 一、授權範圍

在完全遵守本條款的前提下，作者授予您非專屬、不可轉讓的權利：檢視與研究原始碼、為個人非商業目的
編譯與執行、修改以符合個人需求、以未修改的完整形式再散布（須附本條款）。

## 二、使用限制

1. **僅限離線單機。** 不得在任何線上多人對局、線上伺服器或連線模式中使用。
2. 請遵守你所使用之賽事平台自身的規則；若該平台禁止第三方工具，請勿在該平台上使用本軟體。
3. 不得販售、不得用於商業產品或服務、不得收費。
4. 不得移除著作權、授權或免責聲明。

## 三、資料存取範圍

本軟體只做兩件事：讀取遊戲**公開的共享記憶體**（檔位、速度、油量、圈速、胎溫胎壓等儀表資料），
以及在使用者本機讀寫設定檔與片頭檔案。它**不開啟遊戲進程、不讀寫進程記憶體、不注入任何程式碼**。

## 四、隱私

不連網（除 127.0.0.1 上的本機服務）、不收集、不上傳任何資料；設定與日誌只留在本機。
「匯入我的影片」在你的電腦上以 FFmpeg 轉檔，檔案不會離開本機。

## 五、第三方元件與商標

Microsoft Edge WebView2 Runtime（不隨附）、FFmpeg（使用者自行下載，不隨附）、Windows 內建字型（不隨附）。
Assetto Corsa Competizione 為 Kunos Simulazioni / 505 Games 的商標；本軟體為非官方第三方工具，
與上述公司無任何隸屬、贊助或背書關係。

## 六、免責聲明

本軟體按「現狀」提供，不附任何明示或默示的保證。在任何情況下，作者均不就任何索賠、損害或其他
責任負責，無論係因合約、侵權或其他原因而生。

---

# Apex Lite Licence (English)

Version 2.0 · 2026-10-22. The Traditional Chinese text above prevails.

Copyright (c) 2026 Apex contributors.

**This edition is read-only: it never reads, writes or injects into another process's memory.**

Permission is granted, free of charge, for personal, non-commercial, offline use: study the source,
build and run it for yourself, modify it, and redistribute unmodified copies with this licence.

Restrictions: offline single-player only; no use in online multiplayer; respect the rules of
whatever platform you race on, and do not use the tool there if its rules forbid third-party
tools; no selling or commercial use; keep the notices intact.

Data access: the software reads the game's published shared memory (gear, speed, fuel, lap times,
tyre temperatures and pressures) and reads/writes local settings and movie files. It does not open
the game process, does not touch process memory and does not inject code.

Privacy: no network access beyond its own 127.0.0.1 services, no telemetry, no uploads. The video
import runs FFmpeg locally; nothing leaves the machine.

Third-party: WebView2 Runtime, FFmpeg and Windows fonts are not bundled. Assetto Corsa Competizione
is a trademark of Kunos Simulazioni / 505 Games; this is an unofficial tool with no affiliation.

Disclaimer: THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND. IN NO EVENT SHALL THE
AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY ARISING FROM THE SOFTWARE.
"""

LEGAL = {
    'zh-Hant': {
        'version': '2.0',
        'title': '使用授權與免責聲明',
        'updated': '2026-10-22',
        'intro': 'Apex Lite 只讀取遊戲公開的共享記憶體作為儀表資料，並在本機讀寫設定與片頭檔案；它不會寫入或修改遊戲。使用前請閱讀以下全部條款。',
        'sections': [
            {'title': '⚠ 僅限離線單機使用（請務必閱讀）',
             'body': '1. 本工具只讀取遊戲公開的共享記憶體（檔位、速度、油量、圈速、胎溫胎壓），不寫入任何遊戲狀態。\n2. 僅允許在單機 / 離線模式下使用。\n3. 嚴禁在任何線上多人對局、線上伺服器或連線模式中使用。\n4. 若無法接受上述任何一條，請立即停止使用並刪除本軟體。'},
            {'id': 'license', 'title': '一、軟體使用授權協議',
             'body': '1. 本軟體依隨附的 LICENSE 檔案（「Apex Lite 使用授權條款」）授權使用；如兩者解釋有歧異，以 LICENSE 為準。\n2. 可檢視與研究原始碼、為個人非商業目的編譯與執行、修改原始碼，並以未修改的完整形式再散布（須附本條款）。\n3. 不得販售、不得用於商業用途、不得收費。'},
            {'id': 'privacy', 'title': '二、隱私政策',
             'body': '1. 不蒐集、不儲存、不上傳任何個人資訊；不含遙測、統計或廣告元件。\n2. 除 127.0.0.1 上的本機服務外不連線網際網路。\n3. 設定與日誌只儲存在本機；「匯入我的影片」以 FFmpeg 在本機轉檔，檔案不會離開這台電腦。'},
            {'id': 'disclaimer', 'title': '三、免責聲明',
             'body': '1. 本軟體按「現狀」提供，不附帶任何明示或默示的擔保。\n2. 讀取共享記憶體本身不會改變遊戲狀態，但第三方疊加層仍可能被賽事平台視為違規，該風險與後果由您自行承擔。\n3. 因使用或無法使用本軟體所生之任何損害，作者不負任何責任。'},
            {'title': '四、非官方聲明',
             'body': '本軟體為非官方第三方工具，與 Kunos Simulazioni、Assetto Corsa、Assetto Corsa Competizione 及其任何關係企業、發行商、代理商均無任何關聯、贊助、背書或授權關係。所有遊戲名稱、商標與著作權均屬其各自所有人。'},
        ],
        'footer': '點擊「同意」表示您已閱讀、理解並自願接受上述全部條款；點擊「拒絕」將立即退出本軟體。',
        'agree': '同意', 'reject': '拒絕',
    },
    'zh-Hans': {
        'version': '2.0',
        'title': '使用授权与免责声明',
        'updated': '2026-10-22',
        'intro': 'Apex Lite 只读取游戏公开的共享内存作为仪表数据，并在本机读写设置与片头文件；它不会写入或修改游戏。使用前请阅读以下全部条款。',
        'sections': [
            {'title': '⚠ 仅限离线单机使用（请务必阅读）',
             'body': '1. 本工具只读取游戏公开的共享内存（档位、速度、油量、圈速、胎温胎压），不写入任何游戏状态。\n2. 仅允许在单机 / 离线模式下使用。\n3. 严禁在任何线上多人对局、线上服务器或连接模式中使用。\n4. 若无法接受上述任何一条，请立即停止使用并删除本软件。'},
            {'id': 'license', 'title': '一、软件使用授权协议',
             'body': '1. 本软件依随附的 LICENSE 文件（“Apex Lite 使用授权条款”）授权使用；如两者解释有歧异，以 LICENSE 为准。\n2. 可查看与研究源代码、为个人非商业目的编译与执行、修改源代码，并以未修改的完整形式再分发（须附本条款）。\n3. 不得贩售、不得用于商业用途、不得收费。'},
            {'id': 'privacy', 'title': '二、隐私政策',
             'body': '1. 不收集、不存储、不上传任何个人信息；不含遥测、统计或广告组件。\n2. 除 127.0.0.1 上的本机服务外不连接互联网。\n3. 设置与日志只存储在本机；“导入我的视频”以 FFmpeg 在本机转码，文件不会离开这台电脑。'},
            {'id': 'disclaimer', 'title': '三、免责声明',
             'body': '1. 本软件按“现状”提供，不附带任何明示或默示的担保。\n2. 读取共享内存本身不会改变游戏状态，但第三方叠加层仍可能被赛事平台视为违规，该风险与后果由您自行承担。\n3. 因使用或无法使用本软件所生之任何损害，作者不负任何责任。'},
            {'title': '四、非官方声明',
             'body': '本软件为非官方第三方工具，与 Kunos Simulazioni、Assetto Corsa、Assetto Corsa Competizione 及其任何关系企业、发行商、代理商均无任何关联、赞助、背书或授权关系。所有游戏名称、商标与著作权均属其各自所有人。'},
        ],
        'footer': '点击“同意”表示您已阅读、理解并自愿接受上述全部条款；点击“拒绝”将立即退出本软件。',
        'agree': '同意', 'reject': '拒绝',
    },
    'en': {
        'version': '2.0',
        'title': 'Licence and disclaimer',
        'updated': '2026-10-22',
        'intro': 'Apex Lite reads the game published shared memory for telemetry and keeps its settings and movie files on your machine; it does not write into or modify the game. Please read the terms below before using it.',
        'sections': [
            {'title': '⚠ Offline single-player only',
             'body': '1. The tool only reads the game published shared memory (gear, speed, fuel, lap times, tyre temperatures and pressures); it writes nothing into the game.\n2. Use it in single-player / offline mode only.\n3. Never use it in online multiplayer, on an online server, or in any connected session.\n4. If any of this is unacceptable, stop using it and delete the software.'},
            {'id': 'license', 'title': '1. Licence',
             'body': '1. The software is licensed under the bundled LICENSE file (Apex Lite Licence); that file prevails if the two differ.\n2. You may study the source, build and run it for personal non-commercial use, modify it, and redistribute unmodified copies with this licence.\n3. No selling, no commercial use, no charging for it.'},
            {'id': 'privacy', 'title': '2. Privacy',
             'body': '1. No personal data is collected, stored or uploaded; there is no telemetry, analytics or advertising.\n2. Nothing connects to the internet except this machine own services on 127.0.0.1.\n3. Settings and logs stay local; the video import runs FFmpeg on this machine and nothing leaves it.'},
            {'id': 'disclaimer', 'title': '3. Disclaimer',
             'body': '1. The software is provided as is, without warranty of any kind.\n2. Reading shared memory does not change the game state, but a competitive platform may still treat a third-party overlay as a violation; that risk and its consequences are yours.\n3. The authors are not liable for any damage arising from the use of, or inability to use, this software.'},
            {'title': '4. Unofficial',
             'body': 'This is an unofficial third-party tool with no affiliation, sponsorship, endorsement or authorisation from Kunos Simulazioni, Assetto Corsa or Assetto Corsa Competizione. All game names, trademarks and copyrights belong to their respective owners.'},
        ],
        'footer': 'Pressing Agree means you have read, understood and accepted these terms; pressing Decline exits the software immediately.',
        'agree': 'Agree', 'reject': 'Decline',
    },
}

THREADS = [
    "    threading.Thread(target=boot, daemon=True).start()\n",
    "    threading.Thread(target=pump_loop, daemon=True).start()\n",
    "    threading.Thread(target=watcher, daemon=True).start()\n",
    "    threading.Thread(target=damage_loop, daemon=True).start()\n",
    "    threading.Thread(target=crash_loop, daemon=True).start()\n",
]


def copy_tree(dst):
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel = os.path.relpath(base, ROOT)
        out = os.path.join(dst, rel) if rel != '.' else dst
        os.makedirs(out, exist_ok=True)
        for f in files:
            if f in SKIP_FILES or os.path.splitext(f)[1] in SKIP_EXT:
                continue
            shutil.copy2(os.path.join(base, f), os.path.join(out, f))


def patch_server(dst):
    p = os.path.join(dst, 'grip', 'apex_grip_server.py')
    src = open(p, encoding='utf-8').read()
    # keep the movie constants that sit between the class and MOVIE = {}, they are plain config
    src = src[:src.index('class Grip:')] + STUB + src[src.index("MOVIE_NAME = "):]
    for line in THREADS:
        src = src.replace(line, '')
    # drop the ctypes prototypes for the memory calls as well: no calls remain, and a public
    # build should not even advertise the capability
    # drop the ctypes prototypes for the memory calls as well: no calls remain, and a public
    # build should not even advertise the capability
    kept = [ln for ln in src.split(chr(10))
            if not (ln.startswith('k32.') and ('ProcessMemory' in ln or 'OpenProcess' in ln
                                               or 'VirtualQueryEx' in ln))]
    src = chr(10).join(kept)
    # dead weight from the removed scanner: the damage/curve signatures, the heap bounds it
    # searched and the structures only it used. The kernel32 block between them stays, the
    # shared-memory reads and the single-instance mutex still need it.
    def cut(text, start, end):
        i = text.find(start)
        j = text.find(end, i + 1) if i >= 0 else -1
        return text[:i] + text[j:] if (i >= 0 and j > i) else text

    src = cut(src, '# Collision-immunity defers repair', "k32 = C.WinDLL('kernel32'")
    src = cut(src, 'class MBI(C.Structure):', 'LOG_PATH = ')
    src = src.replace("    GRIP.target = GRIP.load_factor()\n", "    GRIP.target = 1.0\n")
    src = src.replace("log('Apex 抓地力后端  http://127.0.0.1:%d  (记忆倍率 %.2fx)' % (PORT, GRIP.target))",
                      "log('Apex Lite 后端  http://127.0.0.1:%d  (只读，不写游戏内存)' % PORT)")
    open(p, 'w', encoding='utf-8').write(src)


def patch_ui(dst):
    p = os.path.join(dst, 'ui', 'index.html')
    src = open(p, encoding='utf-8').read()
    src = src.replace('<html lang=', '<html class="lite" lang=', 1)
    extra = LITE_CSS
    src = src.replace('</head>', extra, 1)
    open(p, 'w', encoding='utf-8').write(src)


BANNER = {
    'disc.text': {
        'zh-Hant': '僅供離線單機使用。本工具不會修改遊戲的任何狀態；請遵守你所使用之賽事平台自身的規則。',
        'zh-Hans': '仅供离线单机使用。本工具不会修改游戏的任何状态；请遵守你所使用之赛事平台自身的规则。',
        'en': 'Offline single-player only. The tool changes nothing in the game; respect the rules of whatever platform you race on.',
    },
}



LITE_README = """# Apex Lite

Assetto Corsa Competizione 的儀表工具：HUD 疊加層、圈速、四輪胎況、賽段與加油計算，
再加上一支可替換成遊戲啟動片頭的影片工具。資料全部來自遊戲公開的共享記憶體（檔位、速度、油量、
圈速、胎溫胎壓），設定與片頭檔案則保存在你自己的電腦上。

介面是本機的 WebView2 面板（Apex.exe 只負責開視窗），實際工作由面板裡的 HTML/JS 與一個在
127.0.0.1:7798 監聽的小型 Python 服務（grip/apex_grip_server.py，負責找 ACC 安裝路徑、管理片頭檔案、
代理疊加層）完成。HUD 是另一個獨立程式 ApexOverlay.ps1（GDI+ 分層視窗，透過 127.0.0.1:7799 受面板控制）。

---

## 功能

| 功能 | 說明 |
|---|---|
| **HUD 疊加層** | S / M / L 三種尺寸、可鎖定、可隱藏；顯示檔位、速度、G 值、油量、單圈 |
| **圈速** | 當前圈（本地插值，逐幀走）、上一圈、最佳，Δ 上色，最近 10 圈折線 |
| **四輪胎況** | 四輪熱胎壓力（psi）與胎芯溫度（°C）即時顯示，溫度分級上色，另給溫差與平均胎壓 |
| **賽段與加油** | 讀單圈時間與每圈油耗，算出剩餘圈數與建議加油量 |
| **開場動畫** | 內建 1080p60 片頭，可一鍵換成 ACC 啟動片頭；原廠檔案自動備份，可還原 |
| **匯入自己的片頭** | 任何影片（mp4/mkv/mov/avi/webm/wmv 等）自動轉成 1080p60 WMV2，長度對齊原廠 72.22 秒 |
| **片頭音量** | 0–200 %，可用滑桿或滾輪（每格 1 %）調整；只重寫音軌、畫面不動 |
| **畫質選項** | 逐項開關：陰影、體積霧、螢幕空間反射、泛光、動態模糊、環境光遮蔽、抗鋸齒 |

## 範圍

只做儀表與呈現：讀取共享記憶體、畫 HUD、算賽段與加油、處理片頭影片。不會寫入遊戲的任何狀態。

## 需求

- Windows 10 / 11 x64
- **Microsoft Edge WebView2 Evergreen Runtime**（面板是 WebView2 宿主；缺少會白屏）
- **Python 3.8+**（本機後端）。找不到時可設環境變數 APEX_PY 指向 pythonw.exe
- Assetto Corsa Competizione（Steam 版會自動偵測；其他版本可在面板手動指定資料夾）
- FFmpeg：只有「匯入我的影片」需要，tools/get_ffmpeg.ps1 會自動下載到 tools/ffmpeg/（不隨附）

## 安裝

1. 把整個資料夾解壓到任意位置（路徑可含空格與中文）。
2. 第一次使用（或搬移過資料夾）雙擊 setup.cmd：
   - 註冊「Apex Grip Watchdog」排程工作（登入時 + 每 5 分鐘；只在後端沒回應時才啟動它）
   - 執行環境檢查，逐項列出 PASS / FAIL / INFO，結果存到 tools/_doctor.log
3. 之後照常用桌面「Apex」捷徑啟動（wscript，不會閃黑窗）。

## 授權

**Apex Lite Licence 2.0**（正體中文與英文並列）。重點：

- **僅限個人、非商業、離線單機使用**；請遵守你所使用之賽事平台自身的規則。
- 不會寫入遊戲記憶體、不注入、不修改遊戲狀態。
- 不連網、不收集、不上傳任何資料；設定與日誌只留在本機。

第三方程式與商標（WebView2、FFmpeg、Windows 字型、ACC 商標）見 THIRD-PARTY-NOTICES.md。
"""

BANNER_OLD = [
    # the title attribute carries the same sentence without the <b> wrapper
    ('僅供離線單機使用。本工具不會修改遊戲的任何狀態；請遵守你所使用之賽事平台自身的規則。',
     '僅供離線單機使用。嚴禁在 LFM、PITSKILL.IO、Hipole、TVRL、PXN Pers 聯賽、FullPush 等任何官方賽事平台使用；一經使用，後果自負。'),
    # the visible span carries a <b> around the first sentence
    ('<b>僅供離線單機使用。</b>本工具不會修改遊戲的任何狀態；請遵守你所使用之賽事平台自身的規則。',
     '<b>僅供離線單機使用。</b>嚴禁在 LFM、PITSKILL.IO、Hipole、TVRL、PXN Pers 聯賽、FullPush 等任何官方賽事平台使用；一經使用，後果自負。'),
    ('**僅供離線單機使用。**本工具不會修改遊戲的任何狀態；請遵守你所使用之賽事平台自身的規則。',
     '**僅供離線單機使用。**嚴禁在 LFM、PITSKILL.IO、Hipole、TVRL、PXN Pers 聯賽、FullPush 等任何官方賽事平台使用；一經使用，後果自負。'),
    ('**仅供离线单机使用。**本工具不会修改游戏的任何状态；请遵守你所使用之赛事平台自身的规则。',
     '**仅供离线单机使用。**严禁在 LFM、PITSKILL.IO、Hipole、TVRL、PXN Pers 联赛、FullPush 等任何官方赛事平台使用；一旦使用，后果自负。'),
    ('**Offline single-player only.** The tool changes nothing in the game; respect the rules of whatever platform you race on.',
     '**Offline single-player use only.** Forbidden on any official competition platform - LFM, PITSKILL.IO, Hipole, TVRL, PXN Pers, FullPush and the like. Use them and you carry the consequences.'),
]
SAFE_NOTE_OLD = [
    ('"safe.setNote":"鎖定時，會寫入遊戲記憶體的五個項目（下壓力、引擎馬力、油量、胎壓、碰撞無車損）將被停用；其餘功能不受影響。解鎖需先閱讀並同意授權聲明。狀態保存在本機，重啟後依然有效。"',
     '"safe.setNote":"本版本不含記憶體寫入功能，因此沒有安全鎖。"'),
    ('"safe.setNote":"锁定时，会写入游戏内存的五个项目（下压力、引擎马力、油量、胎压、碰撞无车损）将被停用；其余功能不受影响。解锁需先阅读并同意授权声明。状态保存在本机，重启后依然有效。"',
     '"safe.setNote":"本版本不含内存写入功能，因此没有安全锁。"'),
]


def patch_banner(dst):
    p = os.path.join(dst, 'ui', 'index.html')
    src = open(p, encoding='utf-8').read()
    for new, old in BANNER_OLD:
        src = src.replace(old, new)
    for old, new in SAFE_NOTE_OLD:
        src = src.replace(old, new)
    src = src.replace("The backend writes ACC's loaded realism damageRate directly in process memory. This is",
                      "This edition has no damage assist: nothing in it writes into the game. This")
    src = src.replace('\u552f\u8b80\u904a\u6232\u5171\u4eab\u8a18\u61b6\u9ad4', '\u53ea\u8b80\u53d6\u904a\u6232\u5171\u4eab\u8a18\u61b6\u9ad4')
    src = src.replace('\u53ea\u8bfb\u6e38\u620f\u5171\u4eab\u5185\u5b58', '\u53ea\u8bfb\u53d6\u6e38\u620f\u5171\u4eab\u5185\u5b58')
    # The lite host implements no status message at all, so the pill stayed on "scanning memory"
    # forever and the car/track row stayed empty even with the game running. The overlay's state
    # is the live source in this edition.
    _OLD = '    var state = "booting", tone = "idle", text = t("st.scan");'
    _NEW = (_OLD
            + chr(10) + '    /* Apex Lite: no host status exists, so every render derives the pill from the'
            + chr(10) + '       overlay state instead of waiting for a message that never arrives. */'
            + chr(10) + '    if (typeof OV !== "undefined" && OV){'
            + chr(10) + '      gotStatus = true;'
            + chr(10) + '      st.connected = !!(OV.state && OV.state.hasGame);'
            + chr(10) + '      st.state = st.connected ? "live" : "idle";'
            + chr(10) + '      if (OV.state){'
            + chr(10) + '        if (OV.state.car) st.car = OV.state.car;'
            + chr(10) + '        if (OV.state.track) st.track = OV.state.track;'
            + chr(10) + '      }'
            + chr(10) + '      setTimeout(render, 2500);'
            + chr(10) + '    }')
    src = src.replace(_OLD, _NEW)
    open(p, 'w', encoding='utf-8').write(src)



# The two editions must never share a port: the panel talks to whatever answers on 7798, so a
# running full backend makes the lite panel show its memory scanner and wait for it.
LITE_PORT = '7808'


def patch_port(dst):
    files = ['ui/index.html', 'ApexGrip-Stop.cmd', 'ApexLauncher.ps1', 'SETUP.txt', 'README.md',
             'tools/apex_doctor.ps1', 'tools/grip_watchdog.ps1', 'grip/apex_grip_server.py']
    for rel in files:
        p = os.path.join(dst, rel.replace('/', os.sep))
        if not os.path.isfile(p):
            continue
        t = open(p, encoding='utf-8', errors='replace').read()
        t = t.replace('127.0.0.1:7798', '127.0.0.1:' + LITE_PORT)
        t = t.replace("PORT = 7798", "PORT = int(%s)" % LITE_PORT)
        t = t.replace('-Port 7798', '-Port ' + LITE_PORT)
        t = t.replace(':7798', ':' + LITE_PORT)
        open(p, 'w', encoding='utf-8').write(t)


def patch_names(dst):
    ov = os.path.join(dst, 'ApexOverlay.ps1')
    if os.path.isfile(ov):
        t = open(ov, encoding='utf-8', errors='replace').read()
        t = t.replace("$StateDir  = Join-Path $env:LOCALAPPDATA 'Apex'",
                      "$StateDir  = Join-Path $env:LOCALAPPDATA 'Apex Lite'")
        open(ov, 'w', encoding='utf-8').write(t)
    srv = os.path.join(dst, 'grip', 'apex_grip_server.py')
    if os.path.isfile(srv):
        t = open(srv, encoding='utf-8', errors='replace').read()
        t = t.replace('ApexGripBackend', 'ApexLiteBackend')
        open(srv, 'w', encoding='utf-8').write(t)
    for name in ('install_watchdog.ps1', 'apex_doctor.ps1'):
        p = os.path.join(dst, 'tools', name)
        if os.path.isfile(p):
            t = open(p, encoding='utf-8', errors='replace').read()
            t = t.replace('Apex Grip Watchdog', 'Apex Lite Watchdog')
            open(p, 'w', encoding='utf-8').write(t)
    for name in ('SETUP.txt', 'README.md'):
        p = os.path.join(dst, name)
        if os.path.isfile(p):
            t = open(p, encoding='utf-8', errors='replace').read()
            t = t.replace('Apex Grip Watchdog', 'Apex Lite Watchdog')
            t = t.replace('%LOCALAPPDATA%\\Apex\\', '%LOCALAPPDATA%\\Apex Lite\\')
            open(p, 'w', encoding='utf-8').write(t)
    idx = os.path.join(dst, 'ui', 'index.html')
    if os.path.isfile(idx):
        t = open(idx, encoding='utf-8', errors='replace').read()
        t = t.replace('<title>Apex</title>', '<title>Apex Lite</title>')
        open(idx, 'w', encoding='utf-8').write(t)
    lg = os.path.join(dst, 'ui', 'legal.html')
    if os.path.isfile(lg):
        t = open(lg, encoding='utf-8', errors='replace').read()
        t = t.replace('%LOCALAPPDATA%\\Apex\\', '%LOCALAPPDATA%\\Apex Lite\\')
        open(lg, 'w', encoding='utf-8').write(t)


CSC = r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
HOST_SRC = os.path.join(HERE, 'apex_lite_host.cs')


def build_host(dst):
    """Compile the tiny WebView2 shell that replaces the full Apex host.

    The full host binary also contains the routines that rewrite tyre curves, torque, fuel,
    pressure and damage values. Shipping it - even with the controls hidden - would ship the
    capability, so the read-only edition gets its own host: a window, a WebView2, and an
    ignored message handler. 8 KB, no P/Invoke, no process access.
    """
    if not os.path.isfile(CSC) or not os.path.isfile(HOST_SRC):
        print('warning: csc.exe or host source missing, leaving the original Apex.exe in place')
        return
    exe = os.path.join(dst, 'Apex.exe')
    args = [CSC, '/nologo', '/target:winexe', '/platform:anycpu', '/optimize+',
            '/out:' + exe,
            '/r:System.dll', '/r:System.Drawing.dll', '/r:System.Windows.Forms.dll',
            '/r:' + os.path.join(dst, 'Microsoft.Web.WebView2.Core.dll'),
            '/r:' + os.path.join(dst, 'Microsoft.Web.WebView2.WinForms.dll'),
            HOST_SRC]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        print('host build failed:')
        print((r.stdout or '')[-1200:])
    else:
        print('host built: %.1f KB' % (os.path.getsize(exe) / 1024.0))


def patch_legal(dst):
    import json
    d = os.path.join(dst, 'ui', 'legal')
    if not os.path.isdir(d):
        return
    for code, doc in LEGAL.items():
        p = os.path.join(d, code + '.json')
        if os.path.isfile(p):
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(doc, f, ensure_ascii=False, indent=2)
    p = os.path.join(d, 'manifest.json')
    if os.path.isfile(p):
        try:
            m = json.load(open(p, encoding='utf-8'))
            if isinstance(m, dict):
                m['version'] = '2.0'
                m['updated'] = '2026-10-22'
                json.dump(m, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        except Exception:
            pass
    lic = os.path.join(dst, 'LICENSE')
    with open(lic, 'w', encoding='utf-8') as f:
        f.write(LITE_LICENSE)


def patch_docs(dst):
    # a generated README instead of patching the full one: the full text advertises features
    # this edition does not have, and a half-patched table reads worse than an honest rewrite
    open(os.path.join(dst, 'README.md'), 'w', encoding='utf-8').write(LITE_README)
    stop = os.path.join(dst, 'ApexGrip-Stop.cmd')
    if os.path.isfile(stop):
        t = open(stop, encoding='utf-8', errors='replace').read()
        t = t.replace('rem 停掉抓地力后端：先让它把轮胎曲线还原成原厂，再退出。',
                      'rem 停掉本機後端（片頭與疊加層控制都靠它）。')
        open(stop, 'w', encoding='utf-8').write(t)
    tpn = os.path.join(dst, 'THIRD-PARTY-NOTICES.md')
    if os.path.isfile(tpn):
        t = open(tpn, encoding='utf-8', errors='replace').read()
        # the grip-curve data file does not exist in this edition
        t = t.replace('- 輪胎曲線資料 `grip/grip_curves.json` 取自遊戲執行時讀出的資料，僅供本工具在本機使用。\n', '')
        open(tpn, 'w', encoding='utf-8').write(t)
    doc = os.path.join(dst, 'tools', 'apex_doctor.ps1')
    if os.path.isfile(doc):
        t = open(doc, encoding='utf-8', errors='replace').read()
        t = t.replace("'Grip backend'", "'Local backend'").replace('抓地力後端', '本機後端')
        open(doc, 'w', encoding='utf-8').write(t)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    inplace = '--inplace' in sys.argv
    dst = args[0] if args else os.path.join(os.path.dirname(ROOT), 'Apex-lite')
    # Windows keeps Apex.exe and the WebView2 DLLs locked while the app is open (OneDrive and
    # the antivirus can hold them too), and rmtree then fails halfway. --inplace overwrites
    # everything else and leaves the locked binaries alone, which is all a docs/UI change needs.
    if inplace:
        if not os.path.isdir(dst):
            os.makedirs(dst)
    else:
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        os.makedirs(dst)
    copy_tree(dst)
    if inplace:
        pass
    patch_server(dst)
    patch_ui(dst)
    patch_legal(dst)
    patch_banner(dst)
    patch_docs(dst)
    patch_names(dst)
    patch_port(dst)
    build_host(dst)
    r = subprocess.run([sys.executable, '-m', 'py_compile',
                        os.path.join(dst, 'grip', 'apex_grip_server.py')],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print('py_compile failed:')
        print((r.stderr or '')[-1500:])
        return 1
    shutil.rmtree(os.path.join(dst, 'grip', '__pycache__'), ignore_errors=True)
    print('built', dst)
    return 0


if __name__ == '__main__':
    sys.exit(main())
