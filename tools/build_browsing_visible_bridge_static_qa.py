"""Create a new revision of the offline bridge verifier; preserve prior reports."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'tools/verify_hosted_graphical_bridge_empty_roster.py').read_text(encoding='utf8')
source=source.replace('client_arena_empty_roster_navigation','client_arena_browsing_visible').replace('client-empty-roster-navigation','client-main-list-visibility')
source=source.replace("NEW='8735e66a1495b124f935432bebaa413f94dbcc9d4f4f00cb502911656e3bbb0b'","NEW='e1d9435a8521881a6559dd3d724d9f5ca865a7aaa72d1707cf1669adaa3a4d80'")
source=source.replace('def sha(path):',"OLD.add('8735e66a1495b124f935432bebaa413f94dbcc9d4f4f00cb502911656e3bbb0b')\ndef sha(path):")
(ROOT/'tools/verify_hosted_graphical_bridge_browsing_visible.py').write_text(source,encoding='utf8')
