"""Verify all four hosted mine bands using disposable excluded TLS clients."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import verify_mine_spawn_exit_hosted_20261117 as verification


def main() -> None:
    for name, cases, stats in (
            ('lower', ((4, 13), (7, 14)), ((128, 150), (180, 249))),
            ('upper', ((14, 15), (16, 16)), ((200, 249), (240, 300)))):
        verification.OUT = ROOT / 'reports/mine-armor-balance-20261117' / name
        verification.OUT.mkdir(parents=True, exist_ok=True)
        verification.PRIVATE = ROOT / f'.secrets/mine-armor-balance-{name}-20261117.json'
        verification.main(cases=cases, mob_stats=stats)


if __name__ == '__main__':
    main()
