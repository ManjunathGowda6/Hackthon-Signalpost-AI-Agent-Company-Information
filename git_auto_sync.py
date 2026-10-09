import subprocess, sys, time, os, argparse
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(r"D:\Signalpost-AI-Agent-Company-Information")
REMOTE = "origin"
BRANCH = "main"
EMAIL = "manjunathd236@gmail.com"
USER = "ManjunathGowda6"
REPO = "https://github.com/ManjunathGowda6/Hackthon-Signalpost-AI-Agent-Company-Information.git"

def git(*a):
    return subprocess.run(["git"]+list(a), cwd=str(PROJECT_DIR), capture_output=True, text=True)

def setup():
    if not (PROJECT_DIR/".git").exists(): git("init"); git("branch","-M",BRANCH)
    git("config","user.email",EMAIL); git("config","user.name",USER)
    r = git("remote","get-url",REMOTE)
    if r.returncode != 0: git("remote","add",REMOTE,REPO)

def status():
    r = git("status","--porcelain")
    return [l for l in r.stdout.strip().split("\n") if l.strip()]

def sync(msg=None):
    ch = status()
    if not ch: print("Nothing to commit"); return
    git("add","-A")
    if not msg: msg = "Auto-sync [{}]: {} changes".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(ch))
    git("commit","-m",msg)
    r = git("push","-u",REMOTE,BRANCH)
    if r.returncode != 0: git("push","--set-upstream",REMOTE,BRANCH)
    h = git("rev-parse","HEAD")
    print("Pushed! Hash:", h.stdout.strip())

def watch(interval=30):
    print("Watching ({}s)... Ctrl+C to stop".format(interval))
    try:
        while True:
            if status(): print("Changes detected!"); sync()
            time.sleep(interval)
    except KeyboardInterrupt: print("Stopped.")

if __name__=="__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--once",action="store_true")
    p.add_argument("--status",action="store_true")
    p.add_argument("--interval",type=int,default=30)
    p.add_argument("-m","--message",default=None)
    a = p.parse_args()
    print("="*50+"\n  Signalpost Git Auto-Sync\n"+"="*50)
    setup()
    if a.status: print("\n".join(status()))
    elif a.once: sync(a.message)
    else: watch(a.interval)
