// Dedicated QA authentication only: real ORANGE sockets and native SILVER
// readers/builders. No protocol injection, result replacement or packet logging.
'use strict';

const EXPECTED_HOST = '127.0.0.1';
let EXPECTED_SESSION_PORT = null;
let qaLoginPort = null;
let qaGate = null;
let qaBlocked = null;
let ownedExit = null;
let moduleBase = null;
let credentials = null;
let initialized = false;
let listParsing = false;
let listRows = [];
let nativeConnect = null;
let nativeSelect = null;
let nativeShowAuthorization = null;
let autoSelect = false;
let persistentHeap = null;
let persistentAllocate = null;
let ownedLogin = null;
let characterSelectCode = null;
const state = {
  connected: false, authChallengeStatus: null, credentialsSubmitted: false,
  loginStatus: null, serverListLoaded: false, serverRows: [],
  selectedServer: null, serverLoginStatus: null, gameAuth1Status: null,
  gameAuth2Status: null, authenticated: false, fault: null,
  charactersLoaded: false, characters: [], selectedCharacter: null,
  characterSelectStatus: null, worldStartSent: false,
};

function emit(event, extra = {}) { send({ event, ...extra }); }
function failClosed(reason) {
  state.fault = reason;
  if (qaGate) qaGate.writeU8(0);
  emit('bridge_fault', { reason, owned_process_terminated: true });
  // initialize has already pinned this process path and all native entries.
  // Returning from an onEnter hook does NOT skip the native builder.
  // Exit the own QA process before original code can send stored credentials.
  if (!ownedExit) throw new Error('Owned process termination is unavailable');
  ownedExit(0x5141);
  throw new Error('Owned process did not terminate');
}
function at(va) { return moduleBase.add(va - 0x400000); }
function normalizedPath(value) { return value.replace(/\\/g, '/').toLowerCase(); }
function startGenuineHostedConnection(showProgress) {
  if (!initialized || state.connected || state.fault || !qaGate || qaGate.readU8() !== 0) throw new Error('Connect is not available');
  state.connected = true;
  qaGate.writeU8(1);
  emit('owned_qa_gate_armed');
  if (showProgress) {
    // The unchanged 15-byte callback opens the already-created registered
    // window_autorization. It contains the original spinner and localized
    // m568/m569 instructions. No state/status or network result is fabricated.
    nativeShowAuthorization();
    emit('native_authorization_wait_shown');
  }
  nativeConnect(Memory.allocUtf8String(EXPECTED_HOST), qaLoginPort, ptr(0), 0);
  emit('native_hosted_connect_started', { host: EXPECTED_HOST, port: qaLoginPort });
  return { started: true, host: EXPECTED_HOST, port: qaLoginPort, native_progress: showProgress };
}
function hex(pointer, length) {
  return Array.from(new Uint8Array(pointer.readByteArray(length)))
    .map(value => value.toString(16).padStart(2, '0')).join('');
}
function relocatedEntry(guard) {
  const bytes = guard.entry12.match(/../g).map(value => parseInt(value, 16));
  const delta = moduleBase.toUInt32() - 0x400000;
  for (const offset of guard.entry_relocations || []) {
    const original = (bytes[offset] | bytes[offset + 1] << 8 |
      bytes[offset + 2] << 16 | bytes[offset + 3] << 24) >>> 0;
    const relocated = (original + delta) >>> 0;
    for (let i = 0; i < 4; i++) bytes[offset + i] = (relocated >>> (i * 8)) & 255;
  }
  return bytes.map(value => value.toString(16).padStart(2, '0')).join('');
}
function delphiString(value) {
  // SILVER may retain these immutable (refcount -1) strings. Allocate from the
  // own process's heap so they stay valid after Frida/helper release. The OS
  // reclaims both small buffers when this dedicated QA process closes.
  const storage = persistentAllocate(persistentHeap, 0, 12 + (value.length + 1) * 2);
  if (storage.isNull()) throw new Error('Native QA credential allocation failed');
  storage.writeU16(1200); storage.add(2).writeU16(2);
  storage.add(4).writeS32(-1); storage.add(8).writeU32(value.length);
  storage.add(12).writeUtf16String(value);
  return storage;
}
function guardedSelection() {
  if (state.fault || !state.connected || !state.credentialsSubmitted || state.loginStatus !== 0) return failClosed('Server selection lacks owned login');
  if (!state.serverListLoaded) throw new Error('Actual native server list has not loaded');
  if (state.selectedServer !== null) throw new Error('Server selection already submitted');
  const rows = state.serverRows.filter(row =>
    row.host === EXPECTED_HOST && row.port === EXPECTED_SESSION_PORT && row.id === 1);
  if (rows.length !== 1) throw new Error('Expected exactly one observed hosted server row');
  const row = rows[0];
  const control = at(0xacdda0).readPointer();
  if (control.isNull()) throw new Error('Native server-list control is absent');
  // Established by evidence/server_login_original.asm: the original callback
  // reads this selected index, retrieves that native row and sends server login.
  control.add(0x280).writeS32(row.index);
  state.selectedServer = { index: row.index, id: row.id, host: row.host, port: row.port };
  emit('native_server_selection', state.selectedServer);
  nativeSelect();
  return { ...state.selectedServer };
}
function statusHook(va, key, event) {
  Interceptor.attach(at(va), {
    onEnter() { this.status = this.context.eax.readU8(); },
    onLeave() {
      state[key] = this.status;
      if (key === 'gameAuth2Status') {
        state.authenticated = !state.fault && state.connected && state.credentialsSubmitted && state.authChallengeStatus === 0 &&
          this.status === 0 && state.loginStatus === 0 && state.serverLoginStatus === 0 && state.gameAuth1Status === 0;
      }
      emit(event, { status: this.status });
      if (this.status === 0 && (!state.connected || !state.credentialsSubmitted || state.fault)) failClosed('Native success arrived without owned credentials');
    },
  });
}

