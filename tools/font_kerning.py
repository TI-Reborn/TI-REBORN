"""GPOS pair kerning ('kern' feature, PairPos formats 1 and 2) from a font's default master."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "reports/ui-hd-assets/fonts/_validation-deps"))
from fontTools.ttLib import TTFont  # noqa: E402


class Kerning:
    """Pair adjustments in font units; the first subtable that covers a pair wins."""

    def __init__(self, path: Path):
        # Variable-font kerning deltas are ignored: the UI uses fixed instances close to the default master.
        with TTFont(str(path), lazy=False) as font:
            self.units_per_em = font["head"].unitsPerEm
            self.cmap = dict(font.getBestCmap())
            self._lookups = []
            if "GPOS" in font:
                gpos = font["GPOS"].table
                indices = sorted({index for record in gpos.FeatureList.FeatureRecord
                                  if record.FeatureTag == "kern" for index in record.Feature.LookupListIndex})
                for index in indices:
                    lookup = gpos.LookupList.Lookup[index]
                    tables = []
                    for subtable in lookup.SubTable:
                        subtable = getattr(subtable, "ExtSubTable", subtable)
                        if getattr(subtable, "LookupType", lookup.LookupType) == 2:
                            tables.append(_PairTable(subtable))
                    self._lookups.append(tables)

    @lru_cache(maxsize=None)
    def units(self, first: int, second: int) -> int:
        """Lookups add up; inside one lookup the first subtable that covers the pair decides."""
        a, b = self.cmap.get(first), self.cmap.get(second)
        if a is None or b is None:
            return 0
        total = 0
        for tables in self._lookups:
            for table in tables:
                value = table.lookup(a, b)
                if value is not None:
                    total += value
                    break
        return total

    def pixels(self, first: int, second: int, size: int) -> int:
        return round(self.units(first, second) * size / self.units_per_em)


class _PairTable:
    def __init__(self, subtable):
        self.format = subtable.Format
        self.coverage = {glyph: i for i, glyph in enumerate(subtable.Coverage.glyphs)}
        if self.format == 1:
            self.pairs = [{record.SecondGlyph: getattr(record.Value1, "XAdvance", 0) or 0
                           for record in pair_set.PairValueRecord} for pair_set in subtable.PairSet]
        else:
            self.class1 = subtable.ClassDef1.classDefs
            self.class2 = subtable.ClassDef2.classDefs
            self.matrix = [[getattr(record.Value1, "XAdvance", 0) or 0 for record in row.Class2Record]
                           for row in subtable.Class1Record]

    def lookup(self, first: str, second: str) -> int | None:
        index = self.coverage.get(first)
        if index is None:
            return None
        if self.format == 1:
            return self.pairs[index].get(second)
        # A covered pair in a class table is decided here, even when the value is zero.
        return self.matrix[self.class1.get(first, 0)][self.class2.get(second, 0)]
