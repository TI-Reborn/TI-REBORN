// The Hospital is created before connectloopback installs compatibility hooks.
// Initialize its shared tariff now, and keep both price calculations in sync
// with the server even when an existing window is merely shown again.
function installTreatmentTariff() {
  const settings = silver.add(0xac5ac0 - 0x400000).readPointer();
  if (!settings.isNull() && settings.readFloat() !== LOCAL_TREATMENT_RATE) {
    settings.writeFloat(LOCAL_TREATMENT_RATE);
  }
}
// Whole function entries only: Hospital painter and post-battle total helper.
// Never intercept interior CALL/PUSH instructions in the original client.
for (const address of [0x8c8d0c, 0x8c8b30]) {
  const entry = silver.add(address - 0x400000);
  if (entry.readU8() !== 0x55 || entry.add(1).readU16() !== 0xec8b) {
    throw Error('Unrecognized treatment price function');
  }
  Interceptor.attach(entry, {onEnter: installTreatmentTariff});
}
installTreatmentTariff();