function selectOwnedCharacter(count) {
  if (state.fault || !state.authenticated || count !== 1 || state.selectedCharacter !== null)
    throw new Error('Expected one character after genuine successful QA authentication');
  const table = at(0xac618c).readPointer();
  if (table.isNull()) throw new Error('Native character table is absent');
  const actor = table.readPointer();
  if (actor.isNull()) throw new Error('Native character record is absent');
  const namePointer = actor.add(0x5ff4).readPointer();
  const name = namePointer.isNull() ? '' : namePointer.readUtf16String();
  const row = { index: 0, id: actor.add(0x28).readU32(),
    unselectable: actor.add(0x60e8).readU8(), name };
  if (name !== ownedLogin || row.id !== 1 || row.unselectable !== 0)
    throw new Error('Observed character is not the expected selectable owned QA character');
  state.charactersLoaded = true;
  state.characters = [row];
  if (!autoSelect) { emit('native_owned_character_observed', {index:row.index,id:row.id}); return; }
  state.selectedCharacter = { ...row };
  emit('native_owned_character_selection', {index:row.index,id:row.id});
  // Original Delphi callback uses EAX=observed slot, EDX=null character password.
  // It performs selection and sends native17; successful native17 sends19 itself.
  characterSelectCode = Memory.alloc(Process.pageSize);
  const target = at(0x8a3108).toUInt32();
  const bytes = [0x31, 0xc0, 0x31, 0xd2, 0xb9];
  for (let i = 0; i < 4; i++) bytes.push((target >>> (i * 8)) & 255);
  bytes.push(0xff, 0xd1, 0xc3);
  characterSelectCode.writeByteArray(bytes);
  Memory.protect(characterSelectCode, Process.pageSize, 'r-x');
  new NativeFunction(characterSelectCode, 'void', [])();
}

