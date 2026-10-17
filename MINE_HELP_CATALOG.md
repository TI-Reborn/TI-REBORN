# Skill28 radio metadata and installed assets

`tools/verify_mine_help_catalog_native.py` executes the original catalogue
loader `0x9d61c0` against a bounded ElementTree-backed DOM. It accepts:

```xml
<skill id="28" name="Radio Help">
  <table>1</table>
  <value key="effectText" val="skill_help_desc" />
  <value key="operateType" val="OP_ACTIVE" />
  <value key="target" val="target_self" />
  <value key="apConsume" val="0" />
  <value key="castRange" val="0" />
  <value key="reuseTurns" val="0" />
</skill>
```

The resulting original record has ID28, level/count/value 1, active1, self
target0, AP/range/reuse0. An unknown target disables active use; a passive
descriptor stays inactive. Level/value/name and explicit zero metadata are
server policy; the original manual supplies anytime/no-AP help behavior.
The root grants `AbilityEntry(28,1,0,1)` in eligible mine battle views only.

No icon path is necessary. Original atlas initialization
`0xa6b6b6..0xa6b6ef` loads `base/pda/skills.png` as 32-pixel tiles from its
256×256 image. Original skill-bar draw `0x8ba4a0..0x8ba4f4` forwards skill ID28
directly as atlas index28 (crop128,96..160,128); that existing tile has visible
pixels. The ability icon uses the ID, rather than a descriptor image field.

Installed `animation.xml` maps Skill28 to `human_radio_use` for both human
models and `freakminer_radio_use_` for the miner. The matching original
`models/anim/*.adjx`, radio model/texture and radio OGG/XML sounds exist.
`english.lng` and `russian.lng` contain `skill_help_desc`. The installed
`base/shared config/skills.xml` currently omits28; runtime XML must add it.

Evidence: `evidence/mine_help_catalog_native.json` and earlier
`evidence/mine_help_native.json`. The installed files were only read. DOM/file
access, allocation/string ownership, generic string comparison and logging
are explicit stubs. The original loader and default-icon forwarding executed;
native XML tokenization, an on-screen button and hosted gameplay remain separate
integration checks. Neither the DLL nor hosted service was changed here.
