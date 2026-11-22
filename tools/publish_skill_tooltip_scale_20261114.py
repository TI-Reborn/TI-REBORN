"""Publish the skill targeting balloon UI-scale fix (Hammer Slash tooltip at 125/150%).

The shared publisher passes its remote script on the ssh command line, which
Windows truncates at 32K characters. Upload the identical script to a private
temporary file first; payload, guards and atomic commit are unchanged.
"""
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_player_feedback_20261104 as publisher
from deploy.client_skill_tooltip_scale import patch, SOURCE_SHA

SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', 'tio']
_run = subprocess.run


def run_via_file(args, **kwargs):
    prefix = 'python3 -c '
    if args[:len(publisher.SSH)] != publisher.SSH or not args[-1].startswith(prefix):
        return _run(args, **kwargs)
    script = shlex.split(args[-1][len(prefix):])[0]
    staged = _run(SSH + ['f=$(mktemp /root/tio-publish-XXXXXX.py) && cat > "$f" && echo "$f"'],
                  input=script, capture_output=True, text=True, encoding='utf-8', timeout=60)
    if staged.returncode:
        raise RuntimeError('Could not stage the publication script')
    path = staged.stdout.strip()
    try:
        return _run(SSH + ['python3 ' + shlex.quote(path)], **kwargs)
    finally:
        _run(SSH + ['rm -f ' + shlex.quote(path)], capture_output=True, timeout=60)


if __name__ == '__main__':
    publisher.patch = patch
    publisher.SOURCE_SHA = SOURCE_SHA
    publisher.VERSION = '2026.11.14.2'
    publisher.OUT = ROOT/'reports/skill-tooltip-scale-20261114'
    publisher.subprocess.run = run_via_file
    publisher.main()
