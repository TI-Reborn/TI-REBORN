"""Technical UV/codec export of AI art; keep native masks and geometry."""
from reservation_texture_assets import *
from PIL import Image
from collections import deque
from tools.reservation_texture_ground import align_ground_base

def islands(image):
    """Find substantial UV islands, excluding JPEG mask speckles/shadows."""
    w,h=image.size;alpha=bytearray(image.getchannel('A').tobytes());parts=[]
    for start,value in enumerate(alpha):
        if value<192:continue
        alpha[start]=0;queue=deque([start]);points=[]
        while queue:
            i=queue.popleft();points.append(i);x=i%w;y=i//w
            for n in (i-1 if x else -1,i+1 if x+1<w else -1,i-w if y else -1,i+w if y+1<h else -1):
                if n>=0 and alpha[n]>=192:alpha[n]=0;queue.append(n)
        if len(points)>=max(12,w*h//1000):
            xs=[i%w for i in points];ys=[i//w for i in points]
            parts.append((min(xs),min(ys),max(xs)+1,max(ys)+1,len(points)))
    return sorted(parts,key=lambda b:-b[4])

def align_uv(art,reference):
    art=art.resize(reference.size,Image.Resampling.LANCZOS)
    old,new=islands(reference),islands(art)
    # Art may contain a feathered edge; mapping each matching sprite's bounds
    # restores the source atlas's margins before applying its exact native mask.
    if old and len(old)==len(new) and len(old)<=32:
        canvas=Image.new('RGBA',reference.size);remaining=list(new)
        for box in old:
            x,y=(box[0]+box[2])/2,(box[1]+box[3])/2
            match=min(remaining,key=lambda b:((b[0]+b[2])/2-x)**2+((b[1]+b[3])/2-y)**2)
            remaining.remove(match)
            sprite=art.crop(match[:4]).resize((box[2]-box[0],box[3]-box[1]),Image.Resampling.LANCZOS)
            canvas.paste(sprite,box[:2])
        return canvas,dict(source_islands=len(old),generated_islands=len(new),registration='individual UV bounds')
    if 1<=len(old)<=2 and 1<=len(new)<=2:
        src=reference.getchannel('A').point(lambda a:255 if a>=128 else 0).getbbox()
        dst=art.getchannel('A').point(lambda a:255 if a>=128 else 0).getbbox()
        if src and dst:
            canvas=Image.new('RGBA',reference.size)
            canvas.paste(art.crop(dst).resize((src[2]-src[0],src[3]-src[1]),Image.Resampling.LANCZOS),src[:2])
            return canvas,dict(source_islands=len(old),generated_islands=len(new),registration='combined UV bounds; exact source gap mask')
    return art,dict(source_islands=len(old),generated_islands=len(new),registration='original canvas dimensions')

def encode(raw, image, reference):
    if raw.startswith(bytes.fromhex('07e181')):
        key=100;plain=bytearray()
        for cipher in raw:
            plain.append(cipher^(key>>8));key=((key+cipher)*0xce6d+0x58bf)&65535
        color_size,mask_size=struct.unpack_from('<QQ',plain,39)
        color=io.BytesIO();image.convert('RGB').save(color,format='JPEG',quality=96,subsampling=0)
        header=bytearray(plain[:55]);struct.pack_into('<QQ',header,39,len(color.getvalue()),mask_size)
        payload=header+color.getvalue()+plain[55+color_size:]
        encrypted=bytearray();key=100
        for value in payload:
            cipher=value^(key>>8);encrypted.append(cipher);key=((key+cipher)*0xce6d+0x58bf)&65535
        return encrypted
    output=io.BytesIO();image=image.convert('RGBA');image.putalpha(reference.getchannel('A'))
    # Preserve BMP32's native alpha bytes: Pillow discards them when reading
    # BI_RGB bitmaps, although the game consumes them as a transparency mask.
    if raw.startswith(b'BM'):
        offset=struct.unpack_from('<I',raw,10)[0]
        width,height,planes,bits,compression=struct.unpack_from('<iiHHI',raw,18)
        if bits==32 and compression==0:
            assert planes==1 and image.size==(width,abs(height))
            payload=bytearray(raw);rgb=image.convert('RGB').tobytes();stride=width*4
            assert offset+stride*abs(height)<=len(payload)
            for y in range(abs(height)):
                row=abs(height)-1-y if height>0 else y
                for x in range(width):
                    source=(y*width+x)*3;target=offset+row*stride+x*4
                    r,g,b=rgb[source:source+3];payload[target:target+3]=bytes((b,g,r))
            return bytes(payload)
        image.convert('RGB').save(output,format='BMP')
        return output.getvalue()
    image.save(output,format='TGA' if raw[2:3] in (b'\x02',b'\x0a') else 'PNG')
    return output.getvalue()

def export(partial=False):
    from tools.build_visual_asset_catalog import decode
    tasks=json.loads((ASSETS/'tasks.json').read_text());mapping=json.loads((OUT/'names.json').read_text())
    target=OUT/'client/base/setting/reservation_v2';saved=ASSETS/'generated';saved.mkdir(exist_ok=True)
    proofs=[];generated=[]
    for task in tasks:
        raw=fetch(task['path']).read_bytes();reference,_=decode(raw);dest=target/mapping[task['id']]
        if task['shadow']:
            dest.write_bytes(raw);proofs.append(dict(id=task['id'],shadow_preserved=True));continue
        index=ASSETS/'generated-index'/(task['id']+'.json')
        if partial and not index.exists():continue
        record=json.loads(index.read_text())
        created=Path(record['path']);stable=saved/(Path(task['id']).stem+'.png');stable.write_bytes(created.read_bytes())
        generated.append(dict(id=task['id'],path=str(stable),imagegen_source=str(created),mode='built-in image_gen'))
        art=Image.open(stable).convert('RGBA')
        if task['id'].startswith('ground_') and '_base_' in task['id']:
            art=align_ground_base(art,reference.size)
            registration=dict(registration='two ground rhombi')
        else:
            art,registration=align_uv(art,reference)
        rgba=list(art.getdata());source=list(reference.getdata());w,h=reference.size
        needed=[i for i,(a,b) in enumerate(zip(rgba,source)) if a[3]<32 and b[3]>64 and max(b[:3])>20]
        if needed:
            nearest=[-1]*(w*h);queue=deque()
            for i,p in enumerate(rgba):
                if p[3]>=64:nearest[i]=i;queue.append(i)
            if not queue:raise ValueError('Generated sprite is empty')
            while queue:
                i=queue.popleft();x=i%w;y=i//w
                for n in (i-1 if x else -1,i+1 if x+1<w else -1,i-w if y else -1,i+w if y+1<h else -1):
                    if n>=0 and nearest[n]<0:nearest[n]=nearest[i];queue.append(n)
            for i in needed:rgba[i]=rgba[nearest[i]]
        # Native shadows, openings and unused white atlas padding are masks,
        # not paintable material. Keep their original pixel values.
        for i,p in enumerate(source):
            if max(p[:3])<=22 or min(p[:3])>=248:rgba[i]=p
        art.putdata(rgba)
        dest.write_bytes(encode(raw,art,reference));check,_=decode(dest.read_bytes())
        assert check.size==reference.size and check.getchannel('A').tobytes()==reference.getchannel('A').tobytes(),task['id']
        assert dest.read_bytes()!=raw,task['id']
        proofs.append(dict(id=task['id'],target=dest.relative_to(OUT/'client').as_posix(),size=list(check.size),sha=sha(dest.read_bytes()),original_alpha_exact=True,**registration))
    (ASSETS/'generated.json').write_text(json.dumps(generated,indent=2)+'\n')
    (OUT/'texture-proof.json').write_text(json.dumps(proofs,indent=2)+'\n')
    print(json.dumps(dict(ai_textures=len(generated),original_shadows=sum(t['shadow'] for t in tasks),pending=sum(not t['shadow'] for t in tasks)-len(generated),alpha='exact original masks')))

if __name__=='__main__':
    import sys
    sys.path.insert(0,str(ROOT));export('--partial' in sys.argv)
