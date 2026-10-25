"""One parsed copy of the client item catalogue (evidence/items_diagnostic.xml).

The catalogue is static for a server process: it is part of rules_digest, and a
change requires a restart without active battles. Parsing it costs ~5 ms, and
it used to be parsed again for every combat, battle equip, shop and rental tax
check while the hub lock was held. Callers must treat the tree as read-only.
"""
from functools import lru_cache
from pathlib import Path
import xml.etree.ElementTree as ET

PATH = Path(__file__).resolve().parents[1]/'evidence/items_diagnostic.xml'


@lru_cache(maxsize=1)
def items_root():
    return ET.parse(PATH).getroot()
