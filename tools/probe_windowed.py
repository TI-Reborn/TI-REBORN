"""Run an owned diagnostic client with temporary windowed rendering settings."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path(r'C:\Program Files (x86)\TIOnline\base\config.cfg')

if __name__ == '__main__':
    original = CONFIG.read_bytes()
    if original.count(b'r_fullscreen 1') != 1:
        raise ValueError('Expected one fullscreen setting; config left unchanged')
    try:
        CONFIG.write_bytes(original.replace(b'r_fullscreen 1', b'r_fullscreen 0'))
        result = subprocess.run([sys.executable, str(ROOT / 'tools/probe_item_fixture.py'), *sys.argv[1:]], cwd=ROOT)
    finally:
        CONFIG.write_bytes(original)
    raise SystemExit(result.returncode)
