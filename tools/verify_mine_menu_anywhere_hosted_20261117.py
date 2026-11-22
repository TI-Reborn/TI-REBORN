"""Confirm existing menu exits away from the lift without a living raider."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import verify_mine_spawn_exit_hosted_20261117 as verification


def main() -> None:
    for name, amounts in (('defeat', (99, 199)), ('victory', (100, 200))):
        verification.OUT = ROOT / 'reports/mine-menu-anywhere-20261117' / name
        verification.OUT.mkdir(parents=True, exist_ok=True)
        verification.PRIVATE = ROOT / f'.secrets/mine-menu-anywhere-{name}-20261117.json'
        verification.main(cases=((4, 13), (14, 15)),
                          quit_away_from_exit=True, drill_crystals=amounts)


if __name__ == '__main__':
    main()
