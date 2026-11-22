# UI fonts: IBM Plex Sans Condensed with native metrics, Tektur titles (clients 2026.11.20.4 and .7)

## Problem
The Roboto density adapter (`deploy/client_ui_hd_fonts.py`) drew Roboto ink centred inside the
original pixel-font cells while ti.exe kept the original advances (`leading + width + trailing +
extra spacing` from `base/fonts/*.xml`). Narrow letters drifted apart, wide ones collided; the
original atlases also lack `–`, `«»`, `…`. Type reviews rate Roboto's Cyrillic as poor.

## Native facts (ti.exe)
- Text width: only `TI6fdcb4`; horizontal draw loop `TI6fcd84` (quad call `TI6fceba`). Both read
  glyph records at `font + 0x10c + cp*28` (top, x, y, width, height, leading, trailing), extra
  spacing `+0x1c032c`, space advance `+0x1c032d`, line height `+0x1c0328`.
- Pen: `+= kerning(prev, cur)`, `+= leading`, draw at pen, `+= width + trailing + extra`. A space
  without a record keeps `prev`, so kerning would apply across it.
- Kerning object `font + 0x108` is `TFontLetterGroups` (created in the font constructor); setter
  `Spec(EAX=self, EDX=code1, ECX=code2, [ESP+4]=shift)` at `TI6fc64c`, `ret 4`. The game never
  calls it, so stock kerning is empty. Codes above 0xFF go to its hash table.
- Font text is a WideString: the length prefix counts bytes.

## Change
- `tools/build_ui_font_metrics.py` rasterizes IBM Plex Sans (variable, `wdth 85`) per role, sized
  by the native cap height like the Roboto builder, with whole-pixel advances, ink offsets from the
  pen, GPOS pair kerning (`tools/font_kerning.py`), added marks and a transparent space record.
  Output: `reports/ui-fonts-plex-20261120/` (atlases `base/ui-hd/fonts/plexc-*.png`, licence).
- `deploy/client_ui_font_metrics.py` keeps the Roboto adapter code, repoints its nine headers to
  the Plex data in a region appended at Silver RVA `0x8eb000`, and replaces STARTUP's call to INIT
  with an entry that: returns at once when the launcher's interface flag (`Silver+0x89ff04`) is
  "original"; otherwise runs INIT and, once the adapter is installed, writes the advances (zero
  leading/trailing), zero extra spacing, space advance and all kerning pairs through `Spec`.
  Line heights and glyph tops stay native (layouts depend on them).

## Verification
- `tests/test_ui_font_metrics.py` (package), `tests/test_client_ui_font_metrics.py` (Unicorn:
  both interface modes, failed install, changed setter, single application, header data).
- Real ti.exe, isolated copy, no network (`work/ui-fonts-plex-20261120/probe_font_metrics.py`):
  native `TI6fdcb4` widths equal advances + kerning for 36/36 role/sample cases, incl. Cyrillic
  pairs and added marks; original mode leaves the adapter unstarted and draws stock pixel fonts.
- Launcher adapter regions: `require_compatible` passed. Published with
  `tools/publish_ui_fonts_plex_20261120.py` (backup `/root/tio-before-ui-fonts-plex-0am4yp43`).

## 2026.11.20.7: Tektur titles, shadow, density-exact placement
- Captions: `TGUIWindow.Paint` (Silver 0xa43774) draws `+0x5c` via Silver 0xc17400(selector 1,
  text, x = left + tile/2, white, y = top + 9). The menu interface handles its own frame there
  (swaps selector 3 for the menu font) and sends every other window to `jmp 0x4f29a8` at Silver
  0xc17458. That jump now goes through a swap of the selector-1 font index (`[[TI 0x76df40]]`)
  with a tenth font object loaded by TI add_font (TI6fecc8) from `base/fonts/pixel.xml/png`, so
  captions keep the native line and baseline. The adapter's font count 9 sits in four
  immediates (Silver RVA 0x82e13f, 0x82ef91, 0x82efb1, 0x82f694); all are 10 now.
- Atlases carry a 1 px black shadow (alpha 0.75): glyph colour multiplies RGB, black stays black.
- Glyph boxes are the union of the glyph's extent at all four densities; each density cell is
  exactly box*scale with its own raster at its own position. Rounding the ink offset at 100 % and
  scaling it misplaced ink by up to a scaled pixel per letter (visible as "З вук" at 150 %).
- Real client (isolated copy, no network): 40/40 native widths match, Settings window caption in
  Tektur; original mode loads no title font and draws stock fonts. Published with
  `tools/publish_ui_fonts_titles_20261120.py` (backup `/root/tio-before-ui-fonts-titles-i90bcfno`).

## 2026.11.20.11: main-menu title centred
The menu interface draws the main-menu title at window top + 0x16 (Silver 0xc17439). In the
"new" interface a stub adds 18 logical px (measured at 150 %: rail ends at 369, first button at
445, title cap centre now 405). The original interface keeps 0x16. Published with
`tools/publish_ui_menu_title_20261120.py` (backup `/root/tio-before-ui-menu-title-drofl7xd`).

## Not done yet
Unified login-window face (the Inter login module was never published); logged-in windows
(shop, warehouse, tooltips) not checked with real accounts.
