import subprocess, sys, time, os, argparse
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(r'D:\Signalpost-AI-Agent-Company-Information')
REMOTE = 'origin'
BRANCH = 'main'
EMAIL = 'manjunathd236@gmail.com'
USER = 'ManjunathGowda6'
REPO = 'https://github.com/ManjunathGowda6/Hackthon-Signalpost-AI-Agent-Company-Information.git'
IGNORE = {'.git', '__pycache__', '.pyc', '.env', 'data', '.mypy_cache', '.pytest_cache'}


def git(*args):
    return subprocess.run(['git'] + list(args), cwd=str(PROJECT_DIR), capture_output=True, text=True)


def setup():
    if not (PROJECT_DIR / '.git').exists():
        git('init')
        git('branch', '-M', BRANCH)
    git('config', 'user.email', EMAIL)
    git('config', 'user.name', USER)
    r = git('remote', 'get-url', REMOTE)
    if r.returncode != 0:
        git('remote', 'add', REMOTE, REPO)
    print(f'[OK] Git configured: {USER} -> {REPO}')


def get_changes():
    r = git('status', '--porcelain')
    return [l for l in r.stdout.strip().split(chr(10)) if l.strip()]


def sync(msg=None):
    changes = get_changes()
    if not changes:
        print('[--] Nothing to commit')
        return False
    git('add', '-A')
    if not msg:
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        msg = f'Auto-sync [{ts}]: {len(changes)} file(s) changed'
    r = git('commit', '-m', msg)
    if r.returncode != 0:
        if 'nothing to commit' in r.stdout:
            return False
        print(f'[!!] Commit error: {r.stderr.strip()}')
        return False
    print(f'[OK] Committed: {msg}')
    r = git('push', '-u', REMOTE, BRANCH)
    if r.returncode != 0:
        r = git('push', '--set-upstream', REMOTE, BRANCH)
        if r.returncode != 0:
            print(f'[!!] Push failed: {r.stderr.strip()}')
            return False
    h = git('rev-parse', '--short', 'HEAD')
    print(f'[OK] Pushed! ({h.stdout.strip()})')
    return True


def should_ignore(path):
    parts = Path(path).parts
    for p in IGNORE:
        if p in parts or str(path).endswith(p):
            return True
    return False


def watch_instant():
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        print('[!!] watchdog not installed: pip install watchdog')
        watch_poll()
        return

    class Handler(FileSystemEventHandler):
        def __init__(self):
            self._last = 0

        def on_any_event(self, event):
            if should_ignore(event.src_path):
                return
            if event.event_type not in ('created', 'modified', 'deleted', 'moved'):
                return
            now = time.time()
            if now - self._last < 2:
                return
            self._last = now
            time.sleep(0.5)
            fname = os.path.basename(event.src_path)
            print(f'\n[!!] Change: {fname}')
            sync()

    observer = Observer()
    observer.schedule(Handler(), str(PROJECT_DIR), recursive=True)
    observer.start()
    print('[>>] Watching... instant push on every change (Ctrl+C to stop)\n')
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        observer.join()
        print('\n[OK] Stopped.')


def watch_poll():
    print('[>>] Polling every 5s... (Ctrl+C to stop)')
    try:
        while True:
            if get_changes():
                sync()
            time.sleep(5)
    except KeyboardInterrupt:
        print('[OK] Stopped.')


def main():
    p = argparse.ArgumentParser(description='Signalpost Git Auto-Sync (Instant)')
    p.add_argument('--once', action='store_true', help='One-time commit & push')
    p.add_argument('--status', action='store_true', help='Show git status')
    p.add_argument('-m', '--message', default=None, help='Custom commit message')
    a = p.parse_args()
    print('=' * 50)
    print('  Signalpost Git Auto-Sync')
    print('  Mode: ' + ('ONE-TIME' if a.once or a.status else 'INSTANT WATCH'))
    print('=' * 50)
    setup()
    print()
    if a.status:
        changes = get_changes()
        if changes:
            for c in changes:
                print(f'  {c}')
        else:
            print('  Working tree clean.')
    elif a.once:
        sync(a.message)
    else:
        sync()
        watch_instant()


if __name__ == '__main__':
    main()
