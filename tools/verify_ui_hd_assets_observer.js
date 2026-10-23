'use strict';
// Appended to the original owned display observer. All HD callbacks observe
// already-running native instructions; none invokes a GUI or gameplay handler.
let hdRuntimeConfiguration = null;
let hdTextureLoads = [];
let hdFontSamples = [];
let hdIconSamples = [];
let hdObservedDensities = new Set();
let hdIconTextures = new Map();
let hdIconKeys = new Set();
let hdIconDensitySamples = new Map();

function hdTextureFields(p) {
  if(p.isNull()) return {object:'0x0'};
  return {object:p.toString(),gpu:p.add(12).readPointer().toString(),
    width:p.add(0x14).readU32(),height:p.add(0x18).readU32(),renderTarget:p.add(0x60).readU8()};
}

function hdWords(rva, definitions) {
  const address = at(0x400000 + rva), output = {};
  for (const [key, offset, kind] of definitions) {
    const field = address.add(offset);
    output[key] = kind === 'pointer' ? field.readPointer().toString()
      : kind === 'signed' ? field.readS32() : field.readU32();
  }
  return output;
}

function hdStatus() {
  if (!hdRuntimeConfiguration) return {observerInstalled: false};
  const font = hdWords(hdRuntimeConfiguration.fontState, [
    ['loadStatus',0,'signed'],['error',4],['loadedAtlases',8],['installStatus',12,'signed'],
    ['adaptedGlyphs',0x20],['fallbacks',0x24],['snappedVertices',0x28],
    ['lastPercent',0x2c],['lastRole',0x30],['lastCodepoint',0x34],
    ['originalTexture',0x38,'pointer'],['selectedTexture',0x3c,'pointer'],
    ['sourceX',0x40],['sourceY',0x44],['sourceWidth',0x48],['sourceHeight',0x4c],
    ['destinationX',0x50,'signed'],['destinationY',0x54,'signed'],
    ['destinationWidth',0x58],['destinationHeight',0x5c],
    ['loadFailures',0x60],['initCount',0x64],['rotation',0x68,'signed'],['fallbackReason',0x6c]
  ]);
  const fontRows=[];
  for(let index=0;index<hdRuntimeConfiguration.fontRows;index++) {
    const p=at(0x400000+hdRuntimeConfiguration.fontTable+index*0x80);
    const row={index,name:hdRuntimeConfiguration.fontNames[index],fontObject:p.add(4).readPointer().toString(),textures:[]};
    for(let density=0;density<4;density++)
      row.textures.push({density:[100,125,150,200][density],
        ...hdTextureFields(p.add(0x18+4*density).readPointer())});
    fontRows.push(row);
  }
  const icon = hdRuntimeConfiguration.iconFields
    ? hdWords(hdRuntimeConfiguration.iconState, hdRuntimeConfiguration.iconFields) : null;
  const iconRows=[];
  hdIconTextures.clear();
  for(let index=0;index<hdRuntimeConfiguration.iconRows;index++) {
    const p=at(0x400000+hdRuntimeConfiguration.iconTable+index*0x80);
    const row={index,originalTexture:p.readPointer().toString(),width:p.add(4).readU32(),height:p.add(8).readU32(),
      status:p.add(12).readS32(),draws:p.add(0x44).readU32(),lastDensity:p.add(0x48).readU32(),fallbacks:p.add(0x4c).readU32(),textures:[]};
    for(let density=0;density<4;density++) {
      const image=p.add(0x10+density*12),texture=image.readPointer();
      row.textures.push({density:[100,125,150,200][density],...hdTextureFields(texture),
        imageWidth:image.add(4).readU16(),imageHeight:image.add(6).readU16(),
        tileWidth:image.add(8).readU16(),tileHeight:image.add(10).readU16()});
      if(!texture.isNull()) hdIconTextures.set(texture.toString(),{index,density:[100,125,150,200][density]});
    }
    iconRows.push(row);
  }
  return {observerInstalled:true,font,icon,fontRows,iconRows,textureLoads:hdTextureLoads,
    fontSamples:hdFontSamples,iconSamples:hdIconSamples};
}

