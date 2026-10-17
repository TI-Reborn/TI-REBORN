"""Create separate bridge static verifier for the frozen actual-mode0 client."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    text=(ROOT/'tools/verify_hosted_graphical_bridge_search_status.py').read_text(encoding='utf8')
    text=text.replace('client_arena_lobby_search_status as composer','client_arena_empty_roster_navigation as composer').replace('client-search-availability','client-empty-roster-navigation')
    text=text.replace("NEW='9d24b8f13a2c2a07c0673f8f9165b9df9f76a45eaa8561415606b3854ca86302'","NEW='8735e66a1495b124f935432bebaa413f94dbcc9d4f4f00cb502911656e3bbb0b'")
    text=text.replace('def sha(path):',"OLD.add('9d24b8f13a2c2a07c0673f8f9165b9df9f76a45eaa8561415606b3854ca86302')\ndef sha(path):")
    target=ROOT/'tools/verify_hosted_graphical_bridge_empty_roster.py'
    if target.exists():assert target.read_text(encoding='utf8')==text
    else:target.write_text(text,encoding='utf8')
if __name__=='__main__':main()
