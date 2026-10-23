'use strict';

// Observation only: no NativeFunction calls, memory writes, input or packets.
let initialized = false, silver = null, configuration = null;
let drawEntries = 0, drawReturns = 0, clickEntries = 0, nativeClickEntries = 0;
let cityEntries = 0, tooltipCalls = 0, spriteCalls = 0, travelCalls = 0;
let latest = null, wanted = null, errorCount = 0;
let samplerEnds = 0, lastSamplerRestore = null;
const travels = [], tooltips = [], errors = [], listeners = [];
function norm(s) { return String(s).replace(/\\/g, '/').toLowerCase(); }
function at(va) { return silver.base.add(va - 0x400000); }
function rva(value) { return silver.base.add(value); }
function event(name, data) { send(Object.assign({event: name}, data)); }
function signed16(value) { const n = value & 0xffff; return n >= 0x8000 ? n - 0x10000 : n; }
function equal(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
function hex(address, length) {
  return Array.from(new Uint8Array(address.readByteArray(length)), b => b.toString(16).padStart(2, '0')).join('');
}
function bounded(list, row) { list.push(row); if (list.length > 80) list.shift(); }
function recordError(kind) {
  errorCount++; bounded(errors, {kind, drawReturns});
  event('global_map_observer_error', {kind, errorCount});
}
function state() {
  const p = rva(configuration.state_rva), result = {};
  for (const name of Object.keys(configuration.fields)) {
    const value = p.add(configuration.fields[name]);
    result[name] = name === 'old_table' ? value.readPointer().toString() : value.readS32();
  }
  return result;
}
function textures() {
  const rows = [];
  for (let i = 0; i < configuration.resources.length; i++) {
    const p = rva(configuration.rows_rva + i * configuration.row_stride);
    rows.push({id: p.add(12).readU32(), resource: configuration.resources[i].path,
      pointer: p.readPointer().toString(), loaded: !p.readPointer().isNull(),
      width: p.add(8).readU16(), height: p.add(10).readU16(),
      worldSize1024: p.add(16).readU32()});
  }
  return {count: rows.length, loaded: rows.filter(r => r.loaded).length, rows};
}
function filtering() {
  const definition = configuration.filtering;
  if (!definition) return null;
  const p = rva(definition.state_rva), result = {};
  for (const name of Object.keys(definition.state_fields)) {
    const address = p.add(definition.state_fields[name]);
    result[name] = ['ti_base', 'iat_old', 'iat_slot', 'sampler'].includes(name)
      ? address.readPointer().toString() : address.readU32();
  }
  const slot = ptr(result.iat_slot || 0), sampler = ptr(result.sampler || 0);
  result.iatPointerRestored = !slot.isNull() && slot.readPointer().equals(ptr(result.iat_old || 0));
  if (!sampler.isNull()) {
    result.currentSamplerCache = {mag: sampler.add(0x68).readU32(), min: sampler.add(0x88).readU32(),
      mip: sampler.add(0xa8).readU32()};
  }
  result.expectedObjectMipCalls = 22;
  result.allObjectMipLoadsObserved = result.mip_calls === 22 && result.load_scopes === 22
    && result.iat_restores === 22 && result.scope_active === 0 && result.protect_failures === 0;
  result.samplerEnds = samplerEnds;
  result.lastSamplerRestore = lastSamplerRestore;
  return result;
}
function towns() {
  const table = at(configuration.original_table_va).readPointer();
  if (table.isNull()) return {pointer: table.toString(), count: 0, rows: [], valid: false};
  const count = table.sub(4).readS32();
  if (count < 0 || count > 64) throw new Error('Invalid native table length');
  const rows = [];
  for (let i = 0; i < count; i++) {
    const p = table.add(4 * i).readPointer();
    if (p.isNull()) throw new Error('Null town entry');
    const bounds = [0x210, 0x214, 0x218, 0x21c].map(o => p.add(o).readS32());
    const id = p.add(8).readU8();
    const authority = configuration.authority.find(row => row.id === id);
    rows.push({id, pointer: p.toString(), enabled: p.add(4).readU8() !== 0, bounds,
      matchesAuthority: !!authority && equal(bounds, authority.bounds),
      authorityEnabled: authority ? authority.enabled : null,
      cache: {load234: p.add(0x234).readU8(), load235: p.add(0x235).readU8(),
        load236: p.add(0x236).readU8(), requestTTL: p.add(0x250).readU32()}});
  }
  return {pointer: table.toString(), count, rows,
    valid: count === configuration.authority.length && rows.every(r => r.matchesAuthority)
      && new Set(rows.map(r => r.id)).size === count};
}
function geometry(table) {
  return {pointer: table.pointer, count: table.count,
    rows: table.rows.map(r => ({id: r.id, pointer: r.pointer, enabled: r.enabled, bounds: r.bounds}))};
}
function camera() {
  return {xBits: at(0xb749ec).readU32(), yBits: at(0xb749f0).readU32(),
    x: at(0xb749ec).readFloat(), y: at(0xb749f0).readFloat()};
}
function character() {
  const p = at(0xac5b7c).readPointer();
  if (p.isNull()) return null;
  return {world: [p.add(0x0c).readS32(), p.add(0x10).readS32()],
    destination: [p.add(0x14).readS32(), p.add(0x18).readS32()],
    renderBits: [p.add(0x1c).readU32(), p.add(0x20).readU32()],
    render: [p.add(0x1c).readFloat(), p.add(0x20).readFloat()],
    movement: p.add(0x224).readS32(), currentTown: at(0xac5d58).readPointer().readS32()};
}
function safeData() {
  try { return {state: state(), textures: textures(), filtering: filtering()}; }
  catch (_) { recordError('state_or_texture_read'); return null; }
}
function status() {
  return {initialized, drawEntries, drawReturns, clickEntries, nativeClickEntries,
    cityEntries, tooltipCalls, spriteCalls, travelCalls, latest, travels, tooltips,
    errors, errorCount, current: initialized ? safeData() : null,
    observationOnly: true, gameplayMutations: 0};
}
function executable(address) {
  const range = Process.findRangeByAddress(address);
  if (!range || range.protection.indexOf('x') < 0) throw new Error('Observer hook is not executable');
}
function hook(va, callbacks) {
  const address = at(va); executable(address);
  listeners.push(Interceptor.attach(address, callbacks));
}
function mouse() {
  return [at(0xac5b70).readPointer().readS32(), at(0xac5a04).readPointer().readS32()];
}
function tooltip(kind, context) {
  try {
    const table = at(configuration.original_table_va).readPointer();
    const count = table.sub(4).readS32(), index = context.ecx.toUInt32();
    if (count < 0 || count > 64 || index >= count) throw new Error('Invalid hovered index');
    const town = table.add(index * 4).readPointer();
    tooltipCalls++;
    bounded(tooltips, {kind, id: town.add(8).readU8(), index, drawEntries, mouse: mouse()});
  } catch (_) { recordError('tooltip_read'); }
}
rpc.exports = {
  initialize(config) {
    if (initialized || Process.arch !== 'ia32' || Process.mainModule.base.toUInt32() !== 0x400000)
      throw new Error('Unexpected owned TI architecture/base');
    if (norm(Process.mainModule.path) !== norm(config.executable)) throw new Error('Foreign game process');
    silver = Process.getModuleByName('silver.dll');
    if (norm(silver.path) !== norm(config.silver_path)) throw new Error('Foreign Silver module');
    configuration = config;
    if (rva(config.signature_rva).readUtf8String() !== config.signature)
      throw new Error('Reviewed global-map extension absent');
    if (typeof config.code_guard_hex !== 'string' || !/^[a-f0-9]+$/.test(config.code_guard_hex)
        || config.code_guard_hex.length % 2 !== 0 || config.code_guard_hex.length > 131072
        || hex(rva(config.code_guard_rva), config.code_guard_hex.length / 2) !== config.code_guard_hex)
      throw new Error('Exact reconstructed live map code differs');
    for (const guard of config.additional_code_guards || []) {
      if (typeof guard.hex !== 'string' || !/^[a-f0-9]+$/.test(guard.hex) || guard.hex.length % 2 !== 0
          || guard.hex.length > 131072 || hex(rva(guard.rva), guard.hex.length / 2) !== guard.hex)
        throw new Error('Exact scoped native visual code differs');
    }
    if (config.resources.length !== 23 || config.authority.length !== 22
        || config.row_stride !== 32 || config.original_table_va !== 0xb749e4
        || config.native_travel_va !== 0x889e5c || config.original_click_va !== 0x9ee684)
      throw new Error('Native observer contract differs');
    for (let i = 0; i < config.resources.length; i++) {
      const p = rva(config.rows_rva + i * config.row_stride);
      const name = rva(p.add(20).readU32());
      if (p.add(12).readU32() !== config.resources[i].id || name.readUtf16String() !== config.resources[i].path)
        throw new Error('Exact live map resource identity differs');
    }
    // Both entry hooks must still point to the exact mapped custom routines.
    for (const row of [[0x9ee150, config.draw_va], [config.original_click_va, config.click_va]]) {
      const p = at(row[0]);
      if (p.readU8() !== 0xe9 || !p.add(5 + p.add(1).readS32()).equals(at(row[1])))
        throw new Error('Native map jump guard differs');
    }
    hook(config.draw_va, {
      onEnter() {
        drawEntries++; this.updateOnly = (this.context.eax.toUInt32() & 1) !== 0;
        this.quads = []; this.spriteStart = spriteCalls;
        try { this.before = towns(); } catch (_) { recordError('draw_enter_table_read'); }
      },
      onLeave() {
        drawReturns++;
        if (this.updateOnly) return;
        try {
          const after = towns(), fields = state(), tex = textures();
          const p = rva(config.state_rva), cam = camera(), actor = character();
          latest = {drawEntries, drawReturns, table: after, state: fields, textures: tex, filtering: filtering(),
            originalTableRestored: !!this.before && equal(geometry(this.before), geometry(after)),
            savedTableRestored: after.pointer === fields.old_table,
            authorityGeometryPreserved: after.valid,
            cameraRestored: cam.xBits === p.add(config.fields.old_x).readU32()
              && cam.yBits === p.add(config.fields.old_y).readU32(),
            avatarRenderRestored: actor !== null && actor.renderBits[0] === p.add(config.fields.old_avx).readU32()
              && actor.renderBits[1] === p.add(config.fields.old_avy).readU32(),
            camera: cam, character: actor, spriteCallsThisDraw: spriteCalls - this.spriteStart};
          const label = wanted;
          if (drawReturns === 1 || label !== null) {
            wanted = null; event('global_map_native_snapshot', Object.assign({label: label || 'first-draw'}, latest));
          }
        } catch (_) { recordError('draw_return_snapshot'); }
      }
    });
    hook(config.original_click_va, {onEnter() { nativeClickEntries++; }});
    hook(config.click_va, {onEnter() { clickEntries++; }});
    hook(config.native_travel_va, {
      onEnter() {
        try {
          travelCalls++;
          const x = signed16(this.context.eax.toUInt32()), y = this.context.edx.toInt32();
          const hits = config.authority.filter(r => r.enabled && x >= r.bounds[0] && y >= r.bounds[1]
            && x <= r.bounds[2] && y <= r.bounds[3]).map(r => r.id);
          const row = {sequence: travelCalls, x, y, inWorld: x >= -512 && x <= 511 && y >= -512 && y <= 511,
            mouse: mouse(), state: state(), locationIds: hits, clickEntries, nativeClickEntries};
          bounded(travels, row); event('global_map_native_travel', row);
        } catch (_) { recordError('travel_read'); }
      }
    });
    hook(0x8596e0, {onEnter() { cityEntries++; event('global_map_native_city_entry', {cityEntries, clickEntries}); }});
    hook(0x9e8e70, {onEnter() { tooltip('base', this.context); }});
    hook(0x9e8374, {onEnter() { tooltip('town', this.context); }});
    hook(0x4f2910, {
      onEnter() {
        const p = this.context.eax;
        const delta = p.sub(rva(config.rows_rva)).toInt32();
        if (delta >= 0 && delta < 23 * config.row_stride && delta % config.row_stride === 0) spriteCalls++;
      }
    });
    if (config.filtering) hook(config.filtering.sampler_end_va, {
      onLeave() {
        try {
          const value = filtering();
          samplerEnds++;
          const actual = value.currentSamplerCache;
          lastSamplerRestore = {sequence: samplerEnds, samplerActive: value.sampler_active,
            actual, saved: {mag: value.old_mag, min: value.old_min, mip: value.old_mip},
            restored: !!actual && value.sampler_active === 0 && actual.mag === value.old_mag
              && actual.min === value.old_min && actual.mip === value.old_mip};
        } catch (_) { recordError('sampler_restore_read'); }
      }
    });
    initialized = true;
    event('global_map_observer_installed', {pid: Process.id, observationOnly: true, resourceCount: 23, authorityCount: 22});
    return {initialized: true, observationOnly: true};
  },
  status() { return status(); },
  snapshot(label) {
    if (!initialized || typeof label !== 'string' || label.length > 80 || !/^[A-Za-z0-9 _.-]+$/.test(label))
      throw new Error('Invalid nonpersonal snapshot label');
    wanted = label;
    return {queued: true, atNextDrawReturn: true};
  }
};
