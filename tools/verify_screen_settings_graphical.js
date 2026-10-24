'use strict';
// Observation only inside the SHA/provenance-guarded owned test process.
let initialized = false, silver = null, renderer = null, wanted = 'initial';
let resultVA=0xc23c30,cvarAddresses={};
let presentCount = 0, beginCount = 0, endCount = 0, nativeResizeCount = 0;
let silverResizeCount = 0, chatResizeCount = 0, silverRenderTarget = null;
let activeScene = false, renderThread = null, lastBeginHRESULT = null, lastEndHRESULT = null;
let snapshots = [], resets = [], getter = null, getterCodes = [], getterStrings = [], applyStatus = null;
const cvarNames=['r_monitor','r_fullscreen','r_width','r_height','r_vsync'];
const pinnedTi = [{va:0x64c298, hex:'558bec83c4f4894df48955f8'},
                  {va:0x64a54c, hex:'558bec83c4dc56578945ec8b'}];
function norm(p) { return p.replace(/\//g, '\\').toLowerCase(); }
function bytes(p, n) { return Array.from(new Uint8Array(p.readByteArray(n))).map(x=>x.toString(16).padStart(2,'0')).join(''); }
function sendEvent(event, value) { send({event, ...value}); }
function at(va) { return silver.base.add(va - 0x400000); }
function r() {
  const reference=ptr(0x76de0c).readPointer();
  if(reference.isNull()) throw new Error('Native renderer reference absent');
  const value=reference.readPointer();
  if(value.isNull()) throw new Error('Native renderer absent');
  return value;
}
function parameters(p) {
  return {width:p.readU32(),height:p.add(4).readU32(),format:p.add(8).readU32(),
    backBufferCount:p.add(12).readU32(),multiSampleType:p.add(16).readU32(),
    multiSampleQuality:p.add(20).readU32(),swapEffect:p.add(24).readU32(),
    window:p.add(28).readPointer().toString(),windowed:p.add(32).readU32(),
    enableAutoDepthStencil:p.add(36).readU32(),autoDepthStencilFormat:p.add(40).readU32(),
    flags:p.add(44).readU32(),refreshRate:p.add(48).readU32(),presentationInterval:p.add(52).readU32()};
}
function com(device, offset, result, args) {
  return new NativeFunction(device.readPointer().add(offset).readPointer(), result, args, 'stdcall');
}
function nativeCvars() {
  return cvarNames.map((name,i)=>({name,value:getter[i]()}));
}
function silverGeometry() {
  const width=at(0xac56e0).readPointer(),height=at(0xac5e60).readPointer();
  const rectangle=at(0xac5a4c).readPointer(),manager=at(0xb76650).readPointer();
  return {width:width.readU32(),height:height.readU32(),
    worldRect:{left:rectangle.readS32(),top:rectangle.add(4).readS32(),
      right:rectangle.add(8).readS32(),bottom:rectangle.add(12).readS32()},
    managerWidth:manager.add(0x29c).readU32(),managerHeight:manager.add(0x2a0).readU32()};
}
function targetFields() {
  return [0x76dfd4,0x76e40c].map(address=>{
    const reference=ptr(address).readPointer(),p=reference.isNull()?ptr(0):reference.readPointer();
    if(p.isNull())return{reference:ptr(address).toString(),object:null};
    return{reference:ptr(address).toString(),object:p.toString(),texture:p.add(12).readPointer().toString(),
      active:p.add(0x60).readU8(),width:p.add(0x14).readU32(),height:p.add(0x18).readU32(),
      requestedWidth:p.add(0x20).readU32(),requestedHeight:p.add(0x1c).readU32()};
  });
}
function surfaceDescription(surface) {
  if(surface.isNull())return null;
  const description=Memory.alloc(32),hr=com(surface,0x30,'int',['pointer','pointer'])(surface,description);
  return{surface:surface.toString(),hresult:hr,width:hr>=0?description.add(24).readU32():null,
    height:hr>=0?description.add(28).readU32():null};
}
function currentTarget(device) {
  const output=Memory.alloc(4),viewport=Memory.alloc(24);output.writePointer(ptr(0));
  const hr=com(device,0x98,'int',['pointer','uint','pointer'])(device,0,output),surface=output.readPointer();
  const row={thread:Process.getCurrentThreadId(),hresult:hr,surface:surfaceDescription(surface)};
  if(!surface.isNull())com(surface,8,'uint',['pointer'])(surface);
  row.getViewportHRESULT=com(device,0xc0,'int',['pointer','pointer'])(device,viewport);
  if(row.getViewportHRESULT>=0)row.viewport={width:viewport.add(8).readU32(),height:viewport.add(12).readU32()};
  return row;
}
function observe(label) {
  // Called on the existing game render/UI thread, after its original scene call.
  const value = r(), device = value.add(0x44).readPointer();
  const snapshot={label,thread:Process.getCurrentThreadId(),presentCount,beginCount,endCount,
    nativeResizeCount,silverResizeCount,chatResizeCount,silverGeometry:silverGeometry(),
    screenSizedTargets:targetFields(),silverRenderTarget,
    requestedDepth:{width:value.add(0x2dc).readU32(),height:value.add(0x2e0).readU32()},
    actualDepth:surfaceDescription(value.add(0x1c0).readPointer()),
    silverCallGate:{lock:ptr(0x76daa0).readU32(),callbackDepth:ptr(0x76daa4).readU32()},
    activeScene,renderThread,lastBeginHRESULT,lastEndHRESULT,
    rendererWidth:value.add(0x208).readU32(),rendererHeight:value.add(0x20c).readU32(),
    lost:value.add(0x2a9).readU8(),initialized:value.add(0x244).readU8(),
    fullscreen:value.add(0x2d7).readU8(),vsyncEnabled:value.add(0x2d3).readU8(),parameters:parameters(value.add(0x180)),
    cvars:nativeCvars(),applyResult:at(resultVA).readU32()};
  const output=Memory.alloc(4), description=Memory.alloc(32);
  output.writePointer(ptr(0));
  const hr=com(device,0x48,'int',['pointer','uint','uint','uint','pointer'])(device,0,0,0,output);
  snapshot.getBackBufferHRESULT=hr;
  const viewport=Memory.alloc(24);
  snapshot.getViewportHRESULT=com(device,0xc0,'int',['pointer','pointer'])(device,viewport);
  if(snapshot.getViewportHRESULT>=0) snapshot.actualViewport={x:viewport.readU32(),y:viewport.add(4).readU32(),
    width:viewport.add(8).readU32(),height:viewport.add(12).readU32(),
    minZ:viewport.add(16).readFloat(),maxZ:viewport.add(20).readFloat()};
  const surface=output.readPointer();
  if(hr>=0 && !surface.isNull()) {
    const descHr=com(surface,0x30,'int',['pointer','pointer'])(surface,description);
    snapshot.getDescHRESULT=descHr;
    if(descHr>=0) snapshot.actualBackBuffer={format:description.readU32(),type:description.add(4).readU32(),
      usage:description.add(8).readU32(),pool:description.add(12).readU32(),
      multiSampleType:description.add(16).readU32(),multiSampleQuality:description.add(20).readU32(),
      width:description.add(24).readU32(),height:description.add(28).readU32()};
    com(surface,8,'uint',['pointer'])(surface);
  }
  snapshots.push(snapshot);
  sendEvent('screen_native_snapshot',snapshot);
}
function installGetters() {
  getter=[];
  for(let i=0;i<cvarNames.length;i++) {
    // Match the DLL's exact immortal UTF16 native cvar name constants.
    const expected=cvarNames[i];
    let text;
    if(cvarAddresses[expected]) text=at(cvarAddresses[expected]);
    else {
      const constant=Memory.alloc(12+2*(expected.length+1));
      constant.writeU16(1200);constant.add(2).writeU16(2);constant.add(4).writeS32(-1);
      constant.add(8).writeU32(expected.length);constant.add(12).writeUtf16String(expected);
      getterStrings.push(constant);text=constant.add(12);
    }
    if(text.readUtf16String()!==expected) throw new Error('Screen native cvar constant differs');
    const code=Memory.alloc(Process.pageSize);
    const values=[0xb8,...u32(text.toUInt32()),0xba,...u32(at(0x688328).toUInt32()),0xff,0xd2,0xc3];
    code.writeByteArray(values);Memory.protect(code,Process.pageSize,'r-x');
    getterCodes.push(code);getter.push(new NativeFunction(code,'int',[]));
  }
}
function u32(x) { return [x&255,(x>>>8)&255,(x>>>16)&255,(x>>>24)&255]; }
rpc.exports={
 initialize(configuration) {
  if(initialized || Process.arch!=='ia32' || Process.mainModule.base.toUInt32()!==0x400000)
    throw new Error('Unexpected owned TI architecture/base');
  if(norm(Process.mainModule.path)!==norm(configuration.executable)) throw new Error('Foreign game process');
  silver=Process.getModuleByName('silver.dll');
  if(norm(silver.path)!==norm(configuration.silver_path)) throw new Error('Foreign Silver module');
  for(const pin of pinnedTi) if(bytes(ptr(pin.va),12)!==pin.hex) throw new Error('TI native render guard differs');
  if(at(configuration.screen_signature_va).readUtf8String()!=='TIO-native-screen-apply-v1') throw new Error('Screen native extension absent');
  resultVA=configuration.screen_apply_result_va;cvarAddresses=configuration.screen_cvar_names;
  installGetters();renderer=r();
  const device=renderer.add(0x44).readPointer(), table=device.readPointer();
  const reset=table.add(0x40).readPointer(), present=table.add(0x44).readPointer();
  for(const address of [reset,present]) {
    const region=Process.findRangeByAddress(address);
    if(!region || region.protection.indexOf('x')<0) throw new Error('Native D3D method is not executable');
  }
  Interceptor.attach(reset,{
    onEnter(args){this.owned=args[0].equals(device);if(this.owned)this.row={parameters:parameters(args[1]),
      thread:Process.getCurrentThreadId(),renderThread,resetOnRenderThread:Process.getCurrentThreadId()===renderThread,
      beginCount,endCount,activeScene,lastBeginHRESULT,lastEndHRESULT,
      screenSizedTargets:targetFields(),requestedDepth:{width:renderer.add(0x2dc).readU32(),height:renderer.add(0x2e0).readU32()},
      silverCallGate:{lock:ptr(0x76daa0).readU32(),callbackDepth:ptr(0x76daa4).readU32()}};},
    onLeave(ret){if(this.owned){this.row.hresult=ret.toInt32();resets.push(this.row);wanted='after-native-reset';sendEvent('screen_d3d_reset',this.row);}}
  });
  Interceptor.attach(present,{onEnter(args){this.owned=args[0].equals(device);},onLeave(ret){if(this.owned){presentCount++;}}});
  Interceptor.attach(table.add(0xa4).readPointer(),{onEnter(args){this.owned=args[0].equals(device);if(this.owned)renderThread=Process.getCurrentThreadId();},
    onLeave(ret){if(this.owned){lastBeginHRESULT=ret.toInt32();if(lastBeginHRESULT>=0)activeScene=true;}}});
  Interceptor.attach(table.add(0xa8).readPointer(),{onEnter(args){this.owned=args[0].equals(device);},
    onLeave(ret){if(this.owned){lastEndHRESULT=ret.toInt32();if(lastEndHRESULT>=0)activeScene=false;}}});
  Interceptor.attach(ptr(0x64ade8),{onEnter(){this.owned=this.context.eax.equals(renderer);if(this.owned)nativeResizeCount++;},
    onLeave(ret){if(this.owned)sendEvent('screen_native_resize_return',{hresult:ret.toInt32(),nativeResizeCount});}});
  Interceptor.attach(at(0x9f47f8),{onEnter(args){silverResizeCount++;this.geometry={width:args[0].toUInt32(),height:args[1].toUInt32(),
    silverResizeCount,thread:Process.getCurrentThreadId()};},onLeave(){wanted='after-silver-resize';sendEvent('screen_silver_resize_return',this.geometry);}});
  Interceptor.attach(at(0xa029dc),{onLeave(){chatResizeCount++;}});
  Interceptor.attach(at(0x9f4004),{onEnter(){if(wanted!==null)silverRenderTarget=currentTarget(device);}});
  Interceptor.attach(ptr(0x64bc84),{onEnter(){beginCount++;}});
  Interceptor.attach(ptr(0x64bcbc),{onEnter(){endCount++;},onLeave(){
    const current=at(resultVA).readU32();
    if(current!==applyStatus){applyStatus=current;wanted='apply-state-'+current;}
    if(wanted!==null){const label=wanted;wanted=null;observe(label);}
  }});
  initialized=true;sendEvent('screen_native_trace_installed',{mainthread_snapshot:true,actual_device_reset_traced:true});
  return {initialized:true};
 },
 snapshot(label){if(typeof label!=='string'||label.length>80)throw new Error('Invalid snapshot label');wanted=label;return{queued:true};},
 status(){return {initialized,presentCount,beginCount,endCount,nativeResizeCount,silverResizeCount,chatResizeCount,resets,snapshots};}
};
