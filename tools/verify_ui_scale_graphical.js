'use strict';
// Observation only inside the SHA/provenance-guarded owned test process.
let initialized = false, silver = null, renderer = null, wanted = 'initial';
let resultVA=0xc23c30,cvarAddresses={};
let presentCount = 0, beginCount = 0, endCount = 0, nativeResizeCount = 0;
let silverResizeCount = 0, chatResizeCount = 0, silverRenderTarget = null;
let activeScene = false, renderThread = null, lastBeginHRESULT = null, lastEndHRESULT = null;
let snapshots = [], resets = [], getter = null, getterCodes = [], getterStrings = [], applyStatus = null;
let portraitPassSample=null;
const cvarNames=['r_monitor','r_fullscreen','r_width','r_height','r_vsync','ui_scale'];
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
function portraitFields(describe) {
  const p=ptr(0x777030).readPointer();
  if(p.isNull())return {object:null};
  const texture=p.add(12).readPointer();
  const row={object:p.toString(),texture:texture.toString(),active:p.add(0x60).readU8(),
    width:p.add(0x14).readU32(),height:p.add(0x18).readU32(),
    requestedWidth:p.add(0x20).readU32(),requestedHeight:p.add(0x1c).readU32(),
    depthWanted:p.add(0x61).readU8(),depthSurface:p.add(0x10).readPointer().toString(),
    startupRebuildStatus:at(0xc2de00).readS32(),startupRebuildError:at(0xc2de04).readU32(),
    originalCreationOperands:bytes(ptr(0x6f702a),10)};
  if(describe && !texture.isNull()) {
    const output=Memory.alloc(4);output.writePointer(ptr(0));
    row.getSurfaceLevelHRESULT=com(texture,0x48,'int',['pointer','uint','pointer'])(texture,0,output);
    const surface=output.readPointer();
    if(row.getSurfaceLevelHRESULT>=0 && !surface.isNull())row.actualSurface=surfaceDescription(surface);
    if(!surface.isNull())com(surface,8,'uint',['pointer'])(surface);
  }
  return row;
}
function scaleFields() {
  const state=at(0xc28f00);
  return{effectivePercent:state.readU32(),physicalWidth:state.add(4).readU32(),physicalHeight:state.add(8).readU32(),
    logicalWidth:state.add(12).readU32(),logicalHeight:state.add(16).readU32(),requestedPercent:state.add(0x18).readU32(),
    multiplier:state.add(0x1c).readFloat(),inverse:state.add(0x20).readFloat()};
}
function startupFields() {
  function read(va){return at(va).readU32();}
  return{guiManager:at(0xb76650).readPointer().toString(),portrait:portraitFields(false),
    portraitStatus:read(0xc2de00),portraitError:read(0xc2de04),
    portraitOriginalDepthWanted:read(0xc2de0c),uiScale:scaleFields(),
    coreInstallStatus:at(0xc28f28).readS32(),coreInstallError:read(0xc28f2c),
    coreLoadCallback:at(0xc28f24).readPointer().toString(),
    nativeThreads:Process.enumerateThreads().map(t=>({id:t.id,state:t.state,pc:t.context.pc.toString()}))};
}
function portraitWindow() {
  const manager=at(0xb76650).readPointer();
  if(manager.isNull())return null;
  const list=manager.add(0x280).readPointer();
  if(list.isNull())return null;
  const count=list.add(8).readU32(),array=list.add(4).readPointer();
  if(count>512 || array.isNull())return null;
  function geometry(p){return {object:p.toString(),visible:p.add(0x49).readU8(),
    x:p.add(0x30).readS32(),y:p.add(0x34).readS32(),width:p.add(0x38).readU32(),height:p.add(0x3c).readU32()};}
  for(let i=0;i<count;i++) {
    const p=array.add(i*4).readPointer(),name=p.add(0x68).readPointer();
    if(name.isNull() || name.sub(4).readU32()>80 || name.readUtf16String()!=='window_portrait_preview')continue;
    const row=geometry(p),close=p.add(0x344).readPointer();
    if(!close.isNull())row.closeButton=geometry(close);
    const children=p.add(0x2c).readPointer();
    if(!children.isNull()) {
      const n=children.add(8).readU32(),data=children.add(4).readPointer();
      if(n<=32 && !data.isNull())for(let j=0;j<n;j++) {
        const child=data.add(j*4).readPointer();
        if(child.readPointer().equals(at(0x8a22e4))) {
          row.portrait=geometry(child);row.portrait.angle=child.add(0x2e8).readS32();
          row.portrait.arrowOffsetY=child.add(0x2f0).readS32();
          row.portrait.dragActive=child.add(0x2e0).readU8();
          row.portrait.dragLastX=child.add(0x2e4).readS32();
          row.portrait.dragHeight=child.add(0x2f4).readS32();
        }
      }
    }
    return row;
  }
  return null;
}
function previewActorAngle() {
  // Read only the selected native actor; do not invoke rotation or GUI handlers.
  const index=ptr(0x76d9a0).readS32(),table=ptr(0x76e430).readPointer();
  if(index<0 || index>30 || table.isNull())return null;
  const actor=table.add(index*4).readPointer();
  return actor.isNull()?null:{index,actor:actor.toString(),angle:actor.add(0x534).readS32()};
}
function cachedInventoryGeometry() {
  const manager=at(0xb76650).readPointer();
  if(manager.isNull())return null;
  function bounds(p) {
    return {object:p.toString(),parent:p.add(0x4c).readPointer().toString(),visible:p.add(0x49).readU8(),
      x:p.add(0x30).readS32(),y:p.add(0x34).readS32(),width:p.add(0x38).readS32(),height:p.add(0x3c).readS32()};
  }
  const result={root:null,tabs:[]},list=manager.add(0x280).readPointer();
  if(!list.isNull()) {
    const count=list.add(8).readU32(),array=list.add(4).readPointer();
    if(count<=512 && !array.isNull())for(let i=0;i<count;i++) {
      const p=array.add(i*4).readPointer();
      if(!p.isNull() && p.readPointer().equals(at(0xa31a40))) {
        const name=p.add(0x68).readPointer();
        if(!name.isNull() && name.sub(4).readU32()<=80 && name.readUtf16String()==='window_squad_page')result.root=bounds(p);
      }
    }
  }
  for(const [name,va] of [['left',0xad10a0],['right',0xad10a4],['toolbar',0xad1094],
      ['categories',0xad1098],['craft',0xad109c],['abilitiesLeft',0xad10a8],['abilitiesRight',0xad10ac]]) {
    const p=at(va).readPointer();
    if(!p.isNull())result.tabs.push({name,...bounds(p)});
  }
  const table=at(0xac4bd8).readPointer();
  if(!table.isNull() && table.readPointer().equals(at(0x995ec4))) {
    const scrollbar=table.add(0x280).readPointer();
    result.table={...bounds(table),cacheWidth:table.add(0x44).readS32(),cacheHeight:table.add(0x40).readS32(),
      viewportHeight:table.add(0x288).readS32(),contentExtent:table.add(0x290).readS32(),
      selection:table.add(0x294).readS32(),contents:table.add(0x2c8).readPointer().toString(),
      scrollbar:scrollbar.isNull()?null:bounds(scrollbar)};
  }
  const bag=at(0xac4bd4).readPointer();
  if(!bag.isNull() && bag.readPointer().equals(at(0x9b23e0))) {
    const scrollbar=bag.add(0x298).readPointer();
    result.bag={...bounds(bag),cacheWidth:bag.add(0x44).readS32(),cacheHeight:bag.add(0x40).readS32(),
      rows:bag.add(0x2ac).readS32(),scrollOffset:bag.add(0x2b0).readS32(),
      scrollbar:scrollbar.isNull()?null:bounds(scrollbar)};
  }
  return result;
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
    screenSizedTargets:targetFields(),silverRenderTarget,portraitTarget:portraitFields(true),
    uiScale:scaleFields(),portraitWindow:portraitWindow(),previewActorAngle:previewActorAngle(),cachedInventory:cachedInventoryGeometry(),portraitPassSample,
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
  if(at(0xc28e00).readUtf8String()!=='TIO-independent-ui-scale-v1' ||
     at(0xc2afc0).readUtf8String()!=='TIO-ui-scale-controls-v1' ||
     at(0xc2cf00).readUtf8String()!=='TIO-portrait-512-preview-v1')throw new Error('UI/portrait reviewed extension absent');
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
      screenSizedTargets:targetFields(),portraitTarget:portraitFields(false),uiScale:scaleFields(),
      requestedDepth:{width:renderer.add(0x2dc).readU32(),height:renderer.add(0x2e0).readU32()},
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
  Interceptor.attach(ptr(0x6b02ac),{onEnter(){this.portrait=this.context.eax.equals(ptr(0x777030).readPointer());},
    onLeave(){if(this.portrait && (portraitPassSample===null || wanted!==null)) {
      const output=Memory.alloc(4);output.writePointer(ptr(0));
      const hr=com(device,0xa0,'int',['pointer','pointer'])(device,output),surface=output.readPointer();
      portraitPassSample={thread:Process.getCurrentThreadId(),activeScene,getDepthHRESULT:hr,
        target:currentTarget(device),depth:surfaceDescription(surface),portrait:portraitFields(false)};
      if(!surface.isNull())com(surface,8,'uint',['pointer'])(surface);
      sendEvent('portrait_native_pass',portraitPassSample);
    }}});
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
 status(){return {initialized,presentCount,beginCount,endCount,nativeResizeCount,silverResizeCount,chatResizeCount,
   startup:startupFields(),resets,snapshots};}
};
