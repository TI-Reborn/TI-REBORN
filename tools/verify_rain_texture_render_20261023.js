
const m=Process.getModuleByName('silver.dll');const p=a=>m.base.add(a-0x400000);
const load=new NativeFunction(p(0xac5dfc).readPointer().readPointer(),'void',['pointer','pointer','int','int','int','int','int'],'stdcall');
const draw=new NativeFunction(p(0xac5b88).readPointer().readPointer(),'int',['pointer','int','int','int','int','int','int','int','uint','int'],'stdcall');
const loadRainExtension=new NativeFunction(p(0xc7c800),'void',[]);
const paths=[], rows=[], textures=[];let done=false;
for(let wide of [false,true]){const path=Memory.alloc(64),row=Memory.alloc(12);path.writeS32(-1);path.add(4).writeU32(12);if(wide)path.add(8).writeUtf16String('gfx\\rain.tga');else path.add(8).writeUtf8String('gfx\\rain.tga');paths.push(path);rows.push(row);}
function textureInfo(handle){
 const tex=handle.add(12).readPointer(),vt=tex.readPointer();
 const desc=Memory.alloc(32),locked=Memory.alloc(8);
 const describe=new NativeFunction(vt.add(17*4).readPointer(),'int',['pointer','uint','pointer'],'stdcall');
 const lock=new NativeFunction(vt.add(19*4).readPointer(),'int',['pointer','uint','pointer','pointer','uint'],'stdcall');
 const unlock=new NativeFunction(vt.add(20*4).readPointer(),'int',['pointer','uint'],'stdcall');
 const hr=describe(tex,0,desc);if(hr<0)throw Error('GetLevelDesc '+hr);
 const w=desc.add(24).readU32(),h=desc.add(28).readU32();let min=255,max=0,zero=0;
 const lh=lock(tex,0,locked,ptr(0),0x10);if(lh<0)throw Error('LockRect '+lh);
 try{const pitch=locked.readU32(),bits=locked.add(4).readPointer();for(let y=0;y<h;y++)for(let x=0;x<w;x++){const a=bits.add(y*pitch+x*4+3).readU8();min=Math.min(min,a);max=Math.max(max,a);if(a===0)zero++;}}finally{unlock(tex,0);}
 return {width:w,height:h,format:desc.readU32(),alpha_min:min,alpha_max:max,zero_alpha_pixels:zero};
}
const dev=ptr(0x76de0c).readPointer().readPointer().add(0x44).readPointer();
Interceptor.attach(dev.readPointer().add(42*4).readPointer(),{onEnter(){
 if(!done){done=true;loadRainExtension();for(let i=0;i<2;i++){load(rows[i],paths[i].add(8),64,64,0,0,2);textures.push(rows[i].readPointer());}send({event:'native-texture-proof',before:textureInfo(textures[0]),after:textureInfo(textures[1]),actual_weather_extension:textureInfo(p(0xc7f040).readPointer()),rain_path_memory:p(0xc7f100).readUtf16String(12)});}
 for(let i=0;i<2;i++){
  draw(textures[i],64,64,200+i*350,180,32,128,0,0x80e0d0b0,0);
  for(let n=0;n<12;n++)draw(textures[i],64,64,130+i*350+(n%4)*40,390+Math.floor(n/4)*45,8,32,0,0x80e0d0b0,0);
 }
}});
