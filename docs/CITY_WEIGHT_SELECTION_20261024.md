# Stable city and mercenary-selection weight

The first recovery-weight fix paired city PetInfo66 with status4E attributes7
(capacity) and6 (carried weight). Its TCP tests used one fighter per account.
They checked correct numbers on the wire, but missed cross-fighter UI effects.

Read-only observation of a running published client confirmed that the selected
fighter retained mass136 in its native model while another fighter's capacity
update redrew the shared scale using that other fighter's mass0. The same scale
is used in the warehouse and the mercenary-selection dialog before mine entry.

In the original status handler, attribute7 stores capacity and unconditionally
calls the scale update at `8c7c71`. Attribute6 uses the selection check at
`8c7bb6..8c7bca` in city/selection mode. It therefore updates a foreign model
without replacing the selected fighter's scale. The existing scale routines
and both branches are unchanged in the inspected published client.

City weight follow-ups now contain only attribute6. PetInfo66 continues to carry
the authoritative capacity derived from level, equipped items and abilities.
Equipment changes already send a freshly projected PetInfo; no capacity rule
or client binary changes. Battle updates still include both attributes because
their capacity may change without a city profile. No stored inventory/profile,
database schema or user data is rewritten.

`tests/test_recovery_weight_display.py` now provisions two fighters in each of
two accounts, including empty squadmates. It checks repeated healing and changed
inventories over real TCP, and rejects redundant capacity commands for both
profile and inventory follow-ups. Large totals retain their u32 status update;
the profile's u16 field does not truncate the displayed total.

`python tools/verify_city_weight_selection_native.py` executes the original
status handlers for both selected slots. The former packets reproduce an
unselected fighter's scale redraw; the corrected packets redraw only the
selected fighter. Lookup/GUI calls are stubbed and captured, so this is native
code validation, not a claim of graphical gameplay acceptance. The script uses
the existing version-bound Unicorn/PE research helpers and is outside portable
CI; it adds no server runtime dependency.

The broader historical `test_weight` suite requires the unbundled research file
`evidence/items_diagnostic_provenance.json`. That provenance test cannot run from
the server handoff alone; the other seven weight tests can run independently.
