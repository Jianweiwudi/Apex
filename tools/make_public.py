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
              '_doctor.log'}
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
            if not (ln.startswith('k32.') and ('ProcessMemory' in ln or 'OpenProcess' in ln))]
    src = chr(10).join(kept)
    src = src.replace("    GRIP.target = GRIP.load_factor()\n", "    GRIP.target = 1.0\n")
    open(p, 'w', encoding='utf-8').write(src)


def patch_ui(dst):
    p = os.path.join(dst, 'ui', 'index.html')
    src = open(p, encoding='utf-8').read()
    src = src.replace('<html lang=', '<html class="lite" lang=', 1)
    extra = ('<style>/* Apex Lite: the memory-writing cards are not part of this edition */\n'
             'html.lite .card[data-risk]{display:none}\n'
             'html.lite #safeBtn{display:none}\n'
             '</style>\n</head>')
    src = src.replace('</head>', extra, 1)
    open(p, 'w', encoding='utf-8').write(src)


def patch_docs(dst):
    p = os.path.join(dst, 'README.md')
    src = open(p, encoding='utf-8').read()
    banner = ('> **Apex Lite.** This build does not read or write another process memory.\n'
              '> The grip multiplier, engine power, collision damage and tyre pressure lock\n'
              '> are not included. Everything else - HUD, stint planner, lap card, tyre\n'
              '> readout, startup movie, graphics options - is shared-memory reads or local\n'
              '> files only.\n\n')
    open(p, 'w', encoding='utf-8').write(banner + src)


def main():
    dst = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(ROOT), 'Apex-lite')
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    os.makedirs(dst)
    copy_tree(dst)
    patch_server(dst)
    patch_ui(dst)
    patch_docs(dst)
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
