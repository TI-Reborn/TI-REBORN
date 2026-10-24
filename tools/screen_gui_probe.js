'use strict';
let silver=null,finished=false,treeRows=[],total=0,setTargets=[],objectBinds=[],renderCount=0;
const at=va=>silver.base.add(va-0x400000);
function hex(p,n){return Array.from(new Uint8Array(p.readByteArray(n))).map(x=>x.toString(16).padStart(2,'0')).join('');}
function field(p,o){return p.add(o).readPointer();}
function nativeName(p){
  try{const value=field(p,0x68);if(value.isNull())return'';
    const count=value.sub(4).readU32();if(count>128)return'<long-name>';
    return value.readUtf16String(count);}catch(_){return'<unreadable-name>';}
}
function className(p){
  try{const vmt=p.readPointer(),value=vmt.sub(0x38).readPointer(),n=value.readU8();
    if(n>64)return'<unknown-class>';return value.add(1).readUtf8String(n);}catch(_){return'<unknown-class>';}
}
function list(p){
  if(p.isNull())return[];
  const n=p.add(8).readU32(),data=p.add(4).readPointer();
  if(n>2048||n&&data.isNull())throw new Error('GUI child list exceeds probe bound');
  return Array.from({length:n},(_,i)=>data.add(i*4).readPointer());
}
function visit(p,depth,parent){
  if(p.isNull()||depth>7||total>=1500)return;
  total++;
  const row={ptr:p.toString(),parent,depth,name:nativeName(p),class:className(p),
    x:p.add(0x30).readS32(),y:p.add(0x34).readS32(),width:p.add(0x38).readS32(),height:p.add(0x3c).readS32(),
    visible:p.add(0x49).readU8(),children:[]};
  row.alignment=p.add(0x18).readU8();row.reference=field(p,4).toString();
  row.relative={x:p.add(8).readFloat(),y:p.add(12).readFloat(),width:p.add(16).readFloat(),height:p.add(20).readFloat()};
  row.layoutRoot8=hex(p.add(0x1c),8);
  if(row.class==='TGUIChatPage'){
    row.nativeParent=field(p,0x4c).toString();row.chatFields={};
    for(const offset of [0x288,0x29c,0x2a0,0x2a4,0x2a8,0x2ac])row.chatFields['0x'+offset.toString(16)]=field(p,offset).toString();
  }
  if(depth===0){
    row.onResizeRaw=hex(p.add(0x2c0),16);
    try{const name=field(p,0x2c4),n=name.sub(4).readU32();row.onResizeEventName=n<=256?name.readUtf16String(n):'<long-event-name>';}catch(_){row.onResizeEventName='<unreadable-event-name>';}
    try{const callbacks=field(p,0x2d0),n=callbacks.isNull()?0:callbacks.sub(4).readU32();
      row.onResizeCallbacks=n<=32?Array.from({length:n},(_,i)=>({method:field(callbacks,i*8).toString(),data:field(callbacks,i*8+4).toString()})):'<long-callback-list>';}catch(_){row.onResizeCallbacks='<unreadable-callback-list>';}
  }
  treeRows.push(row);
  try{for(const child of list(field(p,0x2c))){row.children.push(child.toString());visit(child,depth+1,p.toString());}}
  catch(_){row.childListUnreadable=true;}
}
function com(p,o,result,args){return new NativeFunction(p.readPointer().add(o).readPointer(),result,args,'stdcall');}
function graphics(){
  const renderer=ptr(0x76de0c).readPointer().readPointer(),device=field(renderer,0x44);
  const surface=Memory.alloc(4),description=Memory.alloc(32),viewport=Memory.alloc(24);
  surface.writePointer(ptr(0));
  const out={rendererWidth:renderer.add(0x208).readU32(),rendererHeight:renderer.add(0x20c).readU32(),
    getRenderTargetHRESULT:com(device,0x98,'int',['pointer','uint','pointer'])(device,0,surface)};
  const target=surface.readPointer();
  out.surface=target.toString();
  if(!target.isNull()){
    out.getDescHRESULT=com(target,0x30,'int',['pointer','pointer'])(target,description);
    if(out.getDescHRESULT>=0)out.target={format:description.readU32(),usage:description.add(8).readU32(),
      pool:description.add(12).readU32(),width:description.add(24).readU32(),height:description.add(28).readU32()};
    com(target,8,'uint',['pointer'])(target);
  }
  out.getViewportHRESULT=com(device,0xc0,'int',['pointer','pointer'])(device,viewport);
  if(out.getViewportHRESULT>=0)out.viewport={x:viewport.readU32(),y:viewport.add(4).readU32(),width:viewport.add(8).readU32(),height:viewport.add(12).readU32()};
  return out;
}
function textureObject(p){
  if(p.isNull())return null;
  let name='';try{const text=field(p,4);if(!text.isNull())name=text.readUtf8String(Math.min(text.sub(4).readU32(),128));}catch(_){name='<unreadable>';}
  const out={ptr:p.toString(),name,texture:field(p,12).toString(),width:p.add(0x14).readU32(),height:p.add(0x18).readU32(),
    requestedHeight:p.add(0x1c).readU32(),requestedWidth:p.add(0x20).readU32(),depthStencil:field(p,16).toString()};
  const texture=field(p,12),surf=Memory.alloc(4);surf.writePointer(ptr(0));
  out.getSurfaceLevelHRESULT=com(texture,0x48,'int',['pointer','uint','pointer'])(texture,0,surf);
  if(out.getSurfaceLevelHRESULT>=0&&!surf.readPointer().isNull()){
    out.surface=surf.readPointer().toString();com(surf.readPointer(),8,'uint',['pointer'])(surf.readPointer());
  }
  return out;
}
rpc.exports={initialize(config){
  if(Process.arch!=='ia32'||Process.mainModule.path.toLowerCase()!==config.executable.toLowerCase())throw new Error('Foreign process');
  silver=Process.getModuleByName('silver.dll');
  if(silver.path.toLowerCase()!==config.silver_path.toLowerCase())throw new Error('Foreign Silver');
  // The main owned trace already instruments the export's prologue. Its
  // unmodified next call site follows only native profiling setup and is
  // separately pinned, allowing a second observer without bypassing a guard.
  const renderSite=config.render_observation_va||0x9f4004;
  if(renderSite!==0x9f4004&&renderSite!==0x9f4014)throw new Error('Unknown render observation site');
  if(hex(at(renderSite),8)!==config.render_entry)throw new Error('Native render entry differs');
  const renderer=ptr(0x76de0c).readPointer().readPointer(),device=field(renderer,0x44);
  Interceptor.attach(device.readPointer().add(0x94).readPointer(),{onEnter(args){
    if(!finished && args[0].equals(device) && setTargets.length<20)setTargets.push({surface:args[2].toString(),returnAddress:this.returnAddress.toString()});
  }});
  Interceptor.attach(ptr(0x64c09c),{onEnter(){
    if(!finished && objectBinds.length<20)objectBinds.push({object:this.context.edx.toString(),returnAddress:this.returnAddress.toString()});
  }});
  Interceptor.attach(at(renderSite),{onEnter(){
    if(finished)return;if(++renderCount<3)return;finished=true;
    const manager=at(0xb76650).readPointer();
    for(const child of list(field(manager,0x280)))visit(child,0,'manager');
    send({event:'screen_gui_probe',thread:Process.getCurrentThreadId(),managerWidth:manager.add(0x29c).readU32(),
      managerHeight:manager.add(0x2a0).readU32(),graphics:graphics(),tree:treeRows,total,
      renderObservationVA:'0x'+renderSite.toString(16),setTargets,objectBinds,
      worldTarget:textureObject(ptr(0x76dfd4).readPointer().readPointer())});
  }});
  return{installed:true};
}};
