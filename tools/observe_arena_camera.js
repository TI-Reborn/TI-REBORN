// Read-only camera telemetry in the already-owned pinned QA client.
// No native calls, memory/global writes, sockets, protocol packets or UI inputs.
'use strict';
let initialized = false;
let base = null;
let listener = null;
let updates = 0;
let last = null;

function normalized(value) { return value.replace(/\\/g, '/').toLowerCase(); }
function at(va) { return base.add(va - 0x400000); }
function hex(pointer, length) {
  return Array.from(new Uint8Array(pointer.readByteArray(length)))
    .map(value => value.toString(16).padStart(2, '0')).join('');
}
function indirectS32(va) {
  const pointer = at(va).readPointer();
  if (pointer.isNull()) return null;
  const region = Process.findRangeByAddress(pointer);
  if (region === null || !region.protection.includes('r')) return null;
  return pointer.readS32();
}
function sample() {
  try {
    const cameraX = indirectS32(0x76e444);
    const cameraY = indirectS32(0x76e370);
    const width = indirectS32(0x76dcf8);
    const height = indirectS32(0x76dc08);
    return { updates, camera_pixel_x: cameraX, camera_pixel_y: cameraY,
      field_width: width, field_height: height, available: cameraX !== null && cameraY !== null };
  } catch (_) {
    return { updates, camera_pixel_x: null, camera_pixel_y: null,
      field_width: null, field_height: null, available: false };
  }
}
rpc.exports = {
  initialize(configuration) {
    if (initialized) throw new Error('Camera observer is already initialized');
    if (Process.arch !== 'ia32' || Process.id !== configuration.pid)
      throw new Error('Expected the already-owned x86 QA PID');
    if (normalized(Process.mainModule.path) !== normalized(configuration.executable))
      throw new Error('PID does not belong to the marked QA executable');
    base = Process.mainModule.base;
    if (!base.equals(ptr('0x400000'))) throw new Error('Unsupported relocated QA executable');
    for (const guard of configuration.guards) {
      if (hex(at(guard.va), guard.size) !== guard.bytes)
        throw new Error('Pinned camera function differs');
    }
    listener = Interceptor.attach(at(0x70c070), {
      onLeave() { updates += 1; last = sample(); },
    });
    initialized = true;
    last = sample();
    return { initialized: true, pid: Process.id, read_only: true };
  },
  snapshot() {
    if (!initialized) throw new Error('Camera observer is not initialized');
    return { ...sample(), last_camera_update: last };
  },
  release() {
    if (listener !== null) listener.detach();
    listener = null;
    initialized = false;
    return { released: true };
  },
};
