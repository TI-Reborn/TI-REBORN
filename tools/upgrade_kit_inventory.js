// Ordinary legacy kits remain physical items in this emulator. This client
// explicitly hides template30 in two mercenary inventory panels. Clear the
// panel property, not the item predicate: drawing, layout and hit-testing all
// consult the same HideUpgradeBoxes byte. Exchange panels retain their policy.
for (const [address, panel] of [[0x9a7f41, 'squad_inventory'], [0x9ba222, 'inventory_window']]) {
  Interceptor.attach(silver.add(address - 0x400000), {
    onEnter() {
      const inventory = this.context.eax;
      inventory.add(0x2a2).writeU8(0);
      send({event: 'upgrade_kit_inventory_visible', panel, hide_upgrade_boxes: inventory.add(0x2a2).readU8()});
    }
  });
}
// Squad pages may be constructed before the ORANGE instrumentation is installed.
// AC4BD4 is the original pointer written by CreateSquadPage's inventory builder.
const existingKitInventory = silver.add(0xac4bd4 - 0x400000).readPointer();
if (!existingKitInventory.isNull()) {
  existingKitInventory.add(0x2a2).writeU8(0);
  send({event: 'upgrade_kit_inventory_visible', panel: 'existing_squad_inventory', hide_upgrade_boxes: 0});
}
