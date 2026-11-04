"""Start/reuse the loopback review service outside the invoking terminal job."""
from pathlib import Path
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
URL = 'http://127.0.0.1:8340/'


def available():
    try:
        with urllib.request.urlopen(URL, timeout=2) as response:
            return 'Astralogue · 剧情审核' in response.read(8192).decode('utf-8', errors='replace')
    except (OSError, ValueError):
        return False


def main():
    if not available():
        folder = ROOT/'data/audit'; folder.mkdir(parents=True, exist_ok=True)
        flags = 0
        if os.name == 'nt':
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_BREAKAWAY_FROM_JOB
        try:
            with (folder/'webui-service.log').open('ab') as log:
                subprocess.Popen([sys.executable, '-u', '-m', 'astralogue', 'audit', 'webui'], cwd=ROOT,
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=flags,
                                 start_new_session=os.name != 'nt')
        except OSError:
            print('无法创建独立后台进程。请在终端运行：python -m astralogue audit webui')
            return 1
        for _ in range(40):
            if available():break
            time.sleep(.25)
        else:
            print('审核服务启动失败，请查看 data/audit/webui-service.log（可能端口被占用）。')
            return 1
    if '--no-browser' not in sys.argv:
        webbrowser.open(URL)
    print('剧情审核管理器：'+URL+'（重复启动会复用已有服务）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
