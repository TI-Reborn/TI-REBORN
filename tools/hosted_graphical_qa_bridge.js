// Dedicated QA authentication only: real ORANGE sockets and native SILVER
// readers/builders. No protocol injection, result replacement or packet logging.
'use strict';

const EXPECTED_HOST = '185.184.42.88';
const EXPECTED_SESSION_PORT = 28513;
let expectedSessionHost = EXPECTED_HOST;
let expectedSessionPort = EXPECTED_SESSION_PORT;
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
function at(va) { return moduleBase.add(va - 0x400000); }
function normalizedPath(value) { return value.replace(/\\/g, '/').toLowerCase(); }
function startGenuineHostedConnection(showProgress) {
  if (!initialized || state.connected) throw new Error('Connect is not available');
  state.connected = true;
  if (showProgress) {
    // The unchanged 15-byte callback opens the already-created registered
    // window_autorization. It contains the original spinner and localized
    // m568/m569 instructions. No state/status or network result is fabricated.
    nativeShowAuthorization();
    emit('native_authorization_wait_shown');
  }
  nativeConnect(Memory.allocUtf8String(EXPECTED_HOST), 28512, ptr(0), 0);
  emit('native_hosted_connect_started', { host: EXPECTED_HOST, port: 28512 });
  return { started: true, host: EXPECTED_HOST, port: 28512, native_progress: showProgress };
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
  if (!state.serverListLoaded) throw new Error('Actual native server list has not loaded');
  if (state.selectedServer !== null) throw new Error('Server selection already submitted');
  const rows = state.serverRows.filter(row =>
    row.host === expectedSessionHost && row.port === expectedSessionPort && row.id === 1);
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
        state.authenticated = this.status === 0 && state.loginStatus === 0 &&
          state.serverLoginStatus === 0 && state.gameAuth1Status === 0;
      }
      emit(event, { status: this.status });
    },
  });
}

function selectOwnedCharacter(count) {
  if (!state.authenticated || count !== 1 || state.selectedCharacter !== null)
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
  state.selectedCharacter = { ...row };
  emit('native_owned_character_selection', row);
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
    if (configuration.verified_tls_route === true) {
      if (configuration.session_host !== '127.0.0.1' || !Number.isInteger(configuration.session_port) ||
          configuration.session_port < 1024 || configuration.session_port > 65535)
        throw new Error('Invalid own launcher TLS route');
      expectedSessionHost = configuration.session_host;
      expectedSessionPort = configuration.session_port;
    }
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
    if (!/^q[a-z][a-f0-9]{8}[abcd]$/.test(configuration.login))
      throw new Error('Only fresh randomly named QA accounts are accepted');
    if (!/^[\x21-\x7e]{12,64}$/.test(configuration.password))
      throw new Error('QA password format is unsupported');
    const kernel = Process.getModuleByName('kernel32.dll');
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
        state.authChallengeStatus = this.context.eax.readU8();
        emit('native_auth_challenge', { status: state.authChallengeStatus });
      },
    });
    Interceptor.attach(at(0x87c604), {
      onEnter() {
        if (!state.connected || state.authChallengeStatus !== 0 || !credentials) {
          state.fault = 'Login builder ran outside the observed successful challenge';
          emit('bridge_fault', { reason: state.fault });
          return;
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
        if (!autoSelect) return;
        try { selectOwnedCharacter(this.characterCount); }
        catch (error) {
          state.fault = String(error.message);
          emit('bridge_fault', { reason: state.fault });
        }
      },
    });
    Interceptor.attach(at(0x88a4cc), {
      onEnter() {
        state.characterSelectStatus = this.context.eax.readU8();
        emit('native_character_select_result', { status: state.characterSelectStatus });
      },
    });
    Interceptor.attach(at(0x889e3c), {
      onEnter() {
        state.worldStartSent = true;
        emit('native_world_start_builder', { selected_character: state.selectedCharacter?.id,
          character_select_status: state.characterSelectStatus });
      },
    });
    Interceptor.attach(at(0x87d1cc), {
      onEnter() {
        listParsing = true; listRows = [];
        state.serverListLoaded = false;
        this.expectedCount = this.context.eax.readU8();
      },
      onLeave() {
        listParsing = false;
        if (listRows.length !== this.expectedCount) {
          state.fault = 'Native parsed server-row count differs';
          emit('bridge_fault', { reason: state.fault });
          return;
        }
        state.serverRows = listRows.map(row => ({ ...row }));
        state.serverListLoaded = true;
        emit('native_server_list_loaded', { rows: state.serverRows });
        // When requested before connect, execute on the genuine list handler's
        // thread just as the established diagnostic native callback does.
        if (autoSelect) {
          try { guardedSelection(); }
          catch (error) {
            state.fault = String(error.message);
            emit('bridge_fault', { reason: state.fault });
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
          port: record.add(8).readU16(), online: record.add(10).readU16(),
          available: record.add(14).readU8() });
      },
    });
    const orange = Process.getModuleByName('orange.dll');
    nativeConnect = new NativeFunction(orange.getExportByName('AaaAa'), 'void',
      ['pointer', 'uint32', 'pointer', 'uint32'], 'mscdecl');
    nativeSelect = new NativeFunction(at(0x71e998), 'void', []);
    nativeShowAuthorization = new NativeFunction(at(0x87ba24), 'void', []);
    initialized = true;
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
  status() { return JSON.parse(JSON.stringify(state)); },
};