function installHdObservation(configuration) {
  hdRuntimeConfiguration = configuration;
  for (const marker of configuration.markers) {
    if (at(0x400000 + marker.rva).readUtf8String() !== marker.text)
      throw new Error('Selected HD native marker differs');
  }
  // Observe only selected managed filenames, with a fixed maximum; startup
  // may have completed before attachment, so an empty trace is inconclusive.
  for(const address of [at(0x4f2cb4),ptr(0x7404fc)]) Interceptor.attach(address,{
    onEnter(){
      if(hdTextureLoads.length>=128)return;
      try {
        const p=this.context.eax,length=p.sub(4).readU32();
        if(length>256)return;
        const path=p.readUtf16String(length);
        if(!path.toLowerCase().replace(/^base\\/,'').startsWith('ui-hd\\'))return;
        this.row={path,activeScene,thread:Process.getCurrentThreadId(),loader:address.toString()};
      } catch(_) {}
    },
    onLeave(ret){
      if(this.row && hdTextureLoads.length<128){
        this.row.returned=ret.toString();
        if(address.equals(ptr(0x7404fc))) {
          try {this.row.texture=hdTextureFields(ret);} catch(_) {}
        }
        hdTextureLoads.push(this.row);
      }
    }
  });
  // Sample only a small bounded subset, once per density, while the real
  // adapter returns. Its final state supplies actual source/destination data.
  Interceptor.attach(at(configuration.fontDraw), {
    onEnter(){
      const density=at(0xc28f00).readU32();
      this.sample = !hdObservedDensities.has(density);
      this.density = density;
      if(this.sample) this.beforeAdapted=at(0x400000+configuration.fontState+0x20).readU32();
    },
    onLeave(){
      if(this.sample && hdFontSamples.length < 16) {
        const state=hdStatus().font;
        if(state.adaptedGlyphs > this.beforeAdapted && state.selectedTexture !== '0x0' && state.lastPercent === this.density) {
          hdObservedDensities.add(this.density);
          hdFontSamples.push({density:this.density,activeScene,thread:Process.getCurrentThreadId(),state});
        }
      }
    }
  });
  Interceptor.attach(ptr(0x740610),{onEnter(){
    if(hdIconSamples.length>=24) return;
    const identity=hdIconTextures.get(this.context.eax.toString());
    if(!identity)return;
    if((hdIconDensitySamples.get(identity.density)||0)>=6)return;
    const densityIndex=[100,125,150,200].indexOf(identity.density);
    if(!at(0x400000+configuration.iconTable+identity.index*0x80+0x10+densityIndex*12)
      .readPointer().equals(this.context.eax))return;
    const sp=this.context.esp,sourceX=this.context.edx.toInt32(),sourceY=this.context.ecx.toInt32();
    const key=identity.index+':'+identity.density+':'+sourceX+':'+sourceY;
    if(hdIconKeys.has(key))return;
    hdIconKeys.add(key);
    hdIconDensitySamples.set(identity.density,(hdIconDensitySamples.get(identity.density)||0)+1);
    hdIconSamples.push({...identity,texture:this.context.eax.toString(),sourceX,sourceY,
      sourceWidth:sp.add(0x20).readS32(),sourceHeight:sp.add(0x1c).readS32(),
      destinationX:sp.add(0x18).readS32(),destinationY:sp.add(0x14).readS32(),
      destinationWidth:sp.add(0x10).readS32(),destinationHeight:sp.add(0xc).readS32(),
      rotation:sp.add(4).readU8(),color:sp.add(8).readU32(),activeScene,thread:Process.getCurrentThreadId()});
  }});
}

const hdOriginalInitialize = rpc.exports.initialize;
const hdOriginalStatus = rpc.exports.status;
rpc.exports.initialize = function(configuration) {
  const result = hdOriginalInitialize(configuration);
  installHdObservation(HD_OBSERVER_CONFIGURATION);
  sendEvent('hd_observer_installed',{readOnly:true,guiActions:false,gameplayActions:false});
  return result;
};
rpc.exports.status = function() {
  const result=hdOriginalStatus();
  result.uiHd=hdStatus();
  return result;
};
