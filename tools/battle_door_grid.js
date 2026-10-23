// Original .s door cells may be type1 (walkable), whereas72d79c changes a
// closed door to type3. Native6e40a4 excludes that opaque endpoint from sight,
// then72e370 refuses to open it because6e45a0 reports it as unseen.
// Keep collisions in agreement with the door state, and expose ONLY the
// adjacent door surface, never the cells/enemies beyond it. Server permission,
// turn, distance, occupancy and AP checks remain authoritative.
function installBattleDoorGrid(exe) {
  const at=a=>exe.add(a-0x400000);
  if(at(0x6e40a4).readU8()!==0x55 || at(0x6e40a5).readU16()!==0xec8b)
    throw Error('Unrecognized door visibility refresh function');
  if(at(0x72dc90).readU8()!==0x55 || at(0x72dc91).readU16()!==0xec8b)
    throw Error('Unrecognized door state function');
  // 3/4 are deferred close/open states for an unseen surface. Finishing them
  // normally requires that surface to become visible in72fa32. A closed
  // opaque endpoint may never become visible, leaving the door unusable.
  // Apply the received authoritative state via the native stable-state path,
  // which updates sprite, sound and collision together. Crates use flag0.
  Interceptor.attach(at(0x72dc90),{onEnter(){
    const sp=this.context.esp,state=sp.add(8).readU32();
    if(sp.add(4).readU8()===1 && (state===3 || state===4))sp.add(8).writeU32(state-2);
  }});
  function scene() {
    const world=at(0x76e000).readPointer().readPointer();
    if(world.isNull())return null;
    const list=world.add(0xd0).readPointer();
    if(list.isNull())return null;
    const count=list.add(8).readU32();
    if(count>10000)return null;
    const grid=at(0x76e5f4).readPointer().readPointer();
    if(grid.isNull())return null;
    const width=grid.add(0x24).readU16(),height=grid.add(0x26).readU16();
    if(!width || !height || width>128 || height>128)return null;
    const cells=grid.add(12).readPointer(),vision=grid.add(28).readPointer();
    if(cells.isNull() || vision.isNull())return null;
    const items=list.add(4).readPointer(),doors=[];
    for(let i=0;i<count;i++){
      const p=items.add(i*4).readPointer();let state=p.add(0x340).readU8();
      if(state===3 || state===4){
        // Recover an already pending door when attaching to a running scene.
        state-=2;p.add(0x340).writeU8(state);
        p.add(0x28).writeU8((p.add(0x411).readU8()+state-1)&255);
      }
      if(state!==1 && state!==2)continue;
      const x=p.add(4).readS32(),y=p.add(8).readS32();
      if(x>=0 && y>=0 && x<width && y<height)doors.push({x,y,state});
    }
    return {doors,cells,vision,width,height};
  }
  function collisions(s) {
    for(const d of s.doors)s.cells.add(d.x*4).readPointer().add(d.y*14).writeU8(d.state===1?3:0);
  }
  function doorSurfaces(s) {
    const owner=at(0x76dfac).readPointer().readU32();
    const key=at(0x76e068).readPointer().readU16();
    const table=at(0x76e430).readPointer(),actors=[];
    for(let i=0;i<31;i++){
      const a=table.add(i*4).readPointer();
      if(a.isNull() || a.add(0x64).readU32()!==owner || (a.add(8).readU16()^key)===0)continue;
      const x=a.add(0x1bc).readS32(),y=a.add(0x1c0).readS32();
      if(x>=0 && y>=0 && x<s.width && y<s.height)actors.push([x,y]);
    }
    for(const d of s.doors){
      if(d.state!==1)continue;
      const adjacent=actors.some(([x,y])=>{
        const dx=Math.abs(x-d.x),dy=Math.abs(y-d.y);
        return Math.max(dx,dy)===1;
      });
      if(adjacent)s.vision.add(d.x*4).readPointer().add(d.y*6).writeU8(1);
    }
  }
  Interceptor.attach(at(0x6e40a4),{
    onEnter(){const s=scene();if(s)collisions(s);},
    onLeave(){const s=scene();if(s)doorSurfaces(s);}
  });
  // Also supports attaching the fix to an already loaded diagnostic scene.
  const s=scene();if(s){collisions(s);doorSurfaces(s);}
}
