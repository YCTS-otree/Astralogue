"""Location-independent launcher, preserving the caller's terminal / PTY handles."""
import json
import os
from pathlib import Path
import runpy
import sys


def main():
    root = Path(os.environ.get('ASTRALOGUE_HOME') or Path(__file__).resolve().parents[1]).resolve()
    if not (root/'src/astralogue/__main__.py').is_file():
        raise SystemExit('Astralogue source not found; check ASTRALOGUE_HOME.')
    os.chdir(root)
    sys.path.insert(0,str(root/'src'))
    # No subprocess pipes, captured password input or terminal emulation: native
    # stdin/stdout remain attached to the host's persistent PTY / console.
    args=sys.argv[1:]
    if not args or args==['--debug']:
        config=root/'data/launcher.json'
        if os.environ.get('ASTRALOGUE_PACK'):
            pack=Path(os.environ['ASTRALOGUE_PACK'])
        elif config.exists():
            pack=Path(json.loads(config.read_text(encoding='utf8'))['pack'])
        else:
            candidates=['data/packs/prologue-exploration-v112.storypack','data/packs/prologue-player.storypack']
            pack=next((Path(p) for p in candidates if Path(p).is_file()),Path(candidates[-1]))
            # Pin the pack once, so app updates cannot silently rebind accounts.
            if pack.is_file():
                config.parent.mkdir(parents=True,exist_ok=True)
                with config.open('x',encoding='utf8') as f:json.dump({'pack':pack.as_posix()},f)
        args=['start','--pack',str(pack),*args]
    sys.argv=['astralogue',*args]
    runpy.run_module('astralogue',run_name='__main__')


if __name__=='__main__':main()
