// Observational barter handlers and original request writers in owned QA games.
const image=Process.getModuleByName('silver.dll');
const at=va=>image.base.add(va-0x400000);
const state={invites:0,starts:0,ownUpdates:0,otherUpdates:0,done:0,actions:[],fault:null,sentInvites:[],errors:[],sentPackets:[]};
const keep=[];let pending=null,running=false,uiThread=null;
for(const [entry,field] of [[0x713fb0,'invites'],[0x714068,'starts'],[0x7143a4,'ownUpdates'],[0x714670,'otherUpdates'],[0x714990,'done']])
  Interceptor.attach(at(entry),{onEnter(){state[field]++;uiThread=Process.getCurrentThreadId();}});
const user=Process.getModuleByName('user32.dll');
const getPid=new NativeFunction(user.getExportByName('GetWindowThreadProcessId'),'uint',['pointer','pointer'],'stdcall');
const getClass=new NativeFunction(user.getExportByName('GetClassNameW'),'int',['pointer','pointer','int'],'stdcall');
const enumWindows=new NativeFunction(user.getExportByName('EnumWindows'),'bool',['pointer','pointer'],'stdcall');
const name=Memory.alloc(512),pid=Memory.alloc(4);
const cb=new NativeCallback((hwnd,x)=>{getPid(hwnd,pid);getClass(hwnd,name,256);if(pid.readU32()===Process.id&&name.readUtf16String()==='TForm1')uiThread=getPid(hwnd,pid);return 1;},'bool',['pointer','pointer']);
enumWindows(cb,ptr(0));
function pump(){
  if(!pending||running||Process.getCurrentThreadId()!==uiThread)return;
  running=true;const work=pending;pending=null;
  try{work.run();state.actions.push(work.action);}catch(e){state.fault=String(e.message);}finally{running=false;}
}
for(const entry of ['PeekMessageW','PeekMessageA','GetMessageW','GetMessageA'])
  Interceptor.attach(user.getExportByName(entry),{onLeave:pump});
function writer(entry,a,d,c=0){
  const code=Memory.alloc(Process.pageSize);keep.push(code);
  const u32=v=>[v&255,(v>>>8)&255,(v>>>16)&255,(v>>>24)&255];
  const target=at(entry).toUInt32(),base=code.toUInt32();
  const bytes=[0x9c,0x60,0xb8,...u32(a),0xba,...u32(d),0xb9,...u32(c),0xe8,...u32((target-(base+22))>>>0),0x61,0x9d,0xc3];
  code.writeByteArray(bytes);Memory.protect(code,Process.pageSize,'r-x');
  return new NativeFunction(code,'void',[]);
}
rpc.exports={
  status(){return JSON.parse(JSON.stringify(state));},
  action(action,args){
    if(pending)throw new Error('An owned action is already pending');
    let call;
    if(action==='invite'){
      if(!/^q[a-z][a-f0-9]{8}[abcd]$/.test(args.name))throw new Error('Only owned QA recipients are permitted');
      const s=Memory.alloc(16+args.name.length*2);keep.push(s);
      // 674AAC converts a managed UnicodeString to the ANSI wire CString.
      s.writeU16(1200);s.add(2).writeU16(2);s.add(4).writeS32(-1);s.add(8).writeU32(args.name.length);s.add(12).writeUtf16String(args.name);
      call=writer(0x713f18,s.add(12).toUInt32(),1);
    }else if(action==='answer')call=writer(0x71402c,args.accept?1:0,1);
    else if(action==='offer')call=writer(0x714368,args.item>>>0,args.count>>>0);
    else if(action==='confirm')call=writer(0x71493c,args.accept?1:0,0);
    else throw new Error('Unsupported owned barter action');
    pending={action,run:call};return {queued:true,uiThread};
  },
};
