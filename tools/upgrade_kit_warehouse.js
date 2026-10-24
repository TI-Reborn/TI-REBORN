// The warehouse manager has a separate, unconditional template30 exclusion in
// both CheckItemForFilters and ResortOutputList. Remove only that exclusion;
// keep accumulated search/category/ownership results and all later filters.
// Original bytes are checked before either write. Process memory only.
{
  const sites = [0x9159f7, 0x9171b2].map(address => silver.add(address - 0x400000));
  const bytesAt = p => Array.from(new Uint8Array(p.readByteArray(2)));
  for (const p of sites) {
    const b = bytesAt(p);
    if (!((b[0] === 0x33 && b[1] === 0xdb) || (b[0] === 0x90 && b[1] === 0x90))) {
      throw new Error('Unrecognized Upgrade Kit warehouse filter at ' + p);
    }
  }
  for (const p of sites) {
    Memory.patchCode(p, 2, writable => writable.writeByteArray([0x90, 0x90]));
  }
  send({event: 'upgrade_kit_warehouse_filter_enabled', sites: sites.map(p => ({address: p.toString(), bytes: bytesAt(p)}))});
}
