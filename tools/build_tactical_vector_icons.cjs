/** Original vector companion to the two generated material icon styles.
 * Geometry is authored here, not traced from or painted into raster masters.
 * Exports review assets only; no native/client/hosting paths are written.
 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const sharp = require('C:/Users/jundu/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');

const ROOT = path.resolve(__dirname, '..');
const OUT = path.join(ROOT, 'reports/ui-hd-assets/icons/vector-b');
const MASTER = path.join(ROOT, 'reports/ui-hd-assets/icons/source/b-tactical-vector.png');
const cream = '#dce7ae', olive = '#61713c';
const symbols = ['map','soldier','crates','money','info','rifle','skills','squad',
                 'handshake','search','refresh','settings','check','left','right','close'];

// Every picture has a 64-square viewBox and four-unit rounded primary strokes.
const geometry = {
  map: `<path d="M6 15 22 9 42 15 58 9V49L42 55 22 49 6 55Z" fill="${olive}"/>
        <path d="M22 9V49M42 15V55M9 29 17 26M9 38 16 36M28 40 34 36 38 40"/>
        <path d="M39 25c0 7-8 14-8 14s-8-7-8-14a8 8 0 1 1 16 0Z" fill="${cream}" stroke="${olive}" stroke-width="2"/>
        <circle cx="31" cy="25" r="2.6" fill="${olive}" stroke="none"/>`,
  soldier: `<path d="M14 53c1-8 7-12 15-13l13 5 7 10H14Z" fill="${olive}"/>
            <path d="M22 25v9l5 7 12-2 4-5 5-1-4-7V20L23 19Z" fill="${olive}"/>
            <path d="M15 23c0-11 6-17 17-17 10 0 18 6 19 17l-13 2-23-2Z" fill="${olive}"/>
            <path d="M18 20H48M22 26 25 33 22 36M30 47l-2 8M39 26h6M29 13h9"/>`,
  crates: `<path d="M9 30 31 24 54 31 32 38Z" fill="${olive}"/>
           <path d="M9 30v22l23 7 22-7V31M32 38v21M16 32v20M46 33v21"/>
           <path d="M14 8 34 4 51 10 32 16Z" fill="${olive}"/>
           <path d="M14 8v15l18 5 19-5V10M32 16v12M23 11v13M40 14v11"/>
           <path d="M22 45h4M38 46h4" stroke-width="3"/>`,
  money: `<path d="M7 14h44v27H7Z" fill="${olive}"/>
          <path d="M12 9h44v27M13 19h5M40 34h5"/>
          <ellipse cx="29" cy="28" rx="7" ry="8" fill="${cream}" stroke="none"/>
          <circle cx="45" cy="47" r="11" fill="${olive}"/>
          <path d="M40 43h10M45 40v14M40 50h10" stroke-width="3"/>`,
  info: `<circle cx="32" cy="32" r="25" fill="${cream}" stroke="${olive}" stroke-width="4"/>
         <circle cx="32" cy="19" r="3" fill="${olive}" stroke="none"/>
         <path d="M29 29h3v17M27 46h10" stroke="${olive}" stroke-width="5"/>`,
  rifle: `<g transform="rotate(-29 32 32)">
           <path d="M7 27h9l5 4v8l-14 6V27Z" fill="${olive}"/>
           <path d="M18 28h26v11H18Z" fill="${olive}"/>
           <path d="M44 31h14M22 25h15M38 28v-5M55 28v6"/>
           <path d="M30 39h8l-1 14h-7ZM21 39h6v9h-6Z" fill="${olive}"/>
           <path d="M22 32h13" stroke-width="3"/>
         </g>`,
  skills: `<path d="M38 5 12 34h17l-5 25 28-35H35Z" fill="${cream}" stroke="${olive}" stroke-width="3"/>`,
  squad: `<g fill="${olive}">
           <path d="M5 53c1-11 5-15 12-15s11 4 12 15ZM35 53c1-11 5-15 12-15s11 4 12 15Z"/>
           <circle cx="17" cy="28" r="9"/><circle cx="47" cy="28" r="9"/>
           <path d="M8 26c0-7 3-11 9-11s9 4 9 11ZM38 26c0-7 3-11 9-11s9 4 9 11Z"/>
           <path d="M18 58c0-13 5-19 14-19s14 6 14 19Z"/>
           <circle cx="32" cy="25" r="10"/><path d="M22 22c0-8 4-12 10-12s10 4 10 12Z"/>
         </g><path d="M29 44v11M35 44v11" stroke-width="3"/>`,
  handshake: `<path d="M5 24 14 15 25 23l-9 19L5 35ZM59 24 50 15 39 23l9 19 11-7Z" fill="${olive}"/>
              <path d="M19 27 28 20 35 22l14 13-4 5-4 5-5 4-5-1-14-13Z" fill="${olive}"/>
              <path d="M41 27 33 22 26 28l-3 5 4 3 8-7M24 37l9 9M29 34l11 11M34 31l11 9" stroke-width="3"/>`,
  search: `<circle cx="26" cy="26" r="18" fill="none"/><path d="M39 40 57 57" stroke-width="7"/>
           <path d="M15 26c0-6 4-11 10-12" stroke-width="2.8"/>`,
  refresh: `<path d="M13 24A21 21 0 0 1 49 15M51 40A21 21 0 0 1 15 49" stroke-width="5"/>
            <path d="M49 6v15H34ZM15 58V43h15Z" fill="${cream}" stroke="none"/>`,
  settings: `<path d="M27 5h10l2 8 6 3 7-4 7 8-5 6 1 7 7 4-4 10-8-1-5 5-1 8H34l-3-7-7-2-6 5-8-7 3-7-2-6-8-2V25l8-3 3-6-3-7 9-5 7 6Z" fill="${olive}" stroke-width="3.5"/>
             <circle cx="33" cy="31" r="10" fill="none" stroke-width="4"/>`,
  check: `<path d="M9 32 24 47 55 15" stroke-width="7" fill="none"/>`,
  left: `<path d="M42 9 19 32 42 55" stroke-width="7" fill="none"/>`,
  right: `<path d="M22 9 45 32 22 55" stroke-width="7" fill="none"/>`,
  close: `<path d="M13 13 51 51M51 13 13 51" stroke-width="7" fill="none"/>`,
};
function svg(name) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"><g stroke="${cream}" stroke-width="4" stroke-linejoin="round" stroke-linecap="round" fill="none">${geometry[name]}</g></svg>`;
}
function sha(data) { return crypto.createHash('sha256').update(data).digest('hex'); }
function writeExclusive(filename, data) {
  const resolved = path.resolve(filename);
  if (!resolved.startsWith(ROOT + path.sep)) throw Error('Output escaped workspace');
  fs.mkdirSync(path.dirname(filename), {recursive:true});
  fs.writeFileSync(filename, data, {flag:'wx'});
  return {file:resolved, bytes:data.length, sha256:sha(data)};
}
async function main() {
  if (fs.existsSync(OUT) || fs.existsSync(MASTER)) throw Error('Preserve existing vector artifacts; output already exists');
  const manifest = {schema:1, status:'ORIGINAL_VECTOR_SOURCE_STATIC_VALIDATION_ONLY',
    generated_from_geometry:true, traced_from_raster:false, raster_retouched:false,
    client_installable:false, graphical_client_validation:false, published:false,
    palette:{cream,olive}, viewBox:[0,0,64,64], primaryStroke:4,
    native_logical_glyph_contract:[40,40], source_grid:[4,4], source_cell:320,
    master:'b-tactical-vector.png', renderer:sharp.versions, symbols:[]};
  const layers=[];
  for (let index=0; index<symbols.length; index++) {
    const name=symbols[index], text=svg(name);
    const rec=writeExclusive(path.join(OUT,'svg',name+'.svg'),Buffer.from(text));
    const png=await sharp(Buffer.from(text),{density:288}).resize(204,204).png().toBuffer();
    layers.push({input:png,left:index%4*320+58,top:Math.floor(index/4)*320+58});
    const exports=[];
    for (const density of [100,125,150,200]) {
      const side=40*density/100;
      const buf=await sharp(Buffer.from(text),{density:288}).resize(side,side).png().toBuffer();
      const raw=await sharp(buf).ensureAlpha().raw().toBuffer({resolveWithObject:true});
      let zero=0,visible=0,red=0;
      for(let p=0;p<raw.data.length;p+=4) {
        const [r,g,b,a]=raw.data.subarray(p,p+4);
        if(a===0)zero++;else visible++;
        if(a>8 && r>160 && g<70 && b<70)red++;
      }
      if(!zero || !visible || red)throw Error('Vector RGBA/palette validation failed: '+name);
      if(raw.data[3] || raw.data[raw.data.length-1])throw Error('Vector touched a transparent corner: '+name);
      const image=writeExclusive(path.join(OUT,'rgba',String(density),name+'.png'),buf);
      exports.push({...image,density,dimensions:[side,side],zeroAlphaPixels:zero,visiblePixels:visible,strongRedPixels:red});
    }
    manifest.symbols.push({name,index,source:rec,exports});
  }
  const master=await sharp({create:{width:1280,height:1280,channels:4,background:{r:0,g:0,b:0,alpha:0}}}).composite(layers).png().toBuffer();
  manifest.masterRecord=writeExclusive(MASTER,master);
  manifest.checks={PASS:true,distinctSymbolCount:16,directVectorDensityRenders:64,genuineAlpha:true,clientOrHostingChanges:false};
  writeExclusive(path.join(OUT,'manifest.json'),Buffer.from(JSON.stringify(manifest,null,2)));
  process.stdout.write(JSON.stringify({PASS:true,source:MASTER,vectorDirectory:OUT,masterSha256:sha(master),symbols:16,densities:[100,125,150,200],published:false}));
}
main().catch(e=>{process.stderr.write(e.stack);process.exitCode=1;});