rpc.exports = {
  initialize(configuration) {
    if (initialized) throw new Error('Bridge is already initialized');
    if (Process.arch !== 'ia32') throw new Error('Expected the pinned x86 game client');
    if (normalizedPath(Process.mainModule.path) !== normalizedPath(configuration.executable))
      throw new Error('PID does not belong to the dedicated QA executable');
    const silver = Process.getModuleByName('silver.dll');
    moduleBase = silver.base;
    if (normalizedPath(silver.path) !== normalizedPath(configuration.silver_path))
      throw new Error('Unexpected SILVER module path');
    for (const guard of configuration.entry_guards) {
      if (hex(at(guard.va), 12) !== relocatedEntry(guard))
        throw new Error('Native function entry differs: ' + guard.name);
    }
    if (!/^q[a-z][a-f0-9]{8}[ab]$/.test(configuration.login))
      throw new Error('Only fresh randomly named QA accounts are accepted');
    if (!/^[\x21-\x7e]{12,64}$/.test(configuration.password))
      throw new Error('QA password format is unsupported');
    
    EXPECTED_SESSION_PORT = configuration.loopback_session_port;
    qaLoginPort = configuration.loopback_login_port;
    // Observe the exact production route thunk before credential allocation.
    const routeOrange = Process.getModuleByName('orange.dll');
    const exportConnect = routeOrange.getExportByName('AaaAa');
    if(exportConnect.sub(routeOrange.base).toUInt32()!==0x118f || exportConnect.readU8()!==0xe9)
      throw new Error('Unexpected production ORANGE route export');
    const gateRoute = exportConnect.add(5).add(exportConnect.add(1).readS32());
    const gateAddress = gateRoute.add(3).readPointer();
    const blockedAddress = gateRoute.add(12).readPointer();
    const gateExpected = [0x9c,0x80,0x3d,...[0,1,2,3].map(i=>(gateAddress.toUInt32()>>>(8*i))&255),1,0x74,8,0xff,0x05,
      ...[0,1,2,3].map(i=>(blockedAddress.toUInt32()>>>(8*i))&255),0x9d,0xc3,0x9d];
    if(!gateAddress.equals(gateRoute.add(2064)) || !blockedAddress.equals(gateAddress.add(4)) ||
       hex(gateRoute,19)!==gateExpected.map(v=>v.toString(16).padStart(2,'0')).join('') || gateAddress.readU8()!==0)
      throw new Error('Owned QA startup gate differs or was already armed');
    const gateRegion = Process.findRangeByAddress(gateAddress);
    const routeRegion = Process.findRangeByAddress(gateRoute);
    if(!gateRegion || gateRegion.protection!=='rw-' || !routeRegion || routeRegion.protection!=='r-x')
      throw new Error('Owned QA gate page protections differ');
    qaGate=gateAddress; qaBlocked=blockedAddress;
    const route = gateRoute.add(19);
    const original = route.add(40).add(route.add(36).readS32());
    const routeHost = route.add(6).readPointer();
    if(!routeHost.equals(gateRoute.add(256)))
      throw new Error('Unexpected production loopback string location');
    const u32bytes = value => [value&255,(value>>>8)&255,(value>>>16)&255,(value>>>24)&255];
    const expectedRoute = [0x9c,0x50,0xc7,0x44,0x24,0x0c,
      ...u32bytes(routeHost.toUInt32()),0x8b,0x44,0x24,0x18,0x80,0xf8,0,0xb8,
      ...u32bytes(configuration.loopback_login_port),0x74,0x05,0xb8,
      ...u32bytes(configuration.loopback_session_port),0x89,0x44,0x24,0x10,0x58,0x9d,0xe9,
      ...u32bytes((original.toUInt32()-route.add(40).toUInt32())>>>0)];
    if(hex(route,40)!==expectedRoute.map(v=>v.toString(16).padStart(2,'0')).join('') ||
       routeHost.readUtf8String()!=='127.0.0.1')
      throw new Error('Production native TLS route bytes differ');
    const signature = 'a0f5509b0c84c074238b0df0509b0c85c974198b4424108b54240c508b44240c528b54240c5052e8'
      .match(/../g).map(v=>parseInt(v,16));
    const actualOriginal = new Uint8Array(original.readByteArray(signature.length));
    for(let i=0;i<signature.length;i++)
      if(!(i>=1&&i<=4)&&!(i>=11&&i<=14)&&signature[i]!==actualOriginal[i])
        throw new Error('Production route original target differs');
    emit('production_native_tls_route_verified',{loopback_host:'127.0.0.1',
      login_port:configuration.loopback_login_port,session_port:configuration.loopback_session_port,
      export_rva:0x118f,route_bytes_verified:40});

    const kernel = Process.getModuleByName('kernel32.dll');
    ownedExit = new NativeFunction(kernel.getExportByName('ExitProcess'), 'void', ['uint32'], 'stdcall');
    persistentHeap = new NativeFunction(kernel.getExportByName('GetProcessHeap'), 'pointer', [], 'stdcall')();
    persistentAllocate = new NativeFunction(kernel.getExportByName('HeapAlloc'), 'pointer',
      ['pointer', 'uint32', 'uint32'], 'stdcall');
    credentials = {
      username: delphiString(configuration.login),
      password: delphiString(configuration.password),
    };
    ownedLogin = configuration.login;
    autoSelect = configuration.auto_select === true;
    // The authentic native AuthResult reader calls the ordinary login builder.
    // This observational hook leaves the network response and parser intact.
    Interceptor.attach(at(0x87ce60), {
      onEnter() {
        if (!state.connected || state.fault || !qaGate || qaGate.readU8() !== 1) return failClosed('Challenge arrived outside armed owned connection');
        state.authChallengeStatus = this.context.eax.readU8();
        emit('native_auth_challenge', { status: state.authChallengeStatus });
      },
    });
    Interceptor.attach(at(0x87c604), {
      onEnter() {
        if (state.fault || !state.connected || state.authChallengeStatus !== 0 || !credentials || !qaGate || qaGate.readU8() !== 1) {
          return failClosed('Login builder ran outside the observed successful challenge');
        }
        this.context.eax = credentials.username.add(12);
        this.context.edx = credentials.password.add(12);
        state.credentialsSubmitted = true;
        emit('native_credentials_submitted');
      },
    });
    statusHook(0x87d00c, 'loginStatus', 'native_login_result');
    statusHook(0x87d400, 'serverLoginStatus', 'native_server_login_result');
    statusHook(0x87d608, 'gameAuth1Status', 'native_game_auth1_result');
    statusHook(0x87d8a4, 'gameAuth2Status', 'native_game_auth2_result');
    Interceptor.attach(at(0x889eac), {
      onEnter() { this.characterCount = this.context.eax.readU16(); },
      onLeave() {
        try { selectOwnedCharacter(this.characterCount); }
        catch (error) {
          failClosed(String(error.message));
        }
      },
    });
    Interceptor.attach(at(0x8a3108), {
      onEnter() {
        if(state.fault || !state.authenticated || !state.charactersLoaded || this.context.eax.toUInt32()!==0)
          return failClosed('Character callback is outside observed owned roster');
        const row=state.characters[0];
        if(!row || row.id!==1 || row.name!==ownedLogin || row.unselectable!==0)
          return failClosed('Character callback target is not owned');
        state.selectedCharacter={...row};
      }
    });
    Interceptor.attach(at(0x88a4cc), {
      onEnter() {
        if(state.fault || !state.authenticated || !state.selectedCharacter) return failClosed('Character result lacks owned callback');
        state.characterSelectStatus = this.context.eax.readU8();
        emit('native_character_select_result', { status: state.characterSelectStatus });
      },
    });
    Interceptor.attach(at(0x889e3c), {
      onEnter() {
        if(state.fault || !state.authenticated || !state.selectedCharacter || state.characterSelectStatus!==0) return failClosed('World start is outside owned successful selection');
        state.worldStartSent = true;
        emit('native_world_start_builder', { selected_character: state.selectedCharacter?.id,
          character_select_status: state.characterSelectStatus });
      },
    });
    Interceptor.attach(at(0x87d1cc), {
      onEnter() {
        if(state.fault || !state.credentialsSubmitted || state.loginStatus!==0) return failClosed('Server list lacks owned successful login');
        listParsing = true; listRows = [];
        state.serverListLoaded = false;
        this.expectedCount = this.context.eax.readU8();
      },
      onLeave() {
        listParsing = false;
        if (listRows.length !== this.expectedCount) {
          return failClosed('Native parsed server-row count differs');
        }
        state.serverRows = listRows.map(row => ({ ...row }));
        state.serverListLoaded = true;
        emit('native_server_list_loaded', { rows: state.serverRows });
        // When requested before connect, execute on the genuine list handler's
        // thread just as the established diagnostic native callback does.
        if (autoSelect) {
          try { guardedSelection(); }
          catch (error) {
            failClosed(String(error.message));
          }
        }
      },
    });
    Interceptor.attach(at(0x71fea0), {
      onEnter() {
        if (!listParsing) return;
        const record = this.context.edx;
        const host = record.add(4).readPointer();
        listRows.push({ index: listRows.length, id: record.readU8(),
          host: host.isNull() ? '' : host.readUtf16String(),
          port: record.add(8).readU16() });
      },
    });
    const orange = Process.getModuleByName('orange.dll');
    nativeConnect = new NativeFunction(orange.getExportByName('AaaAa'), 'void',
      ['pointer', 'uint32', 'pointer', 'uint32'], 'mscdecl');
    nativeSelect = new NativeFunction(at(0x71e998), 'void', []);
    nativeShowAuthorization = new NativeFunction(at(0x87ba24), 'void', []);
    initialized = true;
    emit('owned_qa_startup_gate_verified',{armed:false,blocked_attempts:qaBlocked.readU32()});
    emit('native_bridge_initialized');
    return { initialized: true, host: EXPECTED_HOST, session_port: EXPECTED_SESSION_PORT };
  },
  startconnect() {
    // Genuine native ORANGE transport; the server supplies challenge, auth and
    // server-list responses. No socket replacement or synthetic packets.
    return startGenuineHostedConnection(false);
  },
  startconnectwithprogress() {
    return startGenuineHostedConnection(true);
  },
  selectserver() { return guardedSelection(); },
  disarm() { if(qaGate) qaGate.writeU8(0); return {disarmed:true}; },
  status() { const snapshot=JSON.parse(JSON.stringify(state)); snapshot.characters=snapshot.characters.map(({name,...rest})=>rest); if(snapshot.selectedCharacter) delete snapshot.selectedCharacter.name; return snapshot; },
};
