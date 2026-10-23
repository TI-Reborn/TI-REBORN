// Execute the exact launcher adapter against a bounded memory fixture.
// This tests cell ownership/visibility boundaries, not a rendered game scene.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const memory=Buffer.alloc(0x800000),hooks=[];
class Pointer {
  constructor(n){this.n=n;}
  add(n){return new Pointer(this.n+n);}
  isNull(){return this.n===0;}
  readPointer(){return new Pointer(this.readU32());}
  readU32(){return memory.readUInt32LE(this.n);}
  readS32(){return memory.readInt32LE(this.n);}
  readU16(){return memory.readUInt16LE(this.n);}
  readU8(){return memory.readUInt8(this.n);}
  writeU8(v){memory.writeUInt8(v,this.n);}
  writeU32(v){memory.writeUInt32LE(v,this.n);}
}
const put=(a,v)=>memory.writeUInt32LE(v,a);
memory.set([0x55,0x8b,0xec],0x6e40a4);
memory.set([0x55,0x8b,0xec],0x72dc90);
put(0x76e000,0x1000);put(0x1000,0x1100);put(0x11d0,0x1400);
put(0x1404,0x1500);put(0x1408,2);put(0x1500,0x2000);put(0x1504,0x2800);
put(0x2004,3);put(0x2008,3);put(0x2804,7);put(0x2808,7);
memory[0x2340]=1;memory[0x2b40]=1;
put(0x76e5f4,0x1600);put(0x1600,0x1700);put(0x1724,8|(8<<16));
put(0x170c,0x1800);put(0x171c,0x1900);
for(let x=0;x<8;x++){put(0x1800+x*4,0x3000+x*128);put(0x1900+x*4,0x4000+x*64);}
put(0x76dfac,0x1a00);put(0x1a00,7);put(0x76e068,0x1b00);memory[0x1b00]=199;
put(0x76e430,0x5000);put(0x5000,0x6000);put(0x6064,7);memory[0x6008]=100^199;
put(0x61bc,2);put(0x61c0,3);
const cell=(x,y)=>0x3000+x*128+y*14,visible=(x,y)=>0x4000+x*64+y*6;
memory[cell(3,3)]=1;
vm.runInNewContext(fs.readFileSync(__dirname+'/battle_door_grid.js','utf8')+
  '\ninstallBattleDoorGrid(exe);',{exe:new Pointer(0x400000),Interceptor:{attach:(p,h)=>hooks.push(h)}});
assert.equal(hooks.length,2);
assert.equal(memory[cell(3,3)],3);assert.equal(memory[visible(3,3)],1);
assert.equal(memory[visible(4,3)],0);assert.equal(memory[visible(7,7)],0);
const refresh=()=>{hooks[1].onEnter();memory.fill(0,0x4000,0x4200);hooks[1].onLeave();};
for(let n=0;n<3;n++){
  memory[0x2340]=2;refresh();assert.equal(memory[cell(3,3)],0);
  memory[0x2340]=1;refresh();assert.equal(memory[cell(3,3)],3);assert.equal(memory[visible(3,3)],1);
}
// A dead/enemy observer must not reveal even the door's surface.
memory[0x6008]=199;refresh();assert.equal(memory[visible(3,3)],0);
memory[0x6008]=100^199;put(0x6064,8);refresh();assert.equal(memory[visible(3,3)],0);
put(0x6064,7);
// Every neighbor exposes just the surface, including all wall-corner layouts.
for(const dx of [-1,0,1])for(const dy of [-1,0,1]){
  if(!dx && !dy)continue;
  put(0x61bc,3+dx);put(0x61c0,3+dy);
  for(const a of [0,3])for(const b of [0,3]){
    if(dx && dy){memory[cell(3+dx,3)]=a;memory[cell(3,3+dy)]=b;}
    refresh();assert.equal(memory[visible(3,3)],1);
    for(let x=0;x<8;x++)for(let y=0;y<8;y++)
      if(x!==3 || y!==3)assert.equal(memory[visible(x,y)],0);
    if(dx && dy){memory[cell(3+dx,3)]=0;memory[cell(3,3+dy)]=0;}
  }
}
put(0x61bc,0);put(0x61c0,0);refresh();assert.equal(memory[visible(3,3)],0);
// Recover the actual observed hangar failure, even while its surface is unseen.
memory[0x2411]=2;
memory[0x2340]=4;memory[cell(3,3)]=3;refresh();
assert.equal(memory[cell(3,3)],0);assert.equal(memory[0x2340],2);assert.equal(memory[0x2028],3);
memory[0x2340]=3;memory[cell(3,3)]=0;refresh();
assert.equal(memory[cell(3,3)],3);assert.equal(memory[0x2340],1);assert.equal(memory[0x2028],2);
// The upper door can recover independently while the lower one stays closed.
memory[0x2b40]=4;memory[cell(7,7)]=3;refresh();
assert.equal(memory[0x2b40],2);assert.equal(memory[0x2828],1);assert.equal(memory[cell(7,7)],0);
assert.equal(memory[0x2340],1);assert.equal(memory[cell(3,3)],3);
assert.equal(memory[visible(7,7)],0); // No visibility is fabricated at a distance.
// Only the door branch of the native state receiver is adapted, never crates.
for(const flag of [0,1])for(const state of [1,2,3,4]){
  put(0x7004,flag);put(0x7008,state);
  hooks[0].onEnter.call({context:{esp:new Pointer(0x7000)}});
  assert.equal(memory.readUInt32LE(0x7008),flag===1 && state>=3?state-2:state);
}
console.log('Door grid: 3 open/close cycles, sight boundaries, deferred-state recovery and receiver scope PASS');
